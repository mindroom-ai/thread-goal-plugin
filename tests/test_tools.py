# ruff: noqa: INP001
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
from mindroom.approval.tool_approval import scheduled_call_offers_any_arguments
from mindroom.config.legacy_fields import retired_consolidated_approval_error
from mindroom.config.main import Config, ConfigRuntimeValidationError
from mindroom.constants import resolve_runtime_paths
from mindroom.plugin_api import HookBindings, MessageTarget, Toolkit, ToolRuntimeContext
from mindroom.tool_approval_grants import grant_operation
from mindroom.tool_jobs import execution as job_execution
from mindroom.tool_jobs.resources import ExecutionResources, bind_execution_resources
from mindroom.tool_system.output_files import ToolOutputFilePolicy
from mindroom.tool_system.registry import ToolRegistry, plugin_module_registrations
from mindroom.tool_system.runtime_context import tool_runtime_context
from mindroom.tool_system.toolkits import adapt_toolkit, configure_toolkit_functions

try:
    from mindroom.config.runtime import validate_config_with_runtime
except ImportError:
    validate_config_with_runtime = Config.validate_with_runtime

if TYPE_CHECKING:
    from types import ModuleType

PACKAGE_NAME = f"mindroom_plugin_{Path(__file__).resolve().parents[1].name.replace('-', '_')}"


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
    with plugin_module_registrations(module_name) as registrations:
        spec.loader.exec_module(module)
    module.registrations = registrations
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
        hooks=HookBindings(room_state_querier=room_state_querier, room_state_putter=room_state_putter),
    )


def test_thread_goal_schema_and_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    adapted = adapt_toolkit(tools, key="thread_goal")
    (function,) = adapted.functions
    assert function.name == "thread_goal"
    assert function.offer_background_after is False
    assert function.offer_output_path is False

    actor = job_execution.JobActor(
        name="code",
        team=False,
        depth=0,
        tools=job_execution.assembled_job_tools([(tools, function)], {}),
    )
    context = _tool_context()
    monkeypatch.setattr(job_execution, "get_background_runtime", lambda _runtime_paths: object())
    with tool_runtime_context(context), bind_execution_resources(ExecutionResources()):
        assert job_execution.wait_mode(actor.tools["thread_goal"], depth=0, context=context) == "managed"
        (definition,) = job_execution.offered_definitions(actor, [function.definition()])

    schema = definition.parameters
    assert schema["required"] == ["action"]
    assert set(schema["properties"]) == {"action", "goal"}
    assert schema["properties"]["action"]["type"] == "string"
    assert schema["properties"]["action"]["enum"] == ["get", "set", "clear"]
    assert schema["properties"]["action"]["description"]
    assert schema["properties"]["goal"]["type"] == "string"
    assert schema["properties"]["goal"]["description"]
    assert "background_after" not in schema["properties"]
    assert "mindroom_output_path" not in schema["properties"]


def test_action_scoped_grants_separate_operations_per_action() -> None:
    """Timed approval grants bind to (thread_goal, action) so approving get leaves set/clear gated."""
    module = _load_tools_module()
    registration = module.registrations["thread_goal"]
    assert registration.action_scoped_grants == ("thread_goal",)

    registry = ToolRegistry(entries=module.registrations)
    config = Config(tool_approval={"scheduled_any_arguments": True})

    get_op = grant_operation(config, "thread_goal", {"action": "get"}, tools=registry)
    set_op = grant_operation(config, "thread_goal", {"action": "set"}, tools=registry)
    clear_op = grant_operation(config, "thread_goal", {"action": "clear"}, tools=registry)

    assert get_op is not None
    assert set_op is not None
    assert clear_op is not None
    assert get_op == grant_operation(config, "thread_goal", {"action": " get "}, tools=registry)
    assert len({get_op.key, set_op.key, clear_op.key}) == 3
    for bad_args in ({}, {"action": ""}, {"action": "   "}, {"action": 123}):
        assert grant_operation(config, "thread_goal", bad_args, tools=registry) is None
    assert not scheduled_call_offers_any_arguments(
        config,
        "thread_goal",
        {"action": "get"},
        requester_id="@user:localhost",
        approver_id="@user:localhost",
        authored_confirmation=False,
        tools=registry,
    )


def test_retired_functions_fail_closed_in_config_validation(tmp_path: Path) -> None:
    """Legacy approval rules for retired thread-goal functions fail closed until thread_goal is explicitly ruled."""
    plugin_root = Path(__file__).resolve().parents[1]
    module = _load_tools_module()
    registration = module.registrations["thread_goal"]
    assert registration.retired_functions == {
        "set_thread_goal": "thread_goal",
        "get_thread_goal": "thread_goal",
        "clear_thread_goal": "thread_goal",
    }

    config_path = tmp_path / "config.yaml"
    config_path.write_text("router:\n  model: default\n", encoding="utf-8")
    runtime_paths = resolve_runtime_paths(
        config_path=config_path,
        storage_path=tmp_path / "mindroom_data",
        process_env={
            "MATRIX_HOMESERVER": "http://localhost:8008",
            "MINDROOM_NAMESPACE": "",
        },
    )

    for legacy_name in ("set_thread_goal", "get_thread_goal", "clear_thread_goal"):
        approval_config = Config(
            tool_approval={
                "default": "auto_approve",
                "rules": [{"match": legacy_name, "action": "require_approval"}],
            },
        ).tool_approval
        error = retired_consolidated_approval_error(
            "thread_goal",
            approval_config.rules,
            approval_config.default,
            approval_config.timeout_days,
            renames=registration.retired_functions,
        )
        assert error is not None
        assert legacy_name in error
        assert "thread_goal" in error

        stale_data = {
            "models": {"default": {"provider": "openai", "id": "x"}},
            "plugins": [{"path": str(plugin_root)}],
            "agents": {
                "code": {"display_name": "Code", "tools": ["thread_goal"], "include_default_tools": False},
            },
            "tool_approval": {
                "default": "auto_approve",
                "rules": [{"match": legacy_name, "action": "require_approval"}],
            },
        }
        with pytest.raises(ConfigRuntimeValidationError, match="thread_goal"):
            validate_config_with_runtime(stale_data, runtime_paths)

    migrated_data = {
        "models": {"default": {"provider": "openai", "id": "x"}},
        "plugins": [{"path": str(plugin_root)}],
        "agents": {
            "code": {"display_name": "Code", "tools": ["thread_goal"], "include_default_tools": False},
        },
        "tool_approval": {
            "default": "auto_approve",
            "rules": [
                {"match": "clear_thread_goal", "action": "require_approval"},
                {"match": "thread_goal", "action": "require_approval"},
            ],
        },
    }
    loaded = validate_config_with_runtime(migrated_data, runtime_paths)
    assert [rule.match for rule in loaded.tool_approval.rules] == ["clear_thread_goal", "thread_goal"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "goal", "expected_action", "expected_message"),
    [
        ("get", "Ship it", "get", "Parameter 'goal' cannot be used with action='get'."),
        ("get", "", "get", "Parameter 'goal' cannot be used with action='get'."),
        ("get", 123, "get", "Parameter 'goal' cannot be used with action='get'."),
        ("clear", "Ship it", "clear", "Parameter 'goal' cannot be used with action='clear'."),
        ("clear", "", "clear", "Parameter 'goal' cannot be used with action='clear'."),
        ("set", None, "set", "Parameter 'goal' is required for action='set'."),
        ("set", 123, "set", "goal must be a string."),
        ("set", " \n\t ", "set", "goal must be a non-empty string."),
        ("set", "x" * 161, "set", "goal must be 160 characters or fewer."),
        ("delete", None, None, "Unsupported thread_goal action 'delete'. Expected one of: get, set, clear."),
        (123, None, None, "Unsupported thread_goal action 123. Expected one of: get, set, clear."),
        (None, None, None, "Unsupported thread_goal action None. Expected one of: get, set, clear."),
    ],
)
async def test_per_action_argument_validation(
    action: Any,
    goal: Any,
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
        set_result = json.loads(await tools.thread_goal(action="set", goal="  Ship\n ISSUE-083 safely  "))
        repeat_result = json.loads(await tools.thread_goal(action="set", goal="Ship ISSUE-083 safely"))
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
        result = json.loads(await tools.thread_goal(action="set", goal="Ship ISSUE-083 safely"))

    assert result == {
        "action": "set",
        "message": "Failed to write the thread goal state event.",
        "status": "error",
        "tool": "thread_goal",
    }
    querier.assert_awaited_once()
    putter.assert_awaited_once()
