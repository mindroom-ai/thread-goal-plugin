# Thread Goal

[![License](https://img.shields.io/github/license/mindroom-ai/thread-goal-plugin)](https://github.com/mindroom-ai/thread-goal-plugin/blob/main/LICENSE)
[![Docs](https://img.shields.io/badge/docs-plugins-blue)](https://docs.mindroom.chat/plugins/)
[![Hooks](https://img.shields.io/badge/docs-hooks-blue)](https://docs.mindroom.chat/hooks/)

<img src="https://raw.githubusercontent.com/mindroom-ai/mindroom/main/frontend/public/logo.png" alt="MindRoom Logo" align="right" width="120" />

Persistent thread goals for [MindRoom](https://github.com/mindroom-ai/mindroom) agents that survive context compaction.

When agents work on long tasks, conversation history gets compacted to save tokens. Important context can be lost. Thread Goal stores a short goal string (≤160 chars) as a Matrix state event and re-injects it into every prompt, so the agent always knows *what* it's working toward — no matter how many turns have passed.

## How it works

1. Agent (or user) sets a goal via the `set_thread_goal` tool
2. Goal is stored as a Matrix room state event (`com.mindroom.thread.goal`)
3. Every turn, the `message:enrich` hook reads the goal from Matrix state and injects it into the prompt
4. Goal persists indefinitely — immune to compaction, restarts, and context window limits

## Agent tools

| Tool | Purpose |
|------|---------|
| `set_thread_goal(goal)` | Set or update the thread's goal (≤160 chars) |
| `get_thread_goal()` | Read the current goal |
| `clear_thread_goal()` | Remove the goal |

All tools are thread-scoped only — they refuse to operate at room level.

## Hooks

| Hook | Event | Purpose |
|------|-------|---------|
| `inject_thread_goal` | `message:enrich` | Inject goal into prompt (priority 40, before workloop) |

## Setup

1. Copy to `~/.mindroom/plugins/thread-goal`
2. Add to `config.yaml`:
   ```yaml
   plugins:
     - path: plugins/thread-goal
   ```
3. Add `thread_goal` to agent's tools list
4. Restart MindRoom

Complements [workloop](https://github.com/mindroom-ai/workloop-plugin): thread-goal is *what* the agent is trying to achieve, workloop is *how* it gets there.