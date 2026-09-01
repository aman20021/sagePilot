"""OrderSupervisorWorkflow: one long-running workflow per order.

Wake triggers: workflow start, incoming signal (event/instruction), scheduled wake-up.
Completion is workflow-owned: terminal event, manual terminate, or max age.
"""

from datetime import timedelta
from typing import Any, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.temporal.activities import (
        classify_event_activity,
        generate_final_summary_activity,
        record_activity,
        run_agent_activity,
        update_run_state,
    )

TERMINAL_EVENTS = {"delivered"}
ACTIVITY_OPTS = dict(
    start_to_close_timeout=timedelta(minutes=2),
    retry_policy=RetryPolicy(maximum_attempts=3),
)


@workflow.defn
class OrderSupervisorWorkflow:
    def __init__(self) -> None:
        self.pending_events: list[dict] = []
        self.pending_instructions: list[str] = []
        self.instructions: list[str] = []
        self.paused = False
        self.terminate_requested = False
        self.memory_summary = ""
        self.wake_guidance = ""
        self.sleep_minutes = 60.0
        self.status = "starting"
        self.completion_reason: Optional[str] = None
        self.final_output: Optional[dict] = None

    # ---------- signals ----------
    @workflow.signal
    def order_event(self, event: dict) -> None:
        self.pending_events.append(event)

    @workflow.signal
    def add_instruction(self, instruction: str) -> None:
        self.pending_instructions.append(instruction)

    @workflow.signal
    def pause(self) -> None:
        self.paused = True

    @workflow.signal
    def resume(self) -> None:
        self.paused = False

    @workflow.signal
    def terminate(self) -> None:
        self.terminate_requested = True

    # ---------- queries ----------
    @workflow.query
    def get_state(self) -> dict:
        return {
            "status": self.status,
            "paused": self.paused,
            "memory_summary": self.memory_summary,
            "wake_guidance": self.wake_guidance,
            "instructions": self.instructions,
            "pending_events": len(self.pending_events),
        }

    # ---------- helpers ----------
    async def _run_agent(self, wake_reason: str, new_events: list[dict], cfg: dict) -> None:
        self.status = "thinking"
        await workflow.execute_activity(
            update_run_state,
            args=[cfg["run_id"], "running", None, None, None],
            **ACTIVITY_OPTS,
        )
        result = await workflow.execute_activity(
            run_agent_activity,
            {
                "run_id": cfg["run_id"],
                "base_instruction": cfg["base_instruction"],
                "order_context": cfg["order_context"],
                "available_actions": cfg["available_actions"],
                "default_wakeup_minutes": cfg["default_wakeup_minutes"],
                "model": cfg.get("model"),
                "wake_reason": wake_reason,
                "new_events": new_events,
                "instructions": self.instructions,
                "memory_summary": self.memory_summary,
                "wake_guidance": self.wake_guidance,
            },
            **ACTIVITY_OPTS,
        )
        self.memory_summary = result["memory_summary"]
        self.sleep_minutes = float(result["sleep_minutes"])
        self.wake_guidance = result.get("wake_guidance") or self.wake_guidance
        self.status = "sleeping"
        await workflow.execute_activity(
            update_run_state,
            args=[cfg["run_id"], "sleeping", self.memory_summary, self.sleep_minutes, None],
            **ACTIVITY_OPTS,
        )

    def _terminal_event(self) -> Optional[str]:
        for e in self.pending_events:
            if e.get("type") in TERMINAL_EVENTS:
                return e["type"]
        return None

    # ---------- main ----------
    @workflow.run
    async def run(self, cfg: dict[str, Any]) -> dict:
        run_id = cfg["run_id"]
        max_age = timedelta(hours=cfg.get("max_age_hours", 72))
        start_time = workflow.now()

        await workflow.execute_activity(
            record_activity,
            args=[run_id, "status_change", {"status": "started", "order_id": cfg["order_context"].get("order_id")}],
            **ACTIVITY_OPTS,
        )

        # Trigger 1: workflow start
        await self._run_agent("workflow started — initial review of the order", [], cfg)

        while True:
            # ----- completion rules (workflow-owned) -----
            if self.terminate_requested:
                self.completion_reason = "manually terminated from UI"
                break
            if workflow.now() - start_time > max_age:
                self.completion_reason = f"max workflow age of {cfg.get('max_age_hours', 72)}h reached"
                break

            # ----- sleep until: signal arrives OR scheduled wake-up -----
            timed_out = False
            try:
                await workflow.wait_condition(
                    lambda: bool(self.pending_events)
                    or bool(self.pending_instructions)
                    or self.terminate_requested,
                    timeout=timedelta(minutes=self.sleep_minutes),
                )
            except TimeoutError:
                timed_out = True

            if self.terminate_requested:
                self.completion_reason = "manually terminated from UI"
                break

            if self.paused:
                self.status = "paused"
                await workflow.execute_activity(
                    update_run_state, args=[run_id, "paused", None, None, None], **ACTIVITY_OPTS
                )
                await workflow.wait_condition(lambda: not self.paused or self.terminate_requested)
                if self.terminate_requested:
                    self.completion_reason = "manually terminated from UI"
                    break

            # ----- new instructions always wake the agent -----
            new_instructions = self.pending_instructions
            self.pending_instructions = []
            self.instructions.extend(new_instructions)

            # ----- drain and classify events -----
            events = self.pending_events
            self.pending_events = []
            terminal = next((e["type"] for e in events if e.get("type") in TERMINAL_EVENTS), None)

            wake = bool(new_instructions)
            wake_reasons = [f"new operator instruction: {i}" for i in new_instructions]
            for event in events:
                await workflow.execute_activity(
                    record_activity, args=[run_id, "event", event], **ACTIVITY_OPTS
                )
                decision = await workflow.execute_activity(
                    classify_event_activity,
                    args=[event.get("type", "unknown"), cfg.get("wake_aggressiveness", "normal"), self.wake_guidance],
                    **ACTIVITY_OPTS,
                )
                await workflow.execute_activity(
                    record_activity,
                    args=[run_id, "wake_decision", {"event": event.get("type"), **decision}],
                    **ACTIVITY_OPTS,
                )
                if decision["wake"]:
                    wake = True
                    wake_reasons.append(f"event '{event.get('type')}': {decision['reason']}")

            # Trigger 2: signal / Trigger 3: scheduled wake-up
            if timed_out and not events and not new_instructions:
                await self._run_agent("scheduled wake-up — periodic review", [], cfg)
            elif wake:
                await self._run_agent("; ".join(wake_reasons), events, cfg)

            if terminal:
                self.completion_reason = f"terminal order event '{terminal}' received"
                break

        # ----- end of run: final summary, learnings, feedback -----
        self.status = "finalizing"
        self.final_output = await workflow.execute_activity(
            generate_final_summary_activity,
            {
                "run_id": run_id,
                "memory_summary": self.memory_summary,
                "completion_reason": self.completion_reason,
                "model": cfg.get("model"),
            },
            **ACTIVITY_OPTS,
        )
        final_status = "terminated" if "terminated" in (self.completion_reason or "") else "completed"
        self.status = final_status
        await workflow.execute_activity(
            update_run_state,
            args=[run_id, final_status, self.memory_summary, None, self.final_output],
            **ACTIVITY_OPTS,
        )
        await workflow.execute_activity(
            record_activity,
            args=[run_id, "status_change", {"status": final_status, "reason": self.completion_reason}],
            **ACTIVITY_OPTS,
        )
        return {"completion_reason": self.completion_reason, "final_output": self.final_output}
