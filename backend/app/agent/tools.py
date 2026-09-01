"""Business action definitions. Each execution creates an activity record."""

TOOL_DEFS = [
    {
        "name": "message_fulfillment_team",
        "description": "Send a message to the fulfillment team about this order (e.g. packing, stock, delays).",
        "params": {"message": "The message to send to the fulfillment team."},
    },
    {
        "name": "message_payments_team",
        "description": "Send a message to the payments team (e.g. failed payments, refunds, chargebacks).",
        "params": {"message": "The message to send to the payments team."},
    },
    {
        "name": "message_logistics_team",
        "description": "Send a message to the logistics team (e.g. shipment delays, carrier issues).",
        "params": {"message": "The message to send to the logistics team."},
    },
    {
        "name": "message_customer",
        "description": "Send a message directly to the customer about their order.",
        "params": {"message": "The message to send to the customer."},
    },
    {
        "name": "create_internal_note",
        "description": "Create an internal note on the order for future reference.",
        "params": {"note": "The content of the internal note."},
    },
]

RUNTIME_TOOL_DEFS = [
    {
        "name": "update_memory",
        "description": "Replace the compact memory summary for this run with an updated rolling summary.",
        "params": {"summary": "The new compact memory summary (a few sentences)."},
    },
    {
        "name": "sleep",
        "description": "Finish this reasoning turn and go to sleep. Always call this last.",
        "params": {
            "minutes": "Number of minutes to sleep before the next scheduled wake-up.",
            "reason": "Short reason for the chosen sleep duration.",
            "wake_guidance": "Optional guidance for the event classifier about which future events should wake you.",
        },
    },
]
