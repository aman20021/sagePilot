from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

BUSINESS_ACTIONS = [
    "message_fulfillment_team",
    "message_payments_team",
    "message_logistics_team",
    "message_customer",
    "create_internal_note",
]

EVENT_TYPES = [
    "order_created",
    "payment_confirmed",
    "payment_failed",
    "shipment_created",
    "shipment_delayed",
    "delivered",
    "refund_requested",
    "customer_message_received",
    "no_update_for_n_hours",
]

TERMINAL_EVENTS = {"delivered"}


class SupervisorCreate(BaseModel):
    name: str
    base_instruction: str
    available_actions: list[str] = BUSINESS_ACTIONS
    default_wakeup_minutes: int = 60
    model: Optional[str] = None
    wake_aggressiveness: str = "normal"


class SupervisorOut(SupervisorCreate):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True


class RunCreate(BaseModel):
    supervisor_id: str
    order_id: str
    order_context: dict[str, Any] = {}


class RunOut(BaseModel):
    id: str
    supervisor_id: str
    order_id: str
    order_context: dict[str, Any]
    status: str
    memory_summary: str
    next_wakeup_at: Optional[datetime]
    final_output: Optional[dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ActivityOut(BaseModel):
    id: int
    run_id: str
    type: str
    payload: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class EventIn(BaseModel):
    type: str
    payload: dict[str, Any] = {}


class InstructionIn(BaseModel):
    instruction: str
