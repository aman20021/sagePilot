from fastapi import APIRouter, HTTPException

from app.db.models import Supervisor
from app.db.session import db_session
from app.schemas import SupervisorCreate, SupervisorOut

router = APIRouter(prefix="/api/supervisors", tags=["supervisors"])


@router.post("", response_model=SupervisorOut)
def create_supervisor(body: SupervisorCreate):
    with db_session() as s:
        sup = Supervisor(**body.model_dump())
        s.add(sup)
        s.flush()
        return SupervisorOut.model_validate(sup)


@router.get("", response_model=list[SupervisorOut])
def list_supervisors():
    with db_session() as s:
        rows = s.query(Supervisor).order_by(Supervisor.created_at.desc()).all()
        return [SupervisorOut.model_validate(r) for r in rows]


@router.get("/{supervisor_id}", response_model=SupervisorOut)
def get_supervisor(supervisor_id: str):
    with db_session() as s:
        sup = s.get(Supervisor, supervisor_id)
        if not sup:
            raise HTTPException(404, "supervisor not found")
        return SupervisorOut.model_validate(sup)
