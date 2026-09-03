from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.runs import router as runs_router
from app.api.supervisors import router as supervisors_router
from app.db.models import Supervisor
from app.db.session import db_session, init_db
from app.schemas import BUSINESS_ACTIONS

DEFAULT_TEMPLATE = {
    "name": "Standard Order Supervisor",
    "base_instruction": (
        "You supervise a single e-commerce order from creation to completion. "
        "Keep the customer informed on important changes, escalate payment and "
        "shipping problems to the right internal team quickly, and keep concise "
        "internal notes. Prefer minimal, high-value interventions."
    ),
    "available_actions": BUSINESS_ACTIONS,
    "default_wakeup_minutes": 60,
    "wake_aggressiveness": "normal",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with db_session() as s:
        if not s.query(Supervisor).first():
            s.add(Supervisor(**DEFAULT_TEMPLATE))
    yield


app = FastAPI(title="Order Supervisor", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(supervisors_router)
app.include_router(runs_router)


@app.get("/api/health")
def health():
    return {"ok": True}
