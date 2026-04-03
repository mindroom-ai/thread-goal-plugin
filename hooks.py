# ruff: noqa: INP001
"""Hook entrypoint for the MindRoom thread-goal plugin."""

from __future__ import annotations

import sys
from importlib import util as importlib_util
from pathlib import Path

from mindroom.hooks import EnrichmentItem, MessageEnrichContext, hook

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

read_thread_goal_state = state.read_thread_goal


@hook(
    event="message:enrich",
    name="thread-goal-context",
    priority=40,
    timeout_ms=1000,
)
async def inject_thread_goal(ctx: MessageEnrichContext) -> list[EnrichmentItem]:
    """Inject the current thread goal into the model prompt."""
    if ctx.envelope.target.thread_id is None:
        return []
    thread_id = ctx.envelope.target.resolved_thread_id or ctx.envelope.target.thread_id

    record = await read_thread_goal_state(ctx.query_room_state, ctx.envelope.room_id, thread_id)
    if record is None:
        return []

    return [
        EnrichmentItem(
            key="thread_goal",
            text=f"Thread goal: {record.goal}",
            cache_policy="stable",
        ),
    ]


__all__ = ["inject_thread_goal", "state"]
