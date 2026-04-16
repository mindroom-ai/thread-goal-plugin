# ruff: noqa: INP001
"""Hook entrypoint for the MindRoom thread-goal plugin."""

from __future__ import annotations

from mindroom.hooks import EnrichmentItem, MessageEnrichContext, hook
from .state import read_thread_goal as read_thread_goal_state


@hook(
    event="message:enrich",
    name="thread-goal-context",
    priority=40,
    timeout_ms=1000,
)
async def inject_thread_goal(ctx: MessageEnrichContext) -> list[EnrichmentItem]:
    """Inject the current thread goal into the model prompt."""
    target = ctx.envelope.target
    if target.source_thread_id is None:
        return []
    thread_id = target.resolved_thread_id or target.source_thread_id

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

__all__ = ["inject_thread_goal"]
