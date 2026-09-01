"""Temporal activities: DB persistence, classifier, and agent inference."""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from temporalio import activity

from app.agent.classifier import classify_event as _classify
from app.agent.runtime import generate_final_summary_llm, run_agent_llm
from app.db.models import ActivityLog, Run
from app.db.session import db_session


def _log(run_id: str, type_: str, payload: dict) -> None:
    with db_session() as s:
        s.add(ActivityLog(run_id=run_id, type=type_, payload=payload))


@activity.defn
async def record_activity(run_id: str, type_: str, payload: dict) -> None:
    _log(run_id, type_, payload)


@activity.defn
async def update_run_state(
    run_id: str,
    status: Optional[str] = None,
    memory_summary: Optional[str] = None,
    next_wakeup_minutes: Optional[float] = None,
    final_output: Optional[dict] = None,
) -> None:
    with db_session() as s:
        run = s.get(Run, run_id)
        if not run:
            return
        if status is not None:
            run.status = status
        if memory_summary is not None:
            run.memory_summary = memory_summary
        if next_wakeup_minutes is not None:
            run.next_wakeup_at = datetime.now(timezone.utc) + timedelta(minutes=next_wakeup_minutes)
        if final_output is not None:
            run.final_output = final_output


@activity.defn
async def classify_event_activity(
    event_type: str, aggressiveness: str, wake_guidance: str
) -> dict:
    return _classify(event_type, aggressiveness, wake_guidance)


def _fetch_timeline(run_id: str, limit: int = 40) -> list[dict]:
    with db_session() as s:
        rows = (
            s.query(ActivityLog)
            .filter(ActivityLog.run_id == run_id)
            .order_by(ActivityLog.id.desc())
            .limit(limit)
            .all()
        )
    return [
        {"type": r.type, "payload": r.payload, "at": r.created_at.isoformat()}
        for r in reversed(rows)
    ]


@activity.defn
async def run_agent_activity(ctx: dict[str, Any]) -> dict[str, Any]:
    run_id = ctx["run_id"]
    ctx["timeline"] = _fetch_timeline(run_id)

    def record_action(name: str, args: dict) -> None:
        _log(run_id, "action", {"action": name, "args": args})

    result = run_agent_llm(ctx, record_action)
    _log(
        run_id,
        "reasoning",
        {
            "wake_reason": ctx["wake_reason"],
            "reasoning": result["reasoning"],
            "actions_taken": len(result["actions"]),
        },
    )
    _log(
        run_id,
        "sleep_decision",
        {
            "sleep_minutes": result["sleep_minutes"],
            "reason": result["sleep_reason"],
            "wake_guidance": result["wake_guidance"],
        },
    )
    return result


@activity.defn
async def generate_final_summary_activity(ctx: dict[str, Any]) -> dict[str, Any]:
    run_id = ctx["run_id"]
    ctx["timeline"] = _fetch_timeline(run_id, limit=200)
    output = generate_final_summary_llm(ctx)
    _log(run_id, "final_output", output)
    return output
