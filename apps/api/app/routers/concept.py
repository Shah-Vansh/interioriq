"""Design concept endpoints: the style catalogue, apply a style to one room or the whole home ('Design my home'), edit a room's concept.
Every change saves a NEW design version (objects copied, history kept)."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models import models as m
from app.services import concept, flow, homeplan, layouts

router = APIRouter(tags=["Design concept"])
STAFF = tuple(r for r in m.ROLES if r not in ("CLIENT",))
EDIT = ("ADMIN", "PROJECT_MANAGER", "INTERIOR_DESIGNER")


@router.get("/concept/styles")
def styles(user: dict = Depends(require_roles(*STAFF))):
    return {"styles": {k: {"label": v["label"], "idea": v["idea"], "palette": {p: v[p] for p in concept.PALETTE_KEYS}, "floor": concept.FLOORS[v["floor"][0]]}
                       for k, v in concept.STYLES.items()},
            "accent_types": concept.ACCENT_TYPES, "ceilings": concept.CEILINGS, "floors": concept.FLOORS}


def _new_version(db: Session, room: m.Room, prev: m.Design, finishes: dict, user: dict, what: str) -> m.Design:
    nxt = (db.query(func.max(m.Design.version)).filter_by(room_id=room.id).scalar() or 0) + 1
    dj = {**prev.design_json, "finishes": finishes}
    d = m.Design(room_id=room.id, version=nxt, tier=prev.tier, design_json=dj, is_valid=prev.is_valid, created_by=user.get("sub"))
    db.add(d); flow.event(db, room.project_id, "DESIGN", f"{room.name}: {what} (design v{nxt})", user)
    return d


def _room_ctx(db: Session, room: m.Room):
    from app.routers.api import room_openings
    d = homeplan.dims(db, room)
    if not d: raise HTTPException(409, f"{room.name} needs length and width measurements first")
    prev = db.query(m.Design).filter_by(room_id=room.id).order_by(m.Design.version.desc()).first()
    return d, prev, room_openings(db, room.id)


def _out(room: m.Room, d: m.Design) -> dict:
    return {"room_id": room.id, "room": room.name, "version": d.version, "finishes": d.design_json.get("finishes")}


class ApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    style: str
    overrides: dict = Field(default_factory=dict)


@router.post("/rooms/{rid}/concept", status_code=201)
def apply_room(rid: str, b: ApplyIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*EDIT))):
    room = db.get(m.Room, rid)
    if not room: raise HTTPException(404, "Room not found")
    (L, W, H), prev, ops = _room_ctx(db, room)
    if not prev: raise HTTPException(409, f"{room.name} has no saved layout yet — generate one in AI Designer first (or use 'Design my home')")
    try:
        f = concept.concept(room.room_type, L, W, H, prev.design_json.get("objects", []), ops, b.style)
        if b.overrides: f = concept.apply_overrides(f, b.overrides, L, W, H)
    except ValueError as e: raise HTTPException(422, str(e))
    d = _new_version(db, room, prev, f, user, f"{concept.STYLES[b.style]['label']} design concept applied"); db.commit()
    return _out(room, d)


class EditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overrides: dict


@router.put("/rooms/{rid}/concept")
def edit_room(rid: str, b: EditIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*EDIT))):
    room = db.get(m.Room, rid)
    if not room: raise HTTPException(404, "Room not found")
    (L, W, H), prev, _ = _room_ctx(db, room)
    if not prev or not prev.design_json.get("finishes"): raise HTTPException(409, f"{room.name} has no design concept yet — apply a style first")
    try: f = concept.apply_overrides(prev.design_json["finishes"], b.overrides, L, W, H)
    except ValueError as e: raise HTTPException(422, str(e))
    d = _new_version(db, room, prev, f, user, "design concept changed: " + ", ".join(sorted(b.overrides))); db.commit()
    return _out(room, d)


class HomeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    style: str
    generate_missing: bool = True          # lay out rooms that have no design yet (from their room type) before applying the style
    catalogue_filter_in_stock: bool = False


@router.post("/projects/{pid}/concept", status_code=201)
def design_home(pid: str, b: HomeIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*EDIT))):
    """'Design my home': every room gets a layout (if missing) and the style's concept; one new version per room."""
    from app.routers import api as r_api
    p = db.get(m.Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    if b.style not in concept.STYLES: raise HTTPException(422, f"style must be one of {', '.join(concept.STYLES)}")
    done, skipped = [], []
    for room in db.query(m.Room).filter_by(project_id=pid).order_by(m.Room.name):
        d = homeplan.dims(db, room)
        if not d: skipped.append({"room": room.name, "reason": "no length / width measured"}); continue
        prev = db.query(m.Design).filter_by(room_id=room.id).order_by(m.Design.version.desc()).first()
        if not prev and b.generate_missing:
            if not layouts.kind_of(room.room_type) and (room.room_type or "").upper() not in layouts.KINDS:
                skipped.append({"room": room.name, "reason": f"no automatic layout for room type {room.room_type} — lay it out in the 3D editor"}); continue
            try:
                g = r_api.generate(room.id, r_api.GenerateIn(catalogue_filter_in_stock=b.catalogue_filter_in_stock, options=r_api.LayoutOptions(styles=[b.style] if b.style in ("modern", "minimal", "luxury", "scandinavian", "traditional", "industrial") else [])), db, user)
            except HTTPException as e: skipped.append({"room": room.name, "reason": str(e.detail)}); continue
            if not g["objects"]: skipped.append({"room": room.name, "reason": "nothing could be placed: " + "; ".join(x["label"] for x in g["missing"]) + " missing from the catalogue" if g["missing"] else "nothing fits"}); continue
            r_api.save_design(room.id, r_api.SaveDesign(objects=[r_api.ObjectIn(**o) for o in g["objects"]], tier="Balanced"), db, user)
            prev = db.query(m.Design).filter_by(room_id=room.id).order_by(m.Design.version.desc()).first()
        if not prev: skipped.append({"room": room.name, "reason": "no saved layout"}); continue
        from app.routers.api import room_openings
        f = concept.concept(room.room_type, d[0], d[1], d[2], prev.design_json.get("objects", []), room_openings(db, room.id), b.style)
        nv = _new_version(db, room, prev, f, user, f"{concept.STYLES[b.style]['label']} design concept applied")
        db.flush(); done.append({"room": room.name, "room_id": room.id, "version": nv.version, "items": len(prev.design_json.get("objects", [])),
                                 "feature_wall": concept.ACCENT_TYPES[f["accent"]["type"]] if f.get("accent") else None, "ceiling": f["ceiling"]["label"]})
    row = db.get(m.CompanySetting, f"concept:{pid}")
    val = {"style": b.style, "label": concept.STYLES[b.style]["label"]}
    if row: row.value = val
    else: db.add(m.CompanySetting(key=f"concept:{pid}", value=val, updated_by=user.get("name")))
    flow.event(db, pid, "DESIGN", f"Whole-home design concept: {concept.STYLES[b.style]['label']} ({len(done)} room(s))", user)
    db.commit()
    return {"style": b.style, "label": concept.STYLES[b.style]["label"], "rooms": done, "skipped": skipped}


@router.get("/projects/{pid}/concept")
def home_concept(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    if not db.get(m.Project, pid): raise HTTPException(404, "Project not found")
    row = db.get(m.CompanySetting, f"concept:{pid}")
    rooms = []
    for room in db.query(m.Room).filter_by(project_id=pid).order_by(m.Room.name):
        d = db.query(m.Design).filter_by(room_id=room.id).order_by(m.Design.version.desc()).first()
        rooms.append({"room_id": room.id, "room": room.name, "room_type": room.room_type, "version": d.version if d else None,
                      "finishes": d.design_json.get("finishes") if d else None})
    return {"style": (row.value or {}).get("style") if row else None, "rooms": rooms}


@router.get("/projects/{pid}/presentation.pdf")
def presentation(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    """The design presentation for the client: cover, concept, home plan, one page per room (plan, finishes, elevation, furniture, 3D views)."""
    from app.services import company as companylib, presentation as pres
    p = db.get(m.Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    body = pres.build(db, pid, companylib.get(db).get("name") or "InteriorIQ")
    return Response(body, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="design-presentation-{p.project_number}.pdf"'})


@router.get("/portal/projects/{pid}/presentation.pdf")
def portal_presentation(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles("CLIENT"))):
    from app.services import company as companylib, presentation as pres
    p = db.get(m.Project, pid)
    if not p or not user.get("client_id") or p.client_id != user["client_id"]: raise HTTPException(404, "Project not found")
    body = pres.build(db, pid, companylib.get(db).get("name") or "InteriorIQ")
    return Response(body, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="design-presentation-{p.project_number}.pdf"'})


class UnitsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    units: str = Field(pattern="^(ftin|mm)$")


@router.get("/settings/drawing-units")
def get_units(db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    row = db.get(m.CompanySetting, "drawing_units")
    return {"units": (row.value if row and row.value in ("ftin", "mm") else "ftin")}


@router.put("/settings/drawing-units")
def set_units(body: UnitsIn, db: Session = Depends(get_db), user: dict = Depends(require_roles("ADMIN", "PROJECT_MANAGER"))):
    """How working drawings print dimensions: ftin = feet-inches (site practice, default) or mm."""
    row = db.get(m.CompanySetting, "drawing_units")
    if row: row.value = body.units; row.updated_by = user.get("sub")
    else: db.add(m.CompanySetting(key="drawing_units", value=body.units, updated_by=user.get("sub")))
    db.commit(); return {"units": body.units}


@router.get("/projects/{pid}/drawing-set.pdf")
def drawing_set(pid: str, room_id: str | None = None, units: str | None = None, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    """Working drawings for the site team (A3, title block, feet-inches): light detail, room plan + feature-wall elevation + bed details,
    wardrobe elevation + internal detail, kitchen elevations + counter plan, 3D views. room_id = one room only; units = ftin | mm (else the company setting)."""
    from app.services import drawingset
    p = db.get(m.Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    room = None
    if room_id:
        room = db.get(m.Room, room_id)
        if not room or room.project_id != pid: raise HTTPException(404, "Room not found in this project")
    if units not in (None, "ftin", "mm"): raise HTTPException(422, "units must be ftin or mm")
    body = drawingset.build(db, pid, room_id, units=units)
    name = f"working-drawings-{p.project_number}" + (f"-{room.name.replace(' ', '-').lower()}" if room else "")
    return Response(body, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
