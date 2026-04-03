# ruff: noqa: INP001
"""Tests for the thread-goal toolkit."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from mindroom.tool_system.runtime_context import ToolRuntimeContext, tool_runtime_context

if TYPE_CHECKING:
    from types import ModuleType


def _load_tools_module() -> ModuleType:
    """Load the plugin tools module directly from disk."""
    tools_path = Path(__file__).resolve().parents[1] / "tools.py"
    module_name = "thread_goal_tools_test"
    spec = importlib.util.spec_from_file_location(module_name, tools_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _tool_context(
    *,
    thread_id: str | None = "$thread-root",
    resolved_thread_id: str | None = "$thread-root",
    room_state_querier: AsyncMock | None = None,
    room_state_putter: AsyncMock | None = None,
) -> ToolRuntimeContext:
    return ToolRuntimeContext(
        agent_name="code",
        room_id="!room:localhost",
        thread_id=thread_id,
        resolved_thread_id=resolved_thread_id,
        requester_id="@user:localhost",
        client=AsyncMock(),
        config=SimpleNamespace(),
        runtime_paths=SimpleNamespace(),
        room_state_querier=room_state_querier,
        room_state_putter=room_state_putter,
    )


def test_set_thread_goal_schema_requires_goal() -> None:
    """The toolkit schema should expose one required goal argument."""
    module = _load_tools_module()

    tools = module.ThreadGoalTools()
    function = tools.async_functions["set_thread_goal"]
    function.process_entrypoint()
    schema = function.parameters

    assert "goal" in schema["required"]
    assert schema["properties"]["goal"]["type"] == "string"


@pytest.mark.asyncio
async def test_set_get_clear_cycle_and_idempotency() -> None:
    """Setting the same goal twice should avoid a duplicate state write."""
    module = _load_tools_module()
    tools = module.ThreadGoalTools()
    state: dict[tuple[str, str, str], dict[str, object]] = {}

    async def query(
        room_id: str,
        event_type: str,
        state_key: str | None,
    ) -> dict[str, object] | None:
        assert state_key is not None
        return state.get((room_id, event_type, state_key))

    async def put(
        room_id: str,
        event_type: str,
        state_key: str,
        content: dict[str, object],
    ) -> bool:
        state[(room_id, event_type, state_key)] = dict(content)
        return True

    querier = AsyncMock(side_effect=query)
    putter = AsyncMock(side_effect=put)

    with tool_runtime_context(
        _tool_context(room_state_querier=querier, room_state_putter=putter),
    ):
        set_result = json.loads(await tools.set_thread_goal("  Ship\n ISSUE-083 safely  "))
        repeat_result = json.loads(await tools.set_thread_goal("Ship ISSUE-083 safely"))
        get_result = json.loads(await tools.get_thread_goal())
        clear_result = json.loads(await tools.clear_thread_goal())
        empty_result = json.loads(await tools.get_thread_goal())

    assert set_result["status"] == "ok"
    assert set_result["action"] == "set"
    assert set_result["changed"] is True
    assert set_result["goal"] == "Ship ISSUE-083 safely"
    assert set_result["set_by"] == "code"

    assert repeat_result["changed"] is False
    assert putter.await_count == 2

    assert get_result == {
        "action": "get",
        "found": True,
        "goal": "Ship ISSUE-083 safely",
        "room_id": "!room:localhost",
        "set_at": set_result["set_at"],
        "set_by": "code",
        "status": "ok",
        "thread_id": "$thread-root",
        "tool": "thread_goal",
    }

    assert clear_result == {
        "action": "clear",
        "changed": True,
        "room_id": "!room:localhost",
        "status": "ok",
        "thread_id": "$thread-root",
        "tool": "thread_goal",
    }
    assert empty_result["found"] is False
    assert empty_result["goal"] is None


@pytest.mark.asyncio
async def test_unresolved_thread_context_returns_clear_error() -> None:
    """The toolkit should reject room-mode contexts with no resolved thread."""
    module = _load_tools_module()
    tools = module.ThreadGoalTools()

    with tool_runtime_context(
        _tool_context(
            thread_id=None,
            resolved_thread_id=None,
            room_state_querier=AsyncMock(),
            room_state_putter=AsyncMock(),
        ),
    ):
        result = json.loads(await tools.set_thread_goal("Ship it"))

    assert result == {
        "action": "set",
        "message": "An active thread is required to set a thread goal.",
        "status": "error",
        "tool": "thread_goal",
    }


@pytest.mark.asyncio
async def test_room_reply_context_is_not_treated_as_thread_scope() -> None:
    """Room-level replies must not be accepted just because they have a resolved reply ID."""
    module = _load_tools_module()
    tools = module.ThreadGoalTools()
    querier = AsyncMock()
    putter = AsyncMock()

    with tool_runtime_context(
        _tool_context(
            thread_id=None,
            resolved_thread_id="$reply:localhost",
            room_state_querier=querier,
            room_state_putter=putter,
        ),
    ):
        result = json.loads(await tools.set_thread_goal("Ship it"))

    assert result == {
        "action": "set",
        "message": "An active thread is required to set a thread goal.",
        "status": "error",
        "tool": "thread_goal",
    }
    querier.assert_not_awaited()
    putter.assert_not_awaited()


@pytest.mark.asyncio
async def test_tool_returns_error_without_runtime_context() -> None:
    """The toolkit should fail cleanly when no tool runtime context is active."""
    module = _load_tools_module()
    tools = module.ThreadGoalTools()

    with tool_runtime_context(None):
        result = json.loads(await tools.get_thread_goal())

    assert result == {
        "action": "get",
        "message": "Thread goal tool context is unavailable in this runtime path.",
        "status": "error",
        "tool": "thread_goal",
    }


@pytest.mark.asyncio
async def test_tool_returns_error_when_state_write_fails() -> None:
    """A failed room-state write should surface a dedicated tool error."""
    module = _load_tools_module()
    tools = module.ThreadGoalTools()
    querier = AsyncMock(return_value=None)
    putter = AsyncMock(return_value=False)

    with tool_runtime_context(
        _tool_context(
            room_state_querier=querier,
            room_state_putter=putter,
        ),
    ):
        result = json.loads(await tools.set_thread_goal("Ship ISSUE-083 safely"))

    assert result == {
        "action": "set",
        "message": "Failed to write the thread goal state event.",
        "status": "error",
        "tool": "thread_goal",
    }
    querier.assert_awaited_once()
    putter.assert_awaited_once()
