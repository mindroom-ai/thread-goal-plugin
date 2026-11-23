# Thread Goal

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/mindroom-ai/thread-goal-plugin/actions/workflows/plugin-ci.yml/badge.svg)](https://github.com/mindroom-ai/thread-goal-plugin/actions/workflows/plugin-ci.yml)
[![Docs](https://img.shields.io/badge/docs-plugins-blue)](https://docs.mindroom.chat/plugins/)
[![Hooks](https://img.shields.io/badge/docs-hooks-blue)](https://docs.mindroom.chat/hooks/)
[![Tools](https://img.shields.io/badge/docs-tools-blue)](https://docs.mindroom.chat/tools/)

<picture>
  <source media="(prefers-reduced-motion: no-preference)" srcset="https://raw.githubusercontent.com/mindroom-ai/mindroom/main/assets/logo/logo-mark-animated.svg" />
  <img src="https://raw.githubusercontent.com/mindroom-ai/mindroom/main/assets/logo/logo-mark.svg" alt="MindRoom Logo" align="right" width="120" />
</picture>

A [MindRoom](https://github.com/mindroom-ai/mindroom) plugin that stores a short shared goal for each Matrix thread in room state and injects it into every prompt, so agents stay on objective across context compaction and restarts.

- **Survives compaction and restarts:** persists the thread's objective in Matrix room state (`com.mindroom.thread.goal`) keyed by the thread root event ID.
- **Injected on every turn:** a `message:enrich` hook adds a stable `Thread goal: ...` prompt line whenever the thread has a goal set.
- **Compact by design:** collapses whitespace and enforces a 160-character limit so the prompt stays concise.
- **Thread-scoped tools:** agents can set, read, and clear the current thread's goal (recording `set_by` and `set_at`); room-level calls are refused.

```text
Agent calls:    set_thread_goal("Ship v2 auth migration with zero downtime and passing integration tests")
Injected line:  Thread goal: Ship v2 auth migration with zero downtime and passing integration tests
```

## Quick start

```bash
mindroom plugins install thread-goal-plugin
```

```yaml
plugins:
  - path: plugins/thread-goal-plugin

agents:
  dev:
    tools: [thread_goal]
```

No plugin `settings:` are needed. Add `thread_goal` to `agents.<name>.tools` for any agent that should set, read, or clear goals; the enrichment hook injects an active goal on every thread turn automatically.

Update later with `mindroom plugins update thread-goal-plugin`.
Requires MindRoom plugin API 1.0 or later.

## Tools

Toolkit name: `thread_goal`.

| Tool | Purpose |
|------|---------|
| `set_thread_goal(goal)` | Set or update the current thread goal (normalized, up to 160 characters) |
| `get_thread_goal()` | Read the current thread goal and its `set_by` / `set_at` metadata |
| `clear_thread_goal()` | Clear the current thread goal |

All three tools are thread-scoped only and refuse room-level calls. Pairs cleanly with MindRoom's native `todo` tools: keep the overarching objective here while tracking individual steps in todos.

## Hooks

| Hook | Event | Priority | Timeout | Purpose |
|------|-------|----------|---------|---------|
| `thread-goal-context` | `message:enrich` | `40` | `1000 ms` | Inject the active thread goal as a stable prompt enrichment (`Thread goal: ...`) |

<details>
<summary><b>How it works</b></summary>

1. In an active thread, an agent calls `set_thread_goal(goal)`. The tool collapses whitespace, enforces the 160-character limit, and writes a Matrix room-state event if the normalized text changed.
2. On every turn inside a thread (`source_thread_id` present), `thread-goal-context` runs at `priority=40` (`timeout_ms=1000`) and reads the goal for `resolved_thread_id or source_thread_id`.
3. When a goal exists, the hook returns an `EnrichmentItem` with `key="thread_goal"`, `text="Thread goal: <goal>"`, and `cache_policy="stable"`, keeping the objective pinned across compaction without churning prompt caches.
4. Calling `clear_thread_goal()` clears the stored state so subsequent turns inject nothing.

</details>

<details>
<summary><b>Matrix room-state storage</b></summary>

- **Event type:** `com.mindroom.thread.goal`
- **State key:** the thread root event ID
- **Payload fields:**
  - `goal`: normalized non-empty string (at most 160 characters)
  - `set_by`: agent name (or requester ID if agent name is unavailable)
  - `set_at`: UTC ISO 8601 timestamp
- **Clearing:** writes an empty tombstone payload (`{}`) for that state key

</details>
