"""Lightweight wake/sleep policy: decides if an event should wake the main agent."""

CRITICAL_EVENTS = {
    "payment_failed",
    "shipment_delayed",
    "refund_requested",
    "customer_message_received",
    "no_update_for_n_hours",
}

ROUTINE_EVENTS = {
    "order_created",
    "payment_confirmed",
    "shipment_created",
}

TERMINAL_EVENTS = {"delivered"}


def classify_event(event_type: str, aggressiveness: str = "normal", wake_guidance: str = "") -> dict:
    """Rule-based classifier. Returns {"wake": bool, "reason": str}."""
    guidance = wake_guidance.lower()
    if event_type in guidance:
        return {"wake": True, "reason": f"agent wake-up guidance mentions '{event_type}'"}
    if event_type in TERMINAL_EVENTS:
        return {"wake": True, "reason": "terminal event, agent must do a final review"}
    if event_type in CRITICAL_EVENTS:
        return {"wake": True, "reason": "critical event requires immediate attention"}
    if event_type in ROUTINE_EVENTS:
        if aggressiveness == "high":
            return {"wake": True, "reason": "routine event, but supervisor is configured to wake aggressively"}
        return {"wake": False, "reason": "routine event recorded on timeline; agent stays asleep"}
    # unknown event -> escalate by waking
    return {"wake": True, "reason": "unknown event type, escalating to agent"}
