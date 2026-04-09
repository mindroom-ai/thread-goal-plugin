# Thread Goal

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-plugins-blue)](https://docs.mindroom.chat/plugins/)
[![Hooks](https://img.shields.io/badge/docs-hooks-blue)](https://docs.mindroom.chat/hooks/)

<img src="https://media.githubusercontent.com/media/mindroom-ai/mindroom/refs/heads/main/frontend/public/logo.png" alt="MindRoom Logo" align="right" width="120" />

Persistent thread goals for [MindRoom](https://github.com/mindroom-ai/mindroom) agents that survive context compaction.

When agents work on long tasks, conversation history gets compacted to save tokens. Important context can disappear. Thread Goal stores a short shared goal string in Matrix room state and re-injects it into every prompt, so the agent keeps the same objective no matter how many turns, restarts, or compaction passes happen afterward.

## Features

- Stores a short thread goal in Matrix room state under `com.mindroom.thread.goal`
- Re-injects the goal into every prompt via `message:enrich`
- Persists across compaction, restarts, and long-running threads
- Exposes dedicated thread-scoped tools to set, read, and clear the goal
- Records `set_by` and `set_at` metadata alongside the goal text
- Enforces a normalized 160-character limit so the stored goal stays compact

## How It Works

1. An agent calls `set_thread_goal(goal)` in the active thread.
2. The plugin stores the normalized goal as a Matrix state event keyed by the thread root event ID.
3. On each turn, the `thread-goal-context` hook reads the current goal from room state.
4. If a goal exists, the hook injects a stable `Thread goal: ...` enrichment item into the prompt.

## Agent Tools

| Tool | Purpose |
|------|---------|
| `set_thread_goal(goal)` | Set or update the current thread goal. Maximum length: 160 characters |
| `get_thread_goal()` | Read the current thread goal and its metadata |
| `clear_thread_goal()` | Clear the current thread goal |

All three tools are thread-scoped only. They refuse to operate at room level.

## Hooks

| Hook | Event | Purpose |
|------|-------|---------|
| `thread-goal-context` | `message:enrich` | Inject the current thread goal into the prompt before workloop runs |

## Storage

- Event type: `com.mindroom.thread.goal`
- State key: the thread root event ID
- Payload fields: `goal`, `set_by`, `set_at`
- Clearing the goal writes an empty payload for that state key

## Setup

1. Copy this plugin to `~/.mindroom/plugins/thread-goal`.
2. Add the plugin to `config.yaml`:
   ```yaml
   plugins:
     - path: plugins/thread-goal
   ```
3. Add `thread_goal` to the agent's tools list.
4. Restart MindRoom.

Complements [workloop](https://github.com/mindroom-ai/workloop-plugin): thread-goal is what the agent is trying to achieve, and workloop is how it gets there.
