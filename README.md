# thread-goal-plugin

A MindRoom plugin for persistent thread goals that survive compaction.

## Problem

When AI models compact long conversations, earlier instructions and injected context may get summarized away. Agents lose track of what the thread is actually trying to achieve.

## Solution

A short goal string (≤160 chars) stored as a Matrix state event (`com.mindroom.thread.goal`) and re-injected into every prompt via the `message:enrich` hook. Because it's read fresh from Matrix state each turn — not baked into conversation history — it's immune to compaction.

## Features

- **Persistent goals** — stored as Matrix room state, thread-scoped
- **Compaction-proof** — enrichment re-injected fresh each turn, never summarized away
- **Lightweight** — ~44-70 tokens per turn overhead
- **3 tools** — `set_thread_goal`, `get_thread_goal`, `clear_thread_goal`
- **`message:enrich` hook** — priority 40 (before workloop at 50), `cache_policy="stable"`
- **Thread-scoped only** — refuses to operate at room level
- **Last-writer-wins** — simple semantics, tombstone `{}` on clear

## Complements Workloop

| Plugin | Purpose |
|--------|---------|
| **thread-goal** | *What* we're achieving (the destination) |
| **workloop** | *How* to get there (the steps) |

## Installation

1. Copy this directory to `~/.mindroom/plugins/thread-goal/`
2. Add to `config.yaml`:

```yaml
plugins:
  - path: plugins/thread-goal
```

3. Add `thread_goal` to your agent's tools list:

```yaml
agents:
  your_agent:
    tools: [thread_goal]
```

## Files

| File | Purpose |
|------|---------|
| `mindroom.plugin.json` | Plugin manifest |
| `state.py` | `ThreadGoalRecord` dataclass, parse/serialize helpers, `MAX_GOAL_CHARS=160` |
| `tools.py` | `set_thread_goal`, `get_thread_goal`, `clear_thread_goal` tool factory |
| `hooks.py` | `message:enrich` hook — injects goal into every prompt |
| `tests/` | 13 tests covering state, tools, hooks, and edge cases |

## State Event

```
Type: com.mindroom.thread.goal
State key: <thread_event_id>
Content: {"goal": "...", "set_by": "@user:server", "set_at": "2026-04-03T..."}
Tombstone (cleared): {}
```

## License

MIT — see [LICENSE](LICENSE).