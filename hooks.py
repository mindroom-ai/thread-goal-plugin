# ruff: noqa: INP001
"""Hook entrypoint for the MindRoom thread-goal plugin."""

from __future__ import annotations

import sys
from importlib import import_module, util
from pathlib import Path
from types import ModuleType

from mindroom.hooks import EnrichmentItem, MessageEnrichContext, hook

_PLUGIN_ROOT = Path(__file__).resolve().parent
_PACKAGE_NAME = f"{__name__}_modules"


def _ensure_package() -> None:
    """Register a synthetic package so sibling modules can be imported safely."""
    if _PACKAGE_NAME in sys.modules:
        return

    package_spec = util.spec_from_loader(_PACKAGE_NAME, loader=None, is_package=True)
    package_module = ModuleType(_PACKAGE_NAME)
    package_module.__file__ = str(_PLUGIN_ROOT / "__init__.py")
    package_module.__package__ = _PACKAGE_NAME
    package_module.__path__ = [str(_PLUGIN_ROOT)]
    if package_spec is not None:
        package_spec.submodule_search_locations = [str(_PLUGIN_ROOT)]
        package_module.__spec__ = package_spec
    sys.modules[_PACKAGE_NAME] = package_module


def _load_module(name: str) -> ModuleType:
    return import_module(f"{_PACKAGE_NAME}.{name}")


_ensure_package()

state = _load_module("state")
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
