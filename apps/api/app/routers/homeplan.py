"""Whole-home plan endpoints: where each room sits in the house, auto-arrange, overlap checks, whole-house DXF, everything for the home 3D view."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models import models as m
from app.services import flow, homeplan

router = APIRouter(tags=["Home plan"])
STAFF = tuple(r for r in m.ROLES if r not in ("CLIENT",))
EDIT = ("ADMIN", "PROJECT_MANAGER", "INTERIOR_DESIGNER", "SITE_ENGINEER")


def _project(db: Session, pid: str) -> m.Project:
    p = db.get(m.Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    return p


def plan_out(db: Session, pid: str) -> dict:
    from app.routers.api import room_openings, room_shape
    rows = homeplan.boxes(db, pid)
    for r in rows:
        des = db.query(m.Design).filter_by(room_id=r["id"]).order_by(m.Design.version.desc()).first()
        r["openings"] = room_openings(db, r["id"])
        r["shell"] = room_shape(db, r["id"])                     # M41: outline, ceiling profile, beams/columns (None = not measured)
        r["objects"] = des.design_json.get("objects", []) if des else []
        r["finishes"] = (des.design_json.get("finishes") if des else None)
        r["design_version"] = des.version if des else None
    placed = [r for r in rows if r["placed"] and r["L"]]
    bounds = ({"x0": min(r["x"] for r in placed), "y0": min(r["y"] for r in placed), "x1": max(r["x"] + r["L"] for r in placed),
               "y1": max(r["y"] + r["W"] for r in placed)} if placed else None)
    return {"rooms": rows, "warnings": homeplan.overlaps(rows), "bounds": bounds, "wall_mm": homeplan.WALL,
            "unmeasured": [r["name"] for r in rows if not r["L"]], "room_types": homeplan.ROOM_TYPES}


@router.get("/projects/{pid}/home-plan")
def get_plan(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    _project(db, pid); return plan_out(db, pid)


class Pos(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    x: float = Field(ge=-100_000, le=100_000)
    y: float = Field(ge=-100_000, le=100_000)
    level: int = Field(default=0, ge=-1, le=10)


class PlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rooms: list[Pos] = Field(max_length=100)


@router.put("/projects/{pid}/home-plan")
def put_plan(pid: str, b: PlanIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*EDIT))):
    _project(db, pid)
    rooms = {r.id: r for r in db.query(m.Room).filter_by(project_id=pid)}
    for p in b.rooms:
        r = rooms.get(p.id)
        if not r: raise HTTPException(404, "That room is not in this project")
        r.plan_x, r.plan_y, r.level = round(p.x / 10) * 10, round(p.y / 10) * 10, p.level
    flow.event(db, pid, "DESIGN", f"Home plan updated ({len(b.rooms)} room(s) placed)", user)
    db.commit(); return plan_out(db, pid)


class AutoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    all_rooms: bool = False          # true = re-arrange every room; false = only rooms not placed yet


@router.post("/projects/{pid}/home-plan/auto")
def auto_plan(pid: str, b: AutoIn = AutoIn(), db: Session = Depends(get_db), user: dict = Depends(require_roles(*EDIT))):
    _project(db, pid)
    pos = homeplan.arrange(homeplan.boxes(db, pid), only_unplaced=not b.all_rooms)
    for r in db.query(m.Room).filter(m.Room.id.in_(list(pos))) if pos else []:
        r.plan_x, r.plan_y = pos[r.id]
    if pos: flow.event(db, pid, "DESIGN", f"Home plan: {len(pos)} room(s) arranged automatically", user)
    db.commit(); return plan_out(db, pid)


@router.get("/projects/{pid}/home-plan.dxf")
def plan_dxf(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    p = _project(db, pid)
    if not any(r["placed"] and r["L"] for r in homeplan.boxes(db, pid)): raise HTTPException(409, "Place the rooms on the home plan first")
    return Response(homeplan.house_dxf(db, pid, p.name), media_type="application/dxf",
                    headers={"Content-Disposition": f'attachment; filename="home-plan-{p.project_number}.dxf"'})
