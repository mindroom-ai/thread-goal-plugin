# ruff: noqa: INP001
"""Agent-facing tools for the MindRoom thread-goal plugin."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from importlib import util as importlib_util
from pathlib import Path

from agno.tools import Toolkit

from mindroom.tool_system.metadata import (
    SetupType,
    ToolCategory,
    ToolStatus,
    register_tool_with_metadata,
)
from mindroom.tool_system.runtime_context import (
    ToolRuntimeContext,
    ToolRuntimeHookBindings,
    get_tool_runtime_context,
    resolve_tool_runtime_hook_bindings,
)

# MindRoom loads plugin files (hooks.py, tools.py) by absolute path using
# importlib.util.spec_from_file_location, so they aren't part of a real Python
# package. Normal relative imports like ``from . import state`` don't work.
# We load the sibling ``state.py`` the same way and cache it in sys.modules
# so both hooks.py and tools.py share one instance.
_PLUGIN_ROOT = Path(__file__).resolve().parent
_STATE_MOD = "_thread_goal_state"
if _STATE_MOD in sys.modules:
    state = sys.modules[_STATE_MOD]
else:
    _state_spec = importlib_util.spec_from_file_location(_STATE_MOD, _PLUGIN_ROOT / "state.py")
    assert _state_spec is not None and _state_spec.loader is not None  # noqa: S101
    state = importlib_util.module_from_spec(_state_spec)
    sys.modules[_STATE_MOD] = state
    _state_spec.loader.exec_module(state)

MAX_GOAL_CHARS: int = state.MAX_GOAL_CHARS
ThreadGoalRecord = state.ThreadGoalRecord
clear_thread_goal_state = state.clear_thread_goal
has_thread_goal_content = state.has_thread_goal_content
normalize_goal_text = state.normalize_goal_text
query_thread_goal_content = state.query_thread_goal_content
read_thread_goal_state = state.read_thread_goal
write_thread_goal_state = state.write_thread_goal


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _payload(status: str, **kwargs: object) -> str:
    payload: dict[str, object] = {"status": status, "tool": "thread_goal"}
    payload.update(kwargs)
    return json.dumps(payload, sort_keys=True)


def _resolve_scope(
    context: ToolRuntimeContext,
) -> tuple[ToolRuntimeContext, str, str] | tuple[None, None, None]:
    """Return the resolved thread scope for one thread-scoped tool call."""
    if context.thread_id is None:
        return None, None, None

    return context, context.room_id, context.resolved_thread_id or context.thread_id


def _context_error(action: str, *, message: str) -> str:
    return _payload("error", action=action, message=message)


def _resolve_state_access(
    *,
    action: str,
    require_putter: bool,
) -> tuple[ToolRuntimeContext, str, str, ToolRuntimeHookBindings] | str:
    """Resolve the active thread scope and room-state bindings."""
    context = get_tool_runtime_context()
    if context is None:
        return _context_error(
            action,
            message="Thread goal tool context is unavailable in this runtime path.",
        )
    resolved_scope = _resolve_scope(context)
    if resolved_scope[0] is None:
        return _context_error(
            action,
            message=f"An active thread is required to {action} a thread goal.",
        )
    context, room_id, thread_id = resolved_scope

    bindings = resolve_tool_runtime_hook_bindings(context)
    if bindings.room_state_querier is None:
        return _context_error(
            action,
            message="Thread goal room-state access is unavailable in this runtime path.",
        )
    if require_putter and bindings.room_state_putter is None:
        return _context_error(
            action,
            message="Thread goal room-state access is unavailable in this runtime path.",
        )

    return context, room_id, thread_id, bindings


class ThreadGoalTools(Toolkit):
    """Toolkit for storing and reading per-thread goals in Matrix state."""

    def __init__(self) -> None:
        super().__init__(
            name="thread_goal",
            instructions=(
                "Use these tools to capture the current thread's high-level objective. "
                "Goals are short, shared thread metadata and should stay under "
                f"{MAX_GOAL_CHARS} characters."
            ),
            tools=[
                self.set_thread_goal,
                self.get_thread_goal,
                self.clear_thread_goal,
            ],
        )

    async def set_thread_goal(self, goal: str) -> str:
        """Set or update the current thread goal."""
        resolved = _resolve_state_access(action="set", require_putter=True)
        if isinstance(resolved, str):
            return resolved
        context, room_id, thread_id, bindings = resolved

        try:
            normalized_goal = normalize_goal_text(goal)
        except (TypeError, ValueError) as exc:
            return _context_error("set", message=str(exc))

        existing = await read_thread_goal_state(bindings.room_state_querier, room_id, thread_id)
        if existing is not None and existing.goal == normalized_goal:
            return _payload(
                "ok",
                action="set",
                room_id=room_id,
                thread_id=thread_id,
                changed=False,
                goal=existing.goal,
                set_by=existing.set_by,
                set_at=existing.set_at,
            )

        record = ThreadGoalRecord(
            goal=normalized_goal,
            set_by=context.agent_name or context.requester_id,
            set_at=_now_iso(),
        )
        written = await write_thread_goal_state(bindings.room_state_putter, room_id, thread_id, record)
        if not written:
            return _context_error("set", message="Failed to write the thread goal state event.")

        return _payload(
            "ok",
            action="set",
            room_id=room_id,
            thread_id=thread_id,
            changed=True,
            goal=record.goal,
            set_by=record.set_by,
            set_at=record.set_at,
        )

    async def get_thread_goal(self) -> str:
        """Return the current thread goal when one is set."""
        resolved = _resolve_state_access(action="get", require_putter=False)
        if isinstance(resolved, str):
            return resolved
        _, room_id, thread_id, bindings = resolved

        record = await read_thread_goal_state(bindings.room_state_querier, room_id, thread_id)
        if record is None:
            return _payload(
                "ok",
                action="get",
                room_id=room_id,
                thread_id=thread_id,
                found=False,
                goal=None,
                message="No goal set.",
            )

        return _payload(
            "ok",
            action="get",
            room_id=room_id,
            thread_id=thread_id,
            found=True,
            goal=record.goal,
            set_by=record.set_by,
            set_at=record.set_at,
        )

    async def clear_thread_goal(self) -> str:
        """Clear the current thread goal."""
        resolved = _resolve_state_access(action="clear", require_putter=True)
        if isinstance(resolved, str):
            return resolved
        _, room_id, thread_id, bindings = resolved

        existing_content = await query_thread_goal_content(bindings.room_state_querier, room_id, thread_id)
        if not has_thread_goal_content(existing_content):
            return _payload(
                "ok",
                action="clear",
                room_id=room_id,
                thread_id=thread_id,
                changed=False,
            )

        written = await clear_thread_goal_state(bindings.room_state_putter, room_id, thread_id)
        if not written:
            return _context_error("clear", message="Failed to clear the thread goal state event.")

        return _payload(
            "ok",
            action="clear",
            room_id=room_id,
            thread_id=thread_id,
            changed=True,
        )


@register_tool_with_metadata(
    name="thread_goal",
    display_name="Thread Goal",
    description="Set, read, and clear a short shared goal for the current Matrix thread.",
    category=ToolCategory.PRODUCTIVITY,
    status=ToolStatus.AVAILABLE,
    setup_type=SetupType.NONE,
    icon="CiBullseye",
    icon_color="text-amber-500",
)
def thread_goal_factory() -> type[ThreadGoalTools]:
    """Factory function for the thread-goal toolkit."""
    return ThreadGoalTools
