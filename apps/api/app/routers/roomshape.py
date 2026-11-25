"""Room shell (M41): outline (L-shaped / U / angled walls), sloped or uneven ceiling, and fixed building parts — beams, columns,
pillars and ceiling drops. Survey data: every change re-checks the room's latest saved design and is logged on the project timeline."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import box
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models import models as m
from app.routers.api import _room_dims, room_openings, room_shape, room_structures
from app.routers.openings import STAFF, WRITE, _latest_check
from app.services import flow, shape

router = APIRouter(tags=["Survey"])
KINDS = ("BEAM", "COLUMN", "PILLAR", "CEILING_DROP")
NAME = {"BEAM": "Beam", "COLUMN": "Column", "PILLAR": "Pillar", "CEILING_DROP": "Ceiling drop"}


class ShapeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shape: dict | None = None            # {"type": "RECT"} | {"type": "CUTS", "cuts": {...}} | {"type": "POLYGON", "points": [...]}


class CeilingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ceiling: dict | None = None          # {"type": "FLAT"} | {"type": "SLOPED", ...} | {"type": "UNEVEN", "points": [...]}


class StructureIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    x_mm: float = Field(ge=-1, le=50000); y_mm: float = Field(ge=-1, le=50000)
    length_mm: float = Field(ge=50, le=50000); width_mm: float = Field(ge=50, le=50000)
    depth_mm: float | None = Field(None, ge=25, le=3000)
    label: str | None = Field(None, max_length=40)


class StructurePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x_mm: float | None = Field(None, ge=-1, le=50000); y_mm: float | None = Field(None, ge=-1, le=50000)
    length_mm: float | None = Field(None, ge=50, le=50000); width_mm: float | None = Field(None, ge=50, le=50000)
    depth_mm: float | None = Field(None, ge=25, le=3000)
    label: str | None = Field(None, max_length=40)


def _room(db: Session, rid: str) -> m.Room:
    r = db.get(m.Room, rid)
    if not r: raise HTTPException(404, "Room not found")
    return r


def _dims(db: Session, rid: str):
    try: return _room_dims(db, rid)
    except HTTPException: raise HTTPException(409, "Add the room's Length and Width first — the shape, ceiling and beams are measured inside them")


def _out(db: Session, rid: str) -> dict:
    s = room_shape(db, rid) or {}
    room = db.get(m.Room, rid); problems = []
    if s:
        try: shape.clean_shape(s["L"], s["W"], room.shape)
        except shape.ShapeError as e: problems.append(f"Room shape no longer fits the measurements: {e}")
        for o in room_openings(db, rid):
            if o.get("off_wall"): problems.append(f"{o['label']} no longer sits on a wall — move it")
    return {**s, "openings": room_openings(db, rid), "problems": problems, "latest_design": _latest_check(db, rid)}


@router.get("/rooms/{rid}/shape")
def get_shape(rid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    _room(db, rid); _dims(db, rid); return _out(db, rid)


@router.put("/rooms/{rid}/shape")
def put_shape(rid: str, b: ShapeIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    room = _room(db, rid); L, W, H = _dims(db, rid)
    try: new = shape.clean_shape(L, W, b.shape)
    except shape.ShapeError as e: raise HTTPException(422, str(e))
    stuck = []                                                            # doors/windows must still sit on a wall
    for o in room_openings(db, rid):                                     # …at the SAME place (wall numbers change with the shape)
        try:
            p = shape.resolve_opening(L, W, new, o)
            if "x0" in o and max(abs(p[k] - o[k]) for k in ("x0", "y0", "x1", "y1")) > 1: raise shape.ShapeError("moved")
        except shape.ShapeError: stuck.append(o["label"])
    if stuck: raise HTTPException(409, f"With this shape {', '.join(stuck)} would no longer sit on a wall — move or delete them first")
    pg = shape.polygon(L, W, new)
    for s in room_structures(db, rid):
        if not pg.buffer(1).intersects(box(s["x"], s["y"], s["x"] + s["length"], s["y"] + s["width"]).buffer(-1)):
            raise HTTPException(409, f"{s['label']} would be outside the room with this shape — move or delete it first")
    room.shape = new
    desc = "rectangular" if not new else ("L/U-shaped (corner cut " + ", ".join(f"{k} {v[0]:.0f}×{v[1]:.0f}" for k, v in new["cuts"].items()) + ")") if new["type"] == "CUTS" else f"{len(new['points'])}-sided outline"
    flow.event(db, room.project_id, "SURVEY", f"{room.name}: room shape set — {desc}, {pg.area / 1e6:.2f} sq.m", user)
    db.commit(); return _out(db, rid)


@router.put("/rooms/{rid}/ceiling")
def put_ceiling(rid: str, b: CeilingIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    room = _room(db, rid); L, W, H = _dims(db, rid)
    try: new = shape.clean_ceiling(L, W, b.ceiling)
    except shape.ShapeError as e: raise HTTPException(422, str(e))
    for o in room_openings(db, rid):                                     # every door/window still fits under the ceiling where it is
        if "x0" not in o: continue
        here = min(shape.ceiling_at(new, H, L, W, o["x0"], o["y0"]), shape.ceiling_at(new, H, L, W, o["x1"], o["y1"]))
        if (o["sill"] or 0) + o["height"] > here: raise HTTPException(409, f"{o['label']} ({(o['sill'] or 0) + o['height']:.0f} mm to its head) would be taller than this ceiling where it is ({here:.0f} mm)")
    room.ceiling_profile = new
    lo, hi = shape.ceiling_range(new, H, L, W)
    flow.event(db, room.project_id, "SURVEY", f"{room.name}: ceiling set — " + ("flat" if not new else f"{new['type'].lower()}, {lo:.0f}–{hi:.0f} mm"), user)
    db.commit(); return _out(db, rid)


def _check_structure(db: Session, rid: str, d: dict):
    L, W, H = _dims(db, rid); room = db.get(m.Room, rid)
    if d["kind"] not in KINDS: raise HTTPException(422, f"kind must be one of {', '.join(KINDS)}")
    r = box(d["x_mm"], d["y_mm"], d["x_mm"] + d["length_mm"], d["y_mm"] + d["width_mm"])
    if d["x_mm"] < -1 or d["y_mm"] < -1 or d["x_mm"] + d["length_mm"] > L + 1 or d["y_mm"] + d["width_mm"] > W + 1:
        raise HTTPException(422, f"{NAME[d['kind']]} runs outside the {L:.0f} × {W:.0f} mm room")
    pg = shape.polygon(L, W, room.shape)
    if pg.intersection(r).area < r.area * 0.5: raise HTTPException(422, f"{NAME[d['kind']]} is mostly outside the room's shape")
    if d["kind"] in ("BEAM", "CEILING_DROP"):
        if not d.get("depth_mm"): raise HTTPException(422, f"Give the {NAME[d['kind']].lower()}'s depth below the ceiling (mm)")
        low = shape.lowest_over(room.ceiling_profile, H, L, W, r) - d["depth_mm"]
        if low < 1500: raise HTTPException(422, f"The {NAME[d['kind']].lower()}'s underside would be {low:.0f} mm above the floor — check the depth")
    else: d["depth_mm"] = None
    return d


def _label(db: Session, rid: str, kind: str) -> str:
    return f"{NAME[kind]} {db.query(m.RoomStructure).filter_by(room_id=rid, kind=kind).count() + 1}"


@router.post("/rooms/{rid}/structures", status_code=201)
def add_structure(rid: str, b: StructureIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    room = _room(db, rid)
    d = _check_structure(db, rid, {**b.model_dump(), "kind": b.kind.upper()})
    d["label"] = (d.get("label") or "").strip() or _label(db, rid, d["kind"])
    db.add(m.RoomStructure(room_id=rid, **d))
    flow.event(db, room.project_id, "SURVEY", f"{room.name}: {d['label']} added ({d['length_mm']:.0f} × {d['width_mm']:.0f} mm"
               + (f", {d['depth_mm']:.0f} mm deep" if d.get("depth_mm") else "") + ")", user)
    db.commit(); return _out(db, rid)


@router.patch("/structures/{sid}")
def patch_structure(sid: str, b: StructurePatch, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    x = db.get(m.RoomStructure, sid)
    if not x: raise HTTPException(404, "Structure not found")
    ch = b.model_dump(exclude_unset=True)
    for k in ("x_mm", "y_mm", "length_mm", "width_mm"):
        if k in ch and ch[k] is None: raise HTTPException(422, f"{k} cannot be empty")
    d = _check_structure(db, x.room_id, {"kind": x.kind, "x_mm": x.x_mm, "y_mm": x.y_mm, "length_mm": x.length_mm, "width_mm": x.width_mm,
                                         "depth_mm": x.depth_mm, "label": x.label, **ch})
    for k, v in d.items():
        if k != "kind": setattr(x, k, v)
    db.commit(); return _out(db, x.room_id)


@router.delete("/structures/{sid}")
def delete_structure(sid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    x = db.get(m.RoomStructure, sid)
    if not x: raise HTTPException(404, "Structure not found")
    rid = x.room_id; room = db.get(m.Room, rid)
    flow.event(db, room.project_id, "SURVEY", f"{room.name}: {x.label} removed", user)
    db.delete(x); db.commit(); return _out(db, rid)
