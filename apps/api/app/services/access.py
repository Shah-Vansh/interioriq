"""M22 per-project staff permissions.

Off by default (Settings → Company: 'Limit staff to their projects'). When it is on, a staff member sees and works on a project only if
they are on its team (project_members) — except ADMIN / SUPER_ADMIN and the roles listed in 'Roles that see every project'
(default: procurement and inventory, who work across projects). CLIENT users only ever see their own client's projects (unchanged).

One place decides (visible_ids); routes use it three ways:
  * guard()  — an app-wide dependency: any request whose path names a project-scoped record (/projects/{id}, /rooms/{id}, /boqs/{id},
               /invoices/{id}, /purchase-orders/{id}, …) or carries ?project_id= is refused (403) unless that project is visible;
  * scope()  — list endpoints filter their query to visible projects;
  * company_wide() — screens that summarise every project at once (payables) are only for users who see every project."""
import re

import jwt
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import models as m
from app.services import company

ALWAYS_ALL = {"SUPER_ADMIN", "ADMIN"}
DEFAULT_ALL_ROLES = "PROCUREMENT_MANAGER, INVENTORY_MANAGER"
NO_ACCESS = "You're not on this project's team. Ask an admin or the project manager to add you (project page → Team)."


def all_roles(db: Session) -> set:
    raw = company.get(db).get("all_projects_roles") or ""
    return ALWAYS_ALL | {r.strip().upper() for r in str(raw).split(",") if r.strip()}


def limited(db: Session) -> bool: return bool(company.get(db).get("limit_staff_to_projects"))


def visible_ids(db: Session, user: dict) -> set | None:
    """None = every project; otherwise the set of project ids this user may see."""
    role = user.get("role")
    if role == "CLIENT":
        cid = user.get("client_id") or (db.get(m.User, user.get("sub")).client_id if db.get(m.User, user.get("sub")) else None)
        return {p.id for p in db.query(m.Project.id).filter(m.Project.client_id == (cid or "__none__"))}
    if role in ALWAYS_ALL or not limited(db) or role in all_roles(db): return None
    return {r.project_id for r in db.query(m.ProjectMember.project_id).filter_by(user_id=user.get("sub"))}


def can(db: Session, user: dict, pid: str | None) -> bool:
    ids = visible_ids(db, user)
    return ids is None or (pid is not None and pid in ids)


def check(db: Session, user: dict, pid: str | None):
    if pid and not can(db, user, pid): raise HTTPException(403, NO_ACCESS)


def scope(q, column, db: Session, user: dict):
    ids = visible_ids(db, user)
    return q if ids is None else q.filter(column.in_(ids or {"__none__"}))


def company_wide(db: Session, user: dict, what: str):
    if visible_ids(db, user) is not None:
        raise HTTPException(403, f"{what} covers every project, so it's only for roles that see all projects while 'Limit staff to their projects' is on.")


# ── app-wide guard ───────────────────────────────────────────────────────────
def _via_room(db, rid):
    r = db.get(m.Room, rid); return r.project_id if r else None


def _boq(db, bid):
    b = db.get(m.Boq, bid); return _via_room(db, b.room_id) if b else None


def _opening(db, oid):
    o = db.get(m.Opening, oid); return _via_room(db, o.room_id) if o else None


def _structure(db, sid):
    o = db.get(m.RoomStructure, sid); return _via_room(db, o.room_id) if o else None


def _col(model):
    def f(db, rid):
        x = db.get(model, rid); return getattr(x, "project_id", None) if x else None
    return f


RESOLVE = {
    "projects": lambda db, i: i if db.get(m.Project, i) else None, "rooms": _via_room, "boqs": _boq, "openings": _opening, "structures": _structure,
    "invoices": _col(m.Invoice), "purchase-orders": _col(m.PurchaseOrder), "work-orders": _col(m.WorkOrder), "deliveries": _col(m.DeliveryNote),
    "install-tasks": _col(m.InstallTask), "qc-checks": _col(m.QCCheck), "snags": _col(m.Snag), "documents": _col(m.Document),
    "messages": _col(m.Message), "expenses": _col(m.Expense), "bills": _col(m.SupplierBill),
}
PATH = re.compile(r"^/api/(" + "|".join(map(re.escape, RESOLVE)) + r")/([^/]+)")


def _user(request: Request, db: Session) -> dict | None:
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "): return None
    try: claims = jwt.decode(auth[7:], settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError: return None                                         # the route's own auth answers 401
    u = db.get(m.User, claims.get("sub"))
    if not u or not u.is_active: return None
    return {**claims, "role": u.role, "client_id": u.client_id}


def guard(request: Request):
    path = request.scope.get("path", "")
    mt = PATH.match(path); qpid = request.query_params.get("project_id")
    if not mt and not qpid: return
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        user = _user(request, db)
        if not user: return
        if visible_ids(db, user) is None: return
        if qpid: check(db, user, qpid)
        if mt:
            pid = RESOLVE[mt.group(1)](db, mt.group(2))
            if pid: check(db, user, pid)
            elif mt.group(1) == "bills" and db.get(m.SupplierBill, mt.group(2)): company_wide(db, user, "An overhead bill")
    finally:
        db.close()


# ── team ─────────────────────────────────────────────────────────────────────
def add_member(db: Session, pid: str, uid: str | None, by: dict | None = None) -> bool:
    if not uid or not db.get(m.User, uid): return False
    if db.query(m.ProjectMember).filter_by(project_id=pid, user_id=uid).first(): return False
    db.add(m.ProjectMember(project_id=pid, user_id=uid, added_by=(by or {}).get("name"))); return True
