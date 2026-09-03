from fastapi import APIRouter, HTTPException
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError

from app.config import settings
from app.db.models import ActivityLog, Run, Supervisor
from app.db.session import db_session
from app.schemas import ActivityOut, EventIn, InstructionIn, RunCreate, RunOut, EVENT_TYPES
from app.temporal.client import get_temporal_client, workflow_id_for_run
from app.temporal.workflow import OrderSupervisorWorkflow

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _get_run(run_id: str) -> Run:
    with db_session() as s:
        run = s.get(Run, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run


def _mark_finished(run_id: str) -> None:
    """Reconcile DB status when Temporal reports the workflow already finished."""
    with db_session() as s:
        run = s.get(Run, run_id)
        if run and run.status not in ("completed", "terminated"):
            run.status = "completed"


async def _handle(run_id: str):
    client = await get_temporal_client()
    return client.get_workflow_handle(workflow_id_for_run(run_id))


async def _signal(run_id: str, signal, *args) -> None:
    """Send a signal; translate 'workflow already finished' into a clean 409."""
    handle = await _handle(run_id)
    try:
        await handle.signal(signal, *args)
    except RPCError as e:
        msg = str(e).lower()
        if "already completed" in msg or "not found" in msg:
            _mark_finished(run_id)
            raise HTTPException(409, "run already finished") from e
        raise HTTPException(502, f"temporal error: {e}") from e


@router.post("", response_model=RunOut)
async def create_run(body: RunCreate):
    with db_session() as s:
        sup = s.get(Supervisor, body.supervisor_id)
        if not sup:
            raise HTTPException(404, "supervisor not found")
        run = Run(
            supervisor_id=sup.id,
            order_id=body.order_id,
            order_context={"order_id": body.order_id, **body.order_context},
        )
        s.add(run)
        s.flush()
        run_out = RunOut.model_validate(run)
        cfg = {
            "run_id": run.id,
            "base_instruction": sup.base_instruction,
            "order_context": run.order_context,
            "available_actions": sup.available_actions,
            "default_wakeup_minutes": sup.default_wakeup_minutes,
            "model": sup.model,
            "wake_aggressiveness": sup.wake_aggressiveness,
            "max_age_hours": settings.max_workflow_age_hours,
        }

    client = await get_temporal_client()
    await client.start_workflow(
        OrderSupervisorWorkflow.run,
        cfg,
        id=workflow_id_for_run(run_out.id),
        task_queue=settings.temporal_task_queue,
    )
    return run_out


@router.get("", response_model=list[RunOut])
def list_runs():
    with db_session() as s:
        rows = s.query(Run).order_by(Run.created_at.desc()).all()
        return [RunOut.model_validate(r) for r in rows]


@router.get("/meta/event-types")
def event_types():
    return EVENT_TYPES


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: str):
    return RunOut.model_validate(_get_run(run_id))


@router.get("/{run_id}/activities", response_model=list[ActivityOut])
def get_activities(run_id: str):
    _get_run(run_id)
    with db_session() as s:
        rows = (
            s.query(ActivityLog)
            .filter(ActivityLog.run_id == run_id)
            .order_by(ActivityLog.id.asc())
            .all()
        )
        return [ActivityOut.model_validate(r) for r in rows]


@router.get("/{run_id}/state")
async def get_workflow_state(run_id: str):
    _get_run(run_id)
    handle = await _handle(run_id)
    try:
        desc = await handle.describe()
        state = {}
        if desc.status == WorkflowExecutionStatus.RUNNING:
            state = await handle.query(OrderSupervisorWorkflow.get_state)
        return {"workflow_status": desc.status.name, **state}
    except Exception as e:
        return {"workflow_status": "UNKNOWN", "error": str(e)}


@router.post("/{run_id}/events")
async def inject_event(run_id: str, body: EventIn):
    run = _get_run(run_id)
    if run.status in ("completed", "terminated"):
        raise HTTPException(409, "run already finished")
    await _signal(run_id, OrderSupervisorWorkflow.order_event, {"type": body.type, **body.payload})
    return {"ok": True}


@router.post("/{run_id}/instructions")
async def add_instruction(run_id: str, body: InstructionIn):
    run = _get_run(run_id)
    if run.status in ("completed", "terminated"):
        raise HTTPException(409, "run already finished")
    await _signal(run_id, OrderSupervisorWorkflow.add_instruction, body.instruction)
    with db_session() as s:
        s.add(ActivityLog(run_id=run_id, type="instruction", payload={"instruction": body.instruction}))
    return {"ok": True}


@router.post("/{run_id}/interrupt")
async def interrupt_run(run_id: str):
    _get_run(run_id)
    await _signal(run_id, OrderSupervisorWorkflow.pause)
    with db_session() as s:
        run = s.get(Run, run_id)
        run.status = "paused"
        s.add(ActivityLog(run_id=run_id, type="status_change", payload={"status": "paused"}))
    return {"ok": True}


@router.post("/{run_id}/resume")
async def resume_run(run_id: str):
    _get_run(run_id)
    await _signal(run_id, OrderSupervisorWorkflow.resume)
    with db_session() as s:
        run = s.get(Run, run_id)
        run.status = "running"
        s.add(ActivityLog(run_id=run_id, type="status_change", payload={"status": "resumed"}))
    return {"ok": True}


@router.post("/{run_id}/terminate")
async def terminate_run(run_id: str):
    _get_run(run_id)
    await _signal(run_id, OrderSupervisorWorkflow.terminate)
    return {"ok": True}
