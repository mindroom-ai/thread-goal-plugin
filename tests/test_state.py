# ruff: noqa: INP001
"""Tests for thread-goal state helpers."""

from __future__ import annotations

from importlib import util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

PACKAGE_NAME = f"mindroom_plugin_{Path(__file__).resolve().parents[1].name.replace('-', '_')}"


def _load_state_module() -> ModuleType:
    """Load the plugin state module under its synthetic package name."""
    state_path = Path(__file__).resolve().parents[1] / "state.py"
    module_name = f"{PACKAGE_NAME}.state"
    sys.modules.pop(module_name, None)
    spec = util.spec_from_file_location(module_name, state_path)
    assert spec is not None
    assert spec.loader is not None
    module = util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_normalize_goal_text_rejects_empty_and_too_long_values() -> None:
    """Normalization should collapse whitespace and reject invalid values."""
    module = _load_state_module()

    assert module.normalize_goal_text("  Ship\n ISSUE-083   safely  ") == "Ship ISSUE-083 safely"

    with pytest.raises(TypeError, match="string"):
        module.normalize_goal_text(123)

    with pytest.raises(ValueError, match="non-empty"):
        module.normalize_goal_text(" \n\t ")

    with pytest.raises(ValueError, match="160"):
        module.normalize_goal_text("x" * 161)


def test_goal_state_key_normalizes_and_rejects_blank_values() -> None:
    """State keys should be stripped, but never accept blank thread IDs."""
    module = _load_state_module()

    assert module.goal_state_key("  $thread-root  ") == "$thread-root"

    with pytest.raises(ValueError, match="non-empty"):
        module.goal_state_key(" \n\t ")


def test_parse_and_serialize_thread_goal_round_trip() -> None:
    """Valid goal payloads should round-trip through serialization helpers."""
    module = _load_state_module()

    record = module.ThreadGoalRecord(
        goal="Ship ISSUE-083 safely",
        set_by="code",
        set_at="2026-04-03T10:00:00+00:00",
    )

    content = module.serialize_thread_goal_content(record)
    assert content == {
        "goal": "Ship ISSUE-083 safely",
        "set_by": "code",
        "set_at": "2026-04-03T10:00:00+00:00",
    }
    assert module.parse_thread_goal_content(content) == record


def test_parse_tombstone_or_invalid_content_returns_none() -> None:
    """Tombstones and malformed payloads should parse as missing goals."""
    module = _load_state_module()

    assert module.parse_thread_goal_content({}) is None
    assert module.parse_thread_goal_content({"goal": "x"}) is None
    assert module.parse_thread_goal_content("not-a-dict") is None
