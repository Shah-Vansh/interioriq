"""M22 project team: who works on a project. With 'Limit staff to their projects' on, only team members (plus admins and the
roles that see every project) can open it. Adding / removing people is logged on the project timeline."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models import models as m
from app.services import access, flow

router = APIRouter(tags=["Team"])
STAFF = tuple(r for r in m.ROLES if r != "CLIENT")
MANAGE = ("ADMIN", "PROJECT_MANAGER")


def _project(db: Session, pid: str) -> m.Project:
    p = db.get(m.Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    return p


def _out(db: Session, pid: str) -> dict:
    rows = db.query(m.ProjectMember, m.User).join(m.User, m.User.id == m.ProjectMember.user_id).filter(m.ProjectMember.project_id == pid).order_by(m.User.full_name).all()
    on = {u.id for _, u in rows}; everyone = access.all_roles(db)
    staff = db.query(m.User).filter(m.User.role != "CLIENT", m.User.is_active.isnot(False)).order_by(m.User.full_name).all()
    return {"limited": access.limited(db), "all_projects_roles": sorted(everyone),
            "members": [{"user_id": u.id, "name": u.full_name, "email": u.email, "role": u.role, "active": u.is_active is not False, "added_by": pm.added_by,
                         "added_at": pm.created_at.isoformat() if pm.created_at else None} for pm, u in rows],
            "can_add": [{"user_id": u.id, "name": u.full_name, "role": u.role} for u in staff if u.id not in on],
            "sees_all": [{"user_id": u.id, "name": u.full_name, "role": u.role} for u in staff if u.role in everyone and u.id not in on]}


@router.get("/projects/{pid}/team")
def get_team(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    _project(db, pid); return _out(db, pid)


class AddIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str


@router.post("/projects/{pid}/team", status_code=201)
def add(pid: str, b: AddIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*MANAGE))):
    p = _project(db, pid); u = db.get(m.User, b.user_id)
    if not u or u.role == "CLIENT": raise HTTPException(422, "Pick a staff user (clients see their projects through the client portal)")
    if u.is_active is False: raise HTTPException(422, f"{u.full_name}'s account is deactivated")
    if not access.add_member(db, p.id, u.id, user): raise HTTPException(409, f"{u.full_name} is already on the team")
    flow.event(db, p.id, "TEAM", f"{u.full_name} ({u.role.replace('_', ' ').lower()}) added to the team", user)
    db.commit(); return _out(db, pid)


@router.delete("/projects/{pid}/team/{uid}")
def remove(pid: str, uid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*MANAGE))):
    p = _project(db, pid)
    row = db.query(m.ProjectMember).filter_by(project_id=pid, user_id=uid).first()
    if not row: raise HTTPException(404, "Not on this team")
    if uid == user.get("sub") and not access.can(db, {**user, "sub": "__nobody__"}, pid) and access.limited(db):
        raise HTTPException(409, "You'd lose access to this project — ask an admin or another manager on the team to remove you.")
    u = db.get(m.User, uid); db.delete(row)
    flow.event(db, p.id, "TEAM", f"{u.full_name if u else 'A user'} removed from the team", user)
    db.commit(); return _out(db, pid)
