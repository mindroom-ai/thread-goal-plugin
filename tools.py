# ruff: noqa: INP001
"""Agent-facing tools for the MindRoom thread-goal plugin."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

from mindroom.plugin_api import (
    HookBindings,
    SetupType,
    ToolCategory,
    ToolFileAccess,
    Toolkit,
    ToolRuntimeContext,
    ToolStatus,
    get_tool_runtime_context,
    register_tool_with_metadata,
    tool,
)

from .state import (
    MAX_GOAL_CHARS,
    ThreadGoalRecord,
    has_thread_goal_content,
    normalize_goal_text,
    query_thread_goal_content,
)
from .state import clear_thread_goal as clear_thread_goal_state
from .state import read_thread_goal as read_thread_goal_state
from .state import write_thread_goal as write_thread_goal_state

_VALID_ACTIONS = ("get", "set", "clear")


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
) -> tuple[ToolRuntimeContext, str, str, HookBindings] | str:
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

    bindings = context.hooks
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

    offer_background_after = False
    offer_output_path = False

    def __init__(self) -> None:
        super().__init__(
            name="thread_goal",
            instructions=(
                'Use `thread_goal(action="get"|"set"|"clear")` to inspect, update, or clear '
                "the current thread's high-level objective. Goals are short, shared thread "
                f"metadata and must be {MAX_GOAL_CHARS} characters or fewer."
            ),
        )

    @tool
    async def thread_goal(
        self,
        action: Literal["get", "set", "clear"],
        goal: str | None = None,
    ) -> str:
        """Get, set, or clear the current thread's shared goal.

        Args:
            action: Operation to run: "get", "set", or "clear".
            goal: Short thread objective. Required for action="set"; omit for "get" and "clear".
        """
        if not isinstance(action, str) or action not in _VALID_ACTIONS:
            return _payload(
                "error",
                message=f"Unsupported thread_goal action {action!r}. Expected one of: {', '.join(_VALID_ACTIONS)}.",
            )
        if action == "set":
            return await self._set_thread_goal(goal)
        if goal is not None:
            return _context_error(action, message=f"Parameter 'goal' cannot be used with action={action!r}.")
        if action == "get":
            return await self._get_thread_goal()
        return await self._clear_thread_goal()

    @staticmethod
    async def _set_thread_goal(goal: str | None) -> str:
        if not isinstance(goal, str):
            message = "Parameter 'goal' is required for action='set'." if goal is None else "goal must be a string."
            return _context_error("set", message=message)
        try:
            normalized_goal = normalize_goal_text(goal)
        except ValueError as exc:
            return _context_error("set", message=str(exc))

        resolved = _resolve_state_access(action="set", require_putter=True)
        if isinstance(resolved, str):
            return resolved
        context, room_id, thread_id, bindings = resolved

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

    @staticmethod
    async def _get_thread_goal() -> str:
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

    @staticmethod
    async def _clear_thread_goal() -> str:
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
    file_access=ToolFileAccess.NONE,
    display_name="Thread Goal",
    description="Set, read, and clear a short shared goal for the current Matrix thread.",
    category=ToolCategory.PRODUCTIVITY,
    status=ToolStatus.AVAILABLE,
    setup_type=SetupType.NONE,
    icon="CiBullseye",
    icon_color="text-amber-500",
    action_scoped_grants=("thread_goal",),
    retired_functions={
        "set_thread_goal": "thread_goal",
        "get_thread_goal": "thread_goal",
        "clear_thread_goal": "thread_goal",
    },
)
def thread_goal_factory() -> type[ThreadGoalTools]:
    """Factory function for the thread-goal toolkit."""
    return ThreadGoalTools
