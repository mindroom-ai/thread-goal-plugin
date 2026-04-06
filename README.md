# Thread Goal

MindRoom plugin that gives each conversation thread a persistent goal that survives context compaction.

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

## Design

- **Storage:** Matrix state event (type `com.mindroom.thread.goal`, state key = thread event ID)
- **Injection:** `message:enrich` hook at priority 40 (before workloop at 50)
- **Overhead:** ~44–70 tokens per turn
- **Conflict resolution:** Last writer wins
- **Clearing:** Writes a tombstone (`{}`) to the state event

## Complements workloop

**thread-goal** = *what* the agent is trying to achieve (the destination)
**workloop** = *how* it gets there (the steps)

## Setup

1. Copy to `~/.mindroom-chat/plugins/thread-goal`
2. Add to `config.yaml`:
   ```yaml
   plugins:
     - path: plugins/thread-goal
   ```
3. Add `thread_goal` to agent's tools list
4. Restart MindRoom