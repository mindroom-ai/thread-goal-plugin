"""Tests for the thread-goal toolkit."""

from __future__ import annotations

import json
import sys
from importlib import util
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from mindroom.plugin_api import (
    HookBindings,
    MessageTarget,
    Toolkit,
    ToolRuntimeContext,
)
from mindroom.tool_system.output_files import ToolOutputFilePolicy
from mindroom.tool_system.registry import plugin_module_registrations
from mindroom.tool_system.runtime_context import tool_runtime_context
from mindroom.tool_system.toolkits import adapt_toolkit, configure_toolkit_functions

if TYPE_CHECKING:
    from types import ModuleType

PACKAGE_NAME = (
    f"mindroom_plugin_{Path(__file__).resolve().parents[1].name.replace('-', '_')}"
)


def _load_tools_module() -> ModuleType:
    """Load the plugin tools module under its synthetic package name."""
    tools_path = Path(__file__).resolve().parents[1] / "tools.py"
    module_name = f"{PACKAGE_NAME}.tools_test_{uuid4().hex}"
    sys.modules.pop(module_name, None)
    spec = util.spec_from_file_location(module_name, tools_path)
    assert spec is not None
    assert spec.loader is not None
    module = util.module_from_spec(spec)
    sys.modules[module_name] = module
    # A plugin module registers its tools while it loads, as the plugin loader runs it.
    with plugin_module_registrations(module_name):
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
        target=MessageTarget(
            room_id="!room:localhost",
            source_thread_id=thread_id,
            resolved_thread_id=resolved_thread_id,
            reply_to_event_id=None,
            session_id="session-1",
        ),
        requester_id="@user:localhost",
        client=AsyncMock(),
        config=SimpleNamespace(),
        runtime_paths=SimpleNamespace(),
        plugins=SimpleNamespace(),
        conversation_reader=AsyncMock(),
        relations=AsyncMock(),
        hooks=HookBindings(
            room_state_querier=room_state_querier,
            room_state_putter=room_state_putter,
        ),
    )


def test_thread_goal_schema_and_metadata(tmp_path: Path) -> None:
    """The toolkit should expose one unified action-based tool without reserved params."""
    module = _load_tools_module()

    tools = module.ThreadGoalTools()
    assert isinstance(tools, Toolkit)
    assert list(tools.functions) == ["thread_goal"]
    assert tools.offer_background_after is False
    assert tools.offer_output_path is False
    assert "thread_goal(action=" in (tools.instructions or "")

    configure_toolkit_functions(
        tools,
        output_files=ToolOutputFilePolicy(workspace_root=tmp_path),
    )
    adapted = adapt_toolkit(tools)
    assert len(adapted.functions) == 1
    function = adapted.functions[0]
    assert function.name == "thread_goal"
    assert function.offer_background_after is False
    assert function.offer_output_path is False

    schema = function.parameters
    assert schema["required"] == ["action"]
    assert schema["properties"]["action"]["type"] == "string"
    assert schema["properties"]["action"]["enum"] == ["get", "set", "clear"]
    assert schema["properties"]["action"]["description"]
    assert schema["properties"]["goal"]["type"] == "string"
    assert schema["properties"]["goal"]["description"]
    assert "background_after" not in schema["properties"]
    assert "mindroom_output_path" not in schema["properties"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "goal", "expected_action", "expected_message"),
    [
        ("get", "Ship it", "get", "Parameter 'goal' cannot be used with action='get'."),
        ("get", "", "get", "Parameter 'goal' cannot be used with action='get'."),
        (
            "clear",
            "Ship it",
            "clear",
            "Parameter 'goal' cannot be used with action='clear'.",
        ),
        ("clear", "", "clear", "Parameter 'goal' cannot be used with action='clear'."),
        ("set", None, "set", "Parameter 'goal' is required for action='set'."),
        ("set", " \n\t ", "set", "goal must be a non-empty string."),
        ("set", "x" * 161, "set", "goal must be 160 characters or fewer."),
        (
            "delete",
            None,
            None,
            "Unsupported thread_goal action 'delete'. Expected one of: get, set, clear.",
        ),
    ],
)
async def test_per_action_argument_validation(
    action: Any,
    goal: str | None,
    expected_action: str | None,
    expected_message: str,
) -> None:
    """Invalid actions and mismatched per-action arguments should fail cleanly."""
    module = _load_tools_module()
    tools = module.ThreadGoalTools()
    querier = AsyncMock()
    putter = AsyncMock()

    with tool_runtime_context(
        _tool_context(room_state_querier=querier, room_state_putter=putter),
    ):
        result = json.loads(await tools.thread_goal(action=action, goal=goal))

    expected: dict[str, object] = {
        "message": expected_message,
        "status": "error",
        "tool": "thread_goal",
    }
    if expected_action is not None:
        expected["action"] = expected_action
    assert result == expected
    querier.assert_not_awaited()
    putter.assert_not_awaited()


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
        set_result = json.loads(
            await tools.thread_goal(action="set", goal="  Ship\n ISSUE-083 safely  "),
        )
        repeat_result = json.loads(
            await tools.thread_goal(action="set", goal="Ship ISSUE-083 safely"),
        )
        get_result = json.loads(await tools.thread_goal(action="get"))
        clear_result = json.loads(await tools.thread_goal(action="clear"))
        repeat_clear_result = json.loads(await tools.thread_goal(action="clear"))
        empty_result = json.loads(await tools.thread_goal(action="get"))

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
    assert repeat_clear_result["changed"] is False
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
        result = json.loads(await tools.thread_goal(action="set", goal="Ship it"))

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
        result = json.loads(await tools.thread_goal(action="set", goal="Ship it"))

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
        result = json.loads(await tools.thread_goal(action="get"))

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
        result = json.loads(
            await tools.thread_goal(action="set", goal="Ship ISSUE-083 safely"),
        )

    assert result == {
        "action": "set",
        "message": "Failed to write the thread goal state event.",
        "status": "error",
        "tool": "thread_goal",
    }
    querier.assert_awaited_once()
    putter.assert_awaited_once()
