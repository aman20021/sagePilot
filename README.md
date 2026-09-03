# Order Supervisor

A POC for a long-running AI supervisor that oversees a single e-commerce order from creation to completion, built on Temporal.

One Temporal workflow runs per order. Events are delivered as signals; a lightweight classifier decides whether each event should wake the main agent. The agent reasons with Gemini (function calling), executes business actions, maintains a compact rolling memory, chooses its own sleep duration, and the workflow produces a final summary with learnings when it completes.

## Stack

- **Frontend:** Next.js (App Router) + Tailwind CSS
- **Backend:** Python + FastAPI
- **Orchestration:** Temporal (Python SDK, `temporalio`)
- **Persistence:** PostgreSQL
- **LLM:** Google Gemini (function calling), with a deterministic mock-agent fallback when no API key is set

## Run it step by step

Prerequisites: **Docker Desktop** (running), **Python 3.12+**, **Node 20+**.
You'll need **4 terminals** (or run steps 3–5 in the background).

### Step 1 — Start infrastructure (Temporal + Postgres)

```bash
cd sagepilot
docker compose up -d
docker compose ps          # wait until all 3 containers are Up/healthy
```

- Temporal gRPC: `localhost:7233` · Temporal Web UI: http://localhost:8233
- Postgres: `localhost:5432` (app database `orders`, user/password `temporal`/`temporal`)

### Step 2 — Set up the backend (one-time)

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Edit `backend/.env` and set your Gemini key (optional — without it a rule-based mock agent is used, everything still works):

```
GEMINI_API_KEY=your-key-here
```

### Step 3 — Start the Temporal worker (terminal 1)

```bash
cd backend
.venv/bin/python -m app.temporal.worker
```

Expect: `Worker started on task queue order-supervisor`. This process runs the workflow and the AI agent — keep it running.

### Step 4 — Start the API (terminal 2)

```bash
cd backend
.venv/bin/uvicorn app.main:app --port 8000
```

Verify:

```bash
curl localhost:8000/api/health        # → {"ok":true}
curl localhost:8000/api/supervisors   # → seeded default template
```

### Step 5 — Start the frontend (terminal 3)

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000**.

### Step 6 — Try the full lifecycle (terminal 4 or the UI)

In the UI: start a run, then inject events from the run page. Or via curl:

```bash
# get the seeded supervisor id
SUP=$(curl -s localhost:8000/api/supervisors | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")

# start a run (starts one Temporal workflow for the order)
RUN=$(curl -s -X POST localhost:8000/api/runs -H 'content-type: application/json' \
  -d "{\"supervisor_id\":\"$SUP\",\"order_id\":\"ORD-1001\",\"order_context\":{\"item\":\"Espresso machine\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "run: http://localhost:3000/runs/$RUN"

# routine event → classifier logs it, agent stays asleep
curl -X POST localhost:8000/api/runs/$RUN/events -H 'content-type: application/json' -d '{"type":"payment_confirmed"}'

# critical event → agent wakes, messages logistics + customer
curl -X POST localhost:8000/api/runs/$RUN/events -H 'content-type: application/json' -d '{"type":"shipment_delayed","payload":{"delay_days":3}}'

# add a live instruction → wakes the agent with new context
curl -X POST localhost:8000/api/runs/$RUN/instructions -H 'content-type: application/json' -d '{"instruction":"Prioritize speed over cost."}'

# terminal event → agent's final review, then workflow completes with a final report
curl -X POST localhost:8000/api/runs/$RUN/events -H 'content-type: application/json' -d '{"type":"delivered"}'
```

Watch the timeline update live on the run page, and the workflow itself at http://localhost:8233.

### Stopping everything

```bash
# Ctrl+C the worker, API, and frontend, then:
docker compose down        # add -v to also wipe the databases
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
