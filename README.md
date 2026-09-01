# Order Supervisor

A POC for a long-running AI supervisor that oversees a single e-commerce order from creation to completion, built on Temporal.

One Temporal workflow runs per order. Events are delivered as signals; a lightweight classifier decides whether each event should wake the main agent. The agent reasons with Gemini (function calling), executes business actions, maintains a compact rolling memory, chooses its own sleep duration, and the workflow produces a final summary with learnings when it completes.

## Stack

- **Frontend:** Next.js (App Router) + Tailwind CSS
- **Backend:** Python + FastAPI
- **Orchestration:** Temporal (Python SDK, `temporalio`)
- **Persistence:** PostgreSQL
- **LLM:** Google Gemini (function calling), with a deterministic mock-agent fallback when no API key is set

## Setup

Prerequisites: Docker, Python 3.12+, Node 20+.

### 1. Infrastructure (Temporal + Postgres)

```bash
docker compose up -d
```

- Temporal gRPC: `localhost:7233` · Temporal Web UI: http://localhost:8233
- Postgres: `localhost:5432` (app database `orders`)

### 2. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # add GEMINI_API_KEY to enable the LLM agent

# terminal 1 — Temporal worker
.venv/bin/python -m app.temporal.worker

# terminal 2 — API
.venv/bin/uvicorn app.main:app --port 8000
```

Without `GEMINI_API_KEY`, the system still works end-to-end using a rule-based mock agent.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:3000
```

## Using it

1. Open http://localhost:3000/supervisors to review or create a supervisor template (name, base instruction, allowed actions, default wake-up, wake aggressiveness). A default template is seeded automatically.
2. On the home page, start a run for an order.
3. On the run page:
   - **Inject events** (`payment_failed`, `shipment_delayed`, `delivered`, …) — signals into the workflow.
   - **Add instructions** to the live run (e.g. "Prioritize speed over cost") — becomes part of run context and wakes the agent.
   - **Pause / Resume / Terminate** the run.
   - Watch the **timeline** (events, wake/sleep decisions, actions, reasoning) and the **memory summary** update live.
4. Send `delivered` (or terminate) to finish the run and see the **final summary, important actions, key learnings, and recommendations**.

Events can also be injected via API:

```bash
curl -X POST localhost:8000/api/runs/<run_id>/events \
  -H 'content-type: application/json' -d '{"type": "shipment_delayed"}'
```

## API

| Method | Path | Description |
|---|---|---|
| POST | `/api/supervisors` | Create supervisor template |
| GET | `/api/supervisors` / `/{id}` | List / get templates |
| POST | `/api/runs` | Create run + start workflow |
| GET | `/api/runs` / `/{run_id}` | List / get runs |
| GET | `/api/runs/{run_id}/activities` | Timeline & activity log |
| GET | `/api/runs/{run_id}/state` | Live workflow state (Temporal query) |
| POST | `/api/runs/{run_id}/events` | Inject event (signal) |
| POST | `/api/runs/{run_id}/instructions` | Add run-specific instruction (signal) |
| POST | `/api/runs/{run_id}/interrupt` | Pause the run |
| POST | `/api/runs/{run_id}/resume` | Resume the run |
| POST | `/api/runs/{run_id}/terminate` | Request termination (workflow finalizes gracefully) |

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design note.
