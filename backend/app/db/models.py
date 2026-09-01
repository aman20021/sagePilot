import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def now():
    return datetime.now(timezone.utc)


def gen_id():
    return str(uuid.uuid4())


class Supervisor(Base):
    __tablename__ = "supervisors"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    base_instruction = Column(Text, nullable=False)
    available_actions = Column(JSON, nullable=False, default=list)
    default_wakeup_minutes = Column(Integer, nullable=False, default=60)
    model = Column(String, nullable=True)
    wake_aggressiveness = Column(String, nullable=False, default="normal")  # low|normal|high
    created_at = Column(DateTime(timezone=True), default=now)


class Run(Base):
    __tablename__ = "runs"

    id = Column(String, primary_key=True, default=gen_id)
    supervisor_id = Column(String, ForeignKey("supervisors.id"), nullable=False)
    order_id = Column(String, nullable=False)
    order_context = Column(JSON, nullable=False, default=dict)
    status = Column(String, nullable=False, default="running")  # running|sleeping|paused|completed|terminated
    memory_summary = Column(Text, nullable=False, default="")
    next_wakeup_at = Column(DateTime(timezone=True), nullable=True)
    final_output = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    # event | wake_decision | sleep_decision | action | instruction | reasoning | final_output | status_change
    type = Column(String, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=now)
