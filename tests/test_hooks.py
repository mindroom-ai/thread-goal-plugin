# ruff: noqa: INP001
"""Tests for the thread-goal enrichment hook."""

from __future__ import annotations

from importlib import util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from mindroom.hooks.decorators import get_hook_metadata

if TYPE_CHECKING:
    from types import ModuleType

PACKAGE_NAME = f"mindroom_plugin_{Path(__file__).resolve().parents[1].name.replace('-', '_')}"


def _load_hooks_module() -> ModuleType:
    """Load the plugin hooks module under its synthetic package name."""
    hooks_path = Path(__file__).resolve().parents[1] / "hooks.py"
    module_name = f"{PACKAGE_NAME}.hooks"
    sys.modules.pop(module_name, None)
    spec = util.spec_from_file_location(module_name, hooks_path)
    assert spec is not None
    assert spec.loader is not None
    module = util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _context(
    *,
    thread_id: str | None = "$thread-root",
    resolved_thread_id: str | None = "$thread-root",
    goal_content: dict[str, object] | None = None,
) -> SimpleNamespace:
    """Build a minimal enrichment-hook context stub."""
    return SimpleNamespace(
        envelope=SimpleNamespace(
            room_id="!room:localhost",
            target=SimpleNamespace(
                thread_id=thread_id,
                resolved_thread_id=resolved_thread_id,
            ),
        ),
        query_room_state=AsyncMock(return_value=goal_content),
    )


def test_hook_metadata_matches_the_issue_spec() -> None:
    """The hook decorator should match the issue's priority and timeout."""
    module = _load_hooks_module()
    metadata = get_hook_metadata(module.inject_thread_goal)

    assert metadata is not None
    assert metadata.event_name == "message:enrich"
    assert metadata.hook_name == "thread-goal-context"
    assert metadata.priority == 40
    assert metadata.timeout_ms == 1000


@pytest.mark.asyncio
async def test_enrichment_returns_stable_thread_goal() -> None:
    """A stored goal should become one stable enrichment item."""
    module = _load_hooks_module()
    ctx = _context(
        goal_content={
            "goal": "Ship ISSUE-083 safely",
            "set_by": "code",
            "set_at": "2026-04-03T10:00:00+00:00",
        },
    )

    items = await module.inject_thread_goal(ctx)

    assert len(items) == 1
    assert items[0].key == "thread_goal"
    assert items[0].text == "Thread goal: Ship ISSUE-083 safely"
    assert items[0].cache_policy == "stable"


@pytest.mark.asyncio
async def test_enrichment_returns_empty_without_thread_or_goal() -> None:
    """Missing thread scope or tombstones should produce no enrichment."""
    module = _load_hooks_module()

    no_thread_ctx = _context(thread_id=None, goal_content=None)
    assert await module.inject_thread_goal(no_thread_ctx) == []
    no_thread_ctx.query_room_state.assert_not_awaited()

    room_reply_ctx = _context(
        thread_id=None,
        resolved_thread_id="$reply:localhost",
        goal_content={
            "goal": "Should stay thread-only",
            "set_by": "code",
            "set_at": "2026-04-03T10:00:00+00:00",
        },
    )
    assert await module.inject_thread_goal(room_reply_ctx) == []
    room_reply_ctx.query_room_state.assert_not_awaited()

    no_goal_ctx = _context(goal_content={})
    assert await module.inject_thread_goal(no_goal_ctx) == []
    no_goal_ctx.query_room_state.assert_awaited_once()
