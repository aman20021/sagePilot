# Architecture Note

## Overview

```
Next.js UI ──HTTP──▶ FastAPI ──start/signal/query──▶ Temporal Server
                        │                                 │
                        ▼                                 ▼
                    PostgreSQL ◀──activities──── Temporal Worker
                    (read model)                 (workflow + agent runtime)
```

- **Temporal is the source of truth for control flow** — wake/sleep, signal handling, lifecycle rules all live in the workflow.
- **Postgres is the read model** — supervisors, runs, and a single `activity_log` table that stores events, wake/sleep decisions, agent actions, instructions, reasoning, and final outputs. The UI only reads from Postgres (plus an optional live Temporal query endpoint).

## Workflow (`OrderSupervisorWorkflow`)

One workflow per order (`order-supervisor-{run_id}`). Loop shape:

1. **Trigger 1 — start:** run the agent once for an initial review.
2. Sleep via `workflow.wait_condition(pending signals, timeout = agent-chosen sleep duration)`.
3. **Trigger 2 — signal:** `order_event` signals are drained and each is passed through a lightweight rule-based classifier (critical events wake, routine events are just logged, unknown events escalate by waking; agent-provided `wake_guidance` and template `wake_aggressiveness` influence the decision). `add_instruction` signals always wake the agent.
4. **Trigger 3 — scheduled wake-up:** the `wait_condition` timeout fires and the agent runs a periodic review.
5. `pause`/`resume` signals gate the loop; the workflow parks in a paused state without consuming agent turns.

**Completion is workflow-owned**, never agent-owned: a terminal event (`delivered`), a manual terminate signal from the UI, or a configured max workflow age. On completion the workflow runs a final-summary activity (summary, important actions, key learnings, recommendations), persists it, and returns.

## Agent runtime

Runs inside a Temporal activity. It builds a prompt from: base instruction, order context, wake reason, new events, run-specific instructions, compact memory summary, and recent timeline. Gemini function calling drives a small tool loop:

- **5 business actions** — `message_fulfillment_team`, `message_payments_team`, `message_logistics_team`, `message_customer`, `create_internal_note`. Each call writes an `action` row to `activity_log` (mocked side effects, per spec).
- **Runtime tools** — `update_memory(summary)` refreshes the rolling compact memory (context compaction: the agent re-summarizes rather than accumulating history), and `sleep(minutes, reason, wake_guidance)` ends the turn, choosing the next scheduled wake-up and optionally refining classifier guidance for future events.

If `GEMINI_API_KEY` is not set (or the LLM fails), a deterministic mock agent produces sensible rule-based behavior so the whole system remains demoable.

## Memory & timeline

- `activity_log` is the full timeline (single-table design per spec).
- The compact memory summary lives in workflow state (survives via Temporal event history) and is mirrored to `runs.memory_summary` for the UI.
- The agent only ever sees the compact summary + the last ~40 timeline rows, keeping context bounded.

## Trade-offs / scope choices

- Classifier is rule-based rather than an LLM call: cheap, deterministic, and demonstrable; the agent can still steer it via `wake_guidance`.
- `continue_as_new` is not implemented (histories stay small in a POC); the natural insertion point is the top of the workflow loop.
- No auth/multi-tenancy per scope boundaries.
