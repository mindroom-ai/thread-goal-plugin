# ruff: noqa: INP001
"""Thread goal state helpers backed by Matrix room state."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

THREAD_GOAL_EVENT_TYPE = "com.mindroom.thread.goal"
MAX_GOAL_CHARS = 160

type RoomStateQuerier = Callable[[str, str, str | None], Awaitable[dict[str, Any] | None]]
type RoomStatePutter = Callable[[str, str, str, dict[str, Any]], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class ThreadGoalRecord:
    """One normalized thread-goal record."""

    goal: str
    set_by: str
    set_at: str


def _normalize_non_empty_string(value: object) -> str | None:
    """Return one stripped non-empty string."""
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    if not normalized:
        return None
    return normalized


def normalize_goal_text(goal: object) -> str:
    """Normalize one goal string and enforce the V1 size limit."""
    if not isinstance(goal, str):
        msg = "goal must be a string."
        raise TypeError(msg)

    normalized = " ".join(goal.split())
    if not normalized:
        msg = "goal must be a non-empty string."
        raise ValueError(msg)
    if len(normalized) > MAX_GOAL_CHARS:
        msg = f"goal must be {MAX_GOAL_CHARS} characters or fewer."
        raise ValueError(msg)
    return normalized


def goal_state_key(thread_root_event_id: object) -> str:
    """Normalize one thread-root event ID for Matrix state storage."""
    normalized = _normalize_non_empty_string(thread_root_event_id)
    if normalized is None:
        msg = "thread_root_event_id must be a non-empty string."
        raise ValueError(msg)
    return normalized


def parse_thread_goal_content(content: object) -> ThreadGoalRecord | None:
    """Parse one Matrix room-state payload into a typed record."""
    if not isinstance(content, Mapping):
        return None
    if not content:
        return None

    goal = _normalize_non_empty_string(content.get("goal"))
    set_by = _normalize_non_empty_string(content.get("set_by"))
    set_at = _normalize_non_empty_string(content.get("set_at"))
    if goal is None or set_by is None or set_at is None:
        return None

    try:
        normalized_goal = normalize_goal_text(goal)
    except (TypeError, ValueError):
        return None

    return ThreadGoalRecord(goal=normalized_goal, set_by=set_by, set_at=set_at)


def serialize_thread_goal_content(record: ThreadGoalRecord) -> dict[str, str]:
    """Serialize one typed record into the Matrix payload shape."""
    return {
        "goal": record.goal,
        "set_by": record.set_by,
        "set_at": record.set_at,
    }


def has_thread_goal_content(content: object) -> bool:
    """Return whether one queried state payload represents stored goal content."""
    return isinstance(content, Mapping) and bool(content)


async def query_thread_goal_content(
    query_room_state: RoomStateQuerier,
    room_id: str,
    thread_root_event_id: str,
) -> dict[str, Any] | None:
    """Fetch the raw goal payload for one thread."""
    return await query_room_state(
        room_id,
        THREAD_GOAL_EVENT_TYPE,
        goal_state_key(thread_root_event_id),
    )


async def read_thread_goal(
    query_room_state: RoomStateQuerier,
    room_id: str,
    thread_root_event_id: str,
) -> ThreadGoalRecord | None:
    """Read and parse one thread-goal record."""
    content = await query_thread_goal_content(query_room_state, room_id, thread_root_event_id)
    return parse_thread_goal_content(content)


async def write_thread_goal(
    put_room_state: RoomStatePutter,
    room_id: str,
    thread_root_event_id: str,
    record: ThreadGoalRecord,
) -> bool:
    """Write one thread-goal record."""
    return await put_room_state(
        room_id,
        THREAD_GOAL_EVENT_TYPE,
        goal_state_key(thread_root_event_id),
        serialize_thread_goal_content(record),
    )


async def clear_thread_goal(
    put_room_state: RoomStatePutter,
    room_id: str,
    thread_root_event_id: str,
) -> bool:
    """Clear one thread goal by writing a tombstone payload."""
    return await put_room_state(
        room_id,
        THREAD_GOAL_EVENT_TYPE,
        goal_state_key(thread_root_event_id),
        {},
    )
