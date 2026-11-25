"""Doors and windows of a room (survey data). Every change re-checks the room's latest saved design against the new openings."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models import models as m
from app.routers.api import _geo, _room_dims, room_openings
from app.services import flow, geometry, shape

router = APIRouter(tags=["Survey"])
WRITE = ("ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "INTERIOR_DESIGNER")
SWINGS = ["INWARD_LEFT", "INWARD_RIGHT", "OUTWARD", "SLIDING"]
STAFF = tuple(r for r in m.ROLES if r not in ("CLIENT", "SUPER_ADMIN"))


class OpeningIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    wall: str = ""                                   # N | E | S | W (or give `edge`)
    offset_mm: float = Field(ge=0, le=50000)
    width_mm: float = Field(ge=300, le=6000)
    height_mm: float = Field(ge=300, le=6000)
    sill_mm: float = Field(0, ge=0, le=5000)
    swing: str | None = None
    label: str | None = Field(None, max_length=40)
    edge: int | None = Field(None, ge=0, le=40)      # M41: wall number (outline edge) — for inner walls of L-shaped rooms and angled walls


class OpeningPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wall: str | None = None
    offset_mm: float | None = Field(None, ge=0, le=50000)
    width_mm: float | None = Field(None, ge=300, le=6000)
    height_mm: float | None = Field(None, ge=300, le=6000)
    sill_mm: float | None = Field(None, ge=0, le=5000)
    swing: str | None = None
    label: str | None = Field(None, max_length=40)
    edge: int | None = Field(None, ge=0, le=40)


def _check(db: Session, rid: str, o: dict, exclude: str | None = None):
    try: L, W, H = _room_dims(db, rid)
    except HTTPException: raise HTTPException(409, "Add the room's Length and Width first — openings are placed along the walls")
    if o["kind"] not in ("DOOR", "WINDOW"): raise HTTPException(422, "kind must be DOOR or WINDOW")
    room = db.get(m.Room, rid)
    if o.get("edge") is None and o["wall"] not in ("N", "E", "S", "W"): raise HTTPException(422, "wall must be N, E, S or W")
    if o.get("edge") is None and shape.is_rect(room.shape):
        wall_len = L if o["wall"] in ("N", "S") else W
        if o["offset_mm"] + o["width_mm"] > wall_len:
            raise HTTPException(422, f"The opening runs past the end of the {o['wall']} wall ({o['offset_mm']:.0f} + {o['width_mm']:.0f} > {wall_len:.0f} mm)")
    try: pos = shape.resolve_opening(L, W, room.shape, {"wall": o["wall"], "offset": o["offset_mm"], "width": o["width_mm"], "edge": o.get("edge")})
    except shape.ShapeError as e: raise HTTPException(422, str(e))
    o["wall"] = pos["wall"]                                              # an opening on wall #n is filed under the side it faces
    if o["kind"] == "DOOR":
        o["sill_mm"] = 0
        if o.get("swing") is None: o["swing"] = "INWARD_RIGHT"
        if o["swing"] not in SWINGS: raise HTTPException(422, f"swing must be one of {', '.join(SWINGS)}")
    else:
        o["swing"] = None
    here = min(shape.ceiling_at(room.ceiling_profile, H, L, W, pos["x0"], pos["y0"]), shape.ceiling_at(room.ceiling_profile, H, L, W, pos["x1"], pos["y1"]))
    if o["sill_mm"] + o["height_mm"] > here: raise HTTPException(422, f"The opening is taller than the room ({o['sill_mm'] + o['height_mm']:.0f} > {here:.0f} mm)")
    seg = geometry.LineString([(pos["x0"], pos["y0"]), (pos["x1"], pos["y1"])])
    for x in room_openings(db, rid):                                      # no two openings on the same stretch of wall
        if x["id"] == exclude or "x0" not in x: continue
        other = geometry.LineString([(x["x0"], x["y0"]), (x["x1"], x["y1"])])
        if seg.distance(other) < 0.5 and seg.intersection(other).length > 0.5:
            raise HTTPException(409, f"Overlaps {x['label']} on the {x['wall']} wall ({x['offset']:.0f}–{x['offset'] + x['width']:.0f} mm)")
    return o


def _latest_check(db: Session, rid: str):
    d = db.query(m.Design).filter_by(room_id=rid).order_by(m.Design.version.desc()).first()
    if not d: return None
    L, W, H = _room_dims(db, rid)
    objs = [geometry.Obj(**{k: v for k, v in x.items() if k in geometry.Obj.__dataclass_fields__}) for x in d.design_json.get("objects", [])]
    v = geometry.validate(_geo(db, rid, L, W, H), objs)
    return {"version": d.version, "valid": v["valid"], "errors": v["errors"], "warnings": v["warnings"]}


def _out(db: Session, rid: str) -> dict:
    from app.routers.api import room_shape
    return {"openings": room_openings(db, rid), "latest_design": _latest_check(db, rid), "shape": room_shape(db, rid)}


@router.get("/rooms/{rid}/openings")
def list_openings(rid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    if not db.get(m.Room, rid): raise HTTPException(404, "Room not found")
    return _out(db, rid)


@router.post("/rooms/{rid}/openings", status_code=201)
def add_opening(rid: str, b: OpeningIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    room = db.get(m.Room, rid)
    if not room: raise HTTPException(404, "Room not found")
    o = _check(db, rid, {**b.model_dump(), "kind": b.kind.upper(), "wall": b.wall.upper(), "swing": b.swing.upper() if b.swing else None})
    n = db.query(m.Opening).filter_by(room_id=rid, kind=o["kind"]).count() + 1
    o["label"] = (o.get("label") or "").strip() or f"{'Door' if o['kind'] == 'DOOR' else 'Window'} {n}"
    db.add(m.Opening(room_id=rid, **o))
    flow.event(db, room.project_id, "SURVEY", f"{room.name}: {o['label']} added on the {o['wall']} wall ({o['width_mm']:.0f} × {o['height_mm']:.0f} mm)", user)
    db.commit(); return _out(db, rid)


@router.patch("/openings/{oid}")
def patch_opening(oid: str, b: OpeningPatch, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    x = db.get(m.Opening, oid)
    if not x: raise HTTPException(404, "Opening not found")
    d = b.model_dump(exclude_unset=True)
    for k in ("wall", "offset_mm", "width_mm", "height_mm", "sill_mm"):
        if k in d and d[k] is None: raise HTTPException(422, f"{k} cannot be empty")
    merged = {"kind": x.kind, "wall": x.wall, "offset_mm": x.offset_mm, "width_mm": x.width_mm, "height_mm": x.height_mm, "sill_mm": x.sill_mm or 0,
              "swing": x.swing, "label": x.label, "edge": x.edge, **{k: (v.upper() if k in ("wall", "swing") and isinstance(v, str) else v) for k, v in d.items()}}
    o = _check(db, x.room_id, merged, exclude=x.id)
    for k, v in o.items():
        if k != "kind": setattr(x, k, v)
    db.commit(); return _out(db, x.room_id)


@router.delete("/openings/{oid}")
def delete_opening(oid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    x = db.get(m.Opening, oid)
    if not x: raise HTTPException(404, "Opening not found")
    rid = x.room_id; room = db.get(m.Room, rid)
    flow.event(db, room.project_id, "SURVEY", f"{room.name}: {x.label or x.kind.lower()} removed", user)
    db.delete(x); db.commit(); return _out(db, rid)
