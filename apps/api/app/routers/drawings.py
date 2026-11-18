"""Design drawings from a SAVED design version: ceiling + electrical layouts, wall elevations, DXF; and a no-save BOQ cost preview."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models import models as m
from app.routers.api import _room_dims, room_openings
from app.routers.estimation import BoqParams, READ as EST_READ, _money
from app.services import boq as boqlib, cad, mep

router = APIRouter(tags=["Drawings"])
STAFF = tuple(r for r in m.ROLES if r not in ("CLIENT", "SUPER_ADMIN"))


def _design(db: Session, rid: str, version: int | None):
    q = db.query(m.Design).filter_by(room_id=rid)
    d = q.filter_by(version=version).first() if version else q.order_by(m.Design.version.desc()).first()
    if not d: raise HTTPException(404, "No saved design for this room" if not version else f"Version {version} not found")
    L, W, H = _room_dims(db, rid)
    return d, L, W, H, d.design_json.get("objects", [])


@router.get("/rooms/{rid}/drawings/{kind}")
def drawing(rid: str, kind: str, version: int | None = None, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    d, L, W, H, objs = _design(db, rid, version)
    ops = room_openings(db, rid)
    if kind == "ceiling": data = mep.ceiling(L, W, H, objs)
    elif kind == "electrical": data = mep.electrical(L, W, H, objs, ops)
    elif kind == "elevations": data = {"walls": mep.elevations(L, W, H, objs, ops)}
    elif kind == "plan": data = {"room": {"L": L, "W": W, "H": H}, "objects": objs, "validation": d.design_json.get("validation")}
    else: raise HTTPException(404, "Unknown drawing (plan, ceiling, electrical, elevations)")
    return {"version": d.version, "is_valid": d.is_valid, "openings": ops, **data}


@router.get("/rooms/{rid}/drawings/{kind}/dxf")
def drawing_dxf(rid: str, kind: str, version: int | None = None, wall: str = "NORTH", db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    d, L, W, H, objs = _design(db, rid, version); room = db.get(m.Room, rid)
    if kind in ("ceiling", "electrical"):
        ops = room_openings(db, rid)
        data = mep.ceiling(L, W, H, objs) if kind == "ceiling" else mep.electrical(L, W, H, objs, ops); body = mep.dxf(kind, data, L, W, ops)
    elif kind == "elevation":
        w = next((x for x in mep.elevations(L, W, H, objs, room_openings(db, rid)) if x["wall"] == wall.upper()), None)
        if not w: raise HTTPException(422, "wall must be NORTH, EAST, SOUTH or WEST")
        body = cad.elevation(room.name, w["length"], H, w["items"], w["openings"])
    elif kind == "plan": body = cad.furniture_layout(room.name, L, W, objs, room_openings(db, rid))
    else: raise HTTPException(404, "Unknown drawing")
    name = f"{room.name}-{kind}{'-' + wall.lower() if kind == 'elevation' else ''}-v{d.version}.dxf".replace(" ", "_")
    return Response(body, media_type="application/dxf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/boqs/{bid}/preview")
def preview(bid: str, params: BoqParams, db: Session = Depends(get_db), user: dict = Depends(require_roles(*EST_READ))):
    """What-if costing: re-price the BOQ's design with other rates WITHOUT saving anything (the saved BOQ stays frozen)."""
    b = db.get(m.Boq, bid)
    if not b: raise HTTPException(404, "BOQ not found")
    design = db.get(m.Design, b.design_id)
    cat = db.query(m.FurnitureItem).all()
    by_name = {c.name: c for c in cat if c.is_active is False}; by_name.update({c.name: c for c in cat if c.is_active is not False})
    from app.services import company as companylib
    raw = params.model_dump(); inc = raw.pop("include_takeoff")
    p = boqlib.normalize_params(raw, bool(companylib.get(db)["gst_enabled"]))
    from app.services import takeoff as takeofflib
    inc = (b.params.get("include_takeoff") == "true") if inc is None else inc
    tk = takeofflib.for_design(db, b.room_id, design.design_json.get("objects", [])) if inc else {"lines": [], "skipped": []}
    try:
        items, warnings, totals = boqlib.build(design.design_json.get("objects", []), {c.sku: c for c in cat}, by_name, p, {s.id: s for s in db.query(m.Supplier)}, tk["lines"])
    except boqlib.BoqError as e:
        raise HTTPException(e.status, e.message)
    from app.services.cost_engine import D
    return {"params": p, "totals": {k: _money(v) for k, v in totals.items()}, "saved_totals": b.totals,
            "delta": {k: _money(D(v) - D(b.totals.get(k, 0))) for k, v in totals.items()}, "warnings": warnings}
