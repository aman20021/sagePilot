"""Main agent runtime: Gemini function-calling loop with a deterministic mock fallback."""

import json
import logging
from typing import Any, Callable

from app.agent.tools import RUNTIME_TOOL_DEFS, TOOL_DEFS
from app.config import settings

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 8


def _gemini_tool_schema(defs: list[dict]) -> list[dict]:
    fns = []
    for d in defs:
        fns.append(
            {
                "name": d["name"],
                "description": d["description"],
                "parameters": {
                    "type": "OBJECT",
                    "properties": {k: {"type": "STRING", "description": v} for k, v in d["params"].items()},
                    "required": [k for k in d["params"] if k not in ("wake_guidance",)],
                },
            }
        )
    return fns


def build_prompt(ctx: dict[str, Any]) -> str:
    return f"""You are an AI order supervisor overseeing a single e-commerce order.

## Base instruction
{ctx["base_instruction"]}

## Order context
{json.dumps(ctx["order_context"], indent=2)}

## Why you woke up
{ctx["wake_reason"]}

## New events since your last wake-up
{json.dumps(ctx["new_events"], indent=2) if ctx["new_events"] else "(none)"}

## Run-specific extra instructions from the operator
{json.dumps(ctx["instructions"], indent=2) if ctx["instructions"] else "(none)"}

## Your compact memory summary of everything so far
{ctx["memory_summary"] or "(empty — this is your first wake-up)"}

## Recent timeline (newest last)
{json.dumps(ctx["timeline"], indent=2)}

## Your job this turn
1. Reason about whether intervention is needed.
2. If needed, call business action tools (only from your available actions: {ctx["available_actions"]}).
3. Call update_memory with a refreshed rolling summary that compacts old history and keeps important facts.
4. Finally, ALWAYS call sleep(minutes, reason, wake_guidance) to end your turn. Default sleep is {ctx["default_wakeup_minutes"]} minutes if nothing is urgent.

Do not act if nothing requires action — just update memory and sleep. Be concise in messages."""


def run_agent_llm(ctx: dict[str, Any], record_action: Callable[[str, dict], None]) -> dict[str, Any]:
    """Run one agent inference turn. Returns {actions, memory_summary, sleep_minutes, sleep_reason, wake_guidance, reasoning}."""
    if not settings.gemini_api_key:
        return _run_mock_agent(ctx, record_action)
    try:
        return _run_gemini_agent(ctx, record_action)
    except Exception:
        logger.exception("Gemini agent failed, falling back to mock agent")
        return _run_mock_agent(ctx, record_action)


def _run_gemini_agent(ctx: dict[str, Any], record_action: Callable[[str, dict], None]) -> dict[str, Any]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    model = ctx.get("model") or settings.gemini_model

    available = [d for d in TOOL_DEFS if d["name"] in ctx["available_actions"]]
    tools = types.Tool(function_declarations=_gemini_tool_schema(available + RUNTIME_TOOL_DEFS))
    config = types.GenerateContentConfig(tools=[tools], temperature=0.2)

    contents: list[Any] = [types.Content(role="user", parts=[types.Part(text=build_prompt(ctx))])]

    result: dict[str, Any] = {
        "actions": [],
        "memory_summary": ctx["memory_summary"],
        "sleep_minutes": ctx["default_wakeup_minutes"],
        "sleep_reason": "default schedule",
        "wake_guidance": ctx.get("wake_guidance", ""),
        "reasoning": "",
    }

    for _ in range(MAX_TOOL_ITERATIONS):
        resp = client.models.generate_content(model=model, contents=contents, config=config)
        candidate = resp.candidates[0]
        contents.append(candidate.content)

        fn_calls = [p.function_call for p in (candidate.content.parts or []) if p.function_call]
        texts = [p.text for p in (candidate.content.parts or []) if p.text]
        if texts:
            result["reasoning"] += " ".join(t.strip() for t in texts) + " "

        if not fn_calls:
            break

        slept = False
        response_parts = []
        for fc in fn_calls:
            name, args = fc.name, dict(fc.args or {})
            if name == "sleep":
                result["sleep_minutes"] = max(1, int(float(args.get("minutes", ctx["default_wakeup_minutes"]))))
                result["sleep_reason"] = args.get("reason", "")
                result["wake_guidance"] = args.get("wake_guidance", result["wake_guidance"])
                slept = True
                out = {"status": "sleeping"}
            elif name == "update_memory":
                result["memory_summary"] = args.get("summary", result["memory_summary"])
                out = {"status": "memory updated"}
            else:
                record_action(name, args)
                result["actions"].append({"action": name, "args": args})
                out = {"status": f"{name} recorded"}
            response_parts.append(
                types.Part(function_response=types.FunctionResponse(name=name, response=out))
            )
        contents.append(types.Content(role="user", parts=response_parts))
        if slept:
            break

    result["reasoning"] = result["reasoning"].strip()
    return result


def _run_mock_agent(ctx: dict[str, Any], record_action: Callable[[str, dict], None]) -> dict[str, Any]:
    """Deterministic fallback so the system works without an LLM key."""
    actions = []
    new_types = [e.get("type") for e in ctx["new_events"]]

    def act(name: str, args: dict):
        if name in ctx["available_actions"]:
            record_action(name, args)
            actions.append({"action": name, "args": args})

    order_id = ctx["order_context"].get("order_id", "order")
    if "payment_failed" in new_types:
        act("message_payments_team", {"message": f"Payment failed for {order_id}. Please investigate and retry."})
        act("message_customer", {"message": "We hit a payment issue with your order and are looking into it."})
    if "shipment_delayed" in new_types:
        act("message_logistics_team", {"message": f"Shipment delayed for {order_id}. Please expedite."})
        act("message_customer", {"message": "Your shipment is slightly delayed; we are on it."})
    if "refund_requested" in new_types:
        act("message_payments_team", {"message": f"Refund requested for {order_id}. Please process per policy."})
    if "customer_message_received" in new_types:
        act("message_customer", {"message": "Thanks for reaching out — we have received your message and are reviewing your order."})
    if "no_update_for_n_hours" in new_types:
        act("message_fulfillment_team", {"message": f"No updates on {order_id} for a while. Please provide a status."})
    if not actions:
        act("create_internal_note", {"note": f"Reviewed {order_id}; no intervention needed at this time."})

    summary_bits = [ctx["memory_summary"]] if ctx["memory_summary"] else []
    if new_types:
        summary_bits.append(f"Handled events: {', '.join(new_types)}.")
    summary_bits.append(f"Took {len(actions)} action(s) on last wake ({ctx['wake_reason']}).")
    urgent = any(t in {"payment_failed", "shipment_delayed", "refund_requested"} for t in new_types)
    return {
        "actions": actions,
        "memory_summary": " ".join(summary_bits)[-1500:],
        "sleep_minutes": 15 if urgent else ctx["default_wakeup_minutes"],
        "sleep_reason": "urgent follow-up soon" if urgent else "routine schedule",
        "wake_guidance": "",
        "reasoning": "(mock agent) rule-based response to events",
    }


def generate_final_summary_llm(ctx: dict[str, Any]) -> dict[str, Any]:
    """Produce end-of-run output: summary, actions, learnings, feedback."""
    if settings.gemini_api_key:
        try:
            from google import genai

            client = genai.Client(api_key=settings.gemini_api_key)
            prompt = f"""You are an AI order supervisor finishing a run. Produce a final report as pure JSON with keys:
"final_summary" (string), "important_actions" (array of strings), "key_learnings" (array of strings), "recommendations" (array of strings).

Memory summary: {ctx["memory_summary"]}
Full timeline: {json.dumps(ctx["timeline"], indent=2)}
Completion reason: {ctx["completion_reason"]}

Respond with ONLY the JSON object."""
            resp = client.models.generate_content(
                model=ctx.get("model") or settings.gemini_model, contents=prompt
            )
            text = resp.text.strip()
            if text.startswith("```"):
                text = text.split("```")[1].removeprefix("json").strip()
            return json.loads(text)
        except Exception:
            logger.exception("Gemini final summary failed, using fallback")

    actions = [e for e in ctx["timeline"] if e.get("type") == "action"]
    events = [e for e in ctx["timeline"] if e.get("type") == "event"]
    return {
        "final_summary": f"Run completed ({ctx['completion_reason']}). Processed {len(events)} events and took {len(actions)} actions. {ctx['memory_summary']}",
        "important_actions": [f"{a['payload'].get('action')}: {json.dumps(a['payload'].get('args', {}))}" for a in actions][:10],
        "key_learnings": ["Timely intervention on critical events kept the order on track."],
        "recommendations": ["Review recurring delay/payment patterns across orders."],
    }
