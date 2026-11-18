from datetime import date, datetime, time, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import create_token, current_user, require_roles, verify_password
from app.models import models as m
from app.services import layouts, cad, flow, geometry
from app.services.cost_engine import Line, compute
from app.services.providers import LocalLLMProvider
from app.services.measurements import upsert_measurement

router = APIRouter()

# ── Auth ──────────────────────────────────────────────────────────────────────
class Login(BaseModel):
    email: str; password: str

@router.post("/auth/login", tags=["Auth"])
def login(body: Login, db: Session = Depends(get_db)):
    u = db.query(m.User).filter_by(email=body.email).first()
    if not u or not u.is_active or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    return {"access_token": create_token(u.id, u.role, u.full_name), "token_type": "bearer",
            "user": {"id": u.id, "name": u.full_name, "role": u.role}}

@router.get("/auth/me", tags=["Auth"])
def me(user: dict = Depends(current_user)): return user

# ── Projects & rooms ─────────────────────────────────────────────────────────
class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_number: str = Field(min_length=1, max_length=40); name: str = Field(min_length=1, max_length=120)
    budget: Decimal | None = Field(None, ge=0); client_id: str | None = None
    site_address: str | None = Field(None, max_length=500); target_date: date | None = None
class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=1, max_length=120); budget: Decimal | None = Field(None, ge=0)
    client_id: str | None = None       # send null to unlink the client
    site_address: str | None = Field(None, max_length=500); target_date: date | None = None
    archived: bool | None = None
    status: str | None = None          # manual correction (PM/Admin); logged on the timeline
class RoomIn(BaseModel):
    name: str; room_type: str

@router.post("/projects", tags=["Projects"], status_code=201)
def create_project(b: ProjectIn, db: Session = Depends(get_db), user: dict = Depends(require_roles("ADMIN", "PROJECT_MANAGER", "SALES"))):
    if db.query(m.Project).filter_by(project_number=b.project_number).first():
        raise HTTPException(409, f"Project number {b.project_number} already exists")
    if b.client_id and not db.get(m.Client, b.client_id): raise HTTPException(404, "Client not found")
    data = b.model_dump(); data["target_date"] = _as_dt(data["target_date"])
    p = m.Project(**data, status="LEAD", progress=0); db.add(p); db.flush()
    from app.services import access
    access.add_member(db, p.id, user.get("sub"), user)                         # whoever creates it is on its team
    flow.event(db, p.id, "CREATED", f"Project {p.project_number} created", user); db.commit()
    return _project(p, db.get(m.Client, p.client_id) if p.client_id else None)

def _as_dt(d):
    return datetime.combine(d, time(12), tzinfo=timezone.utc) if d else None

def _project(p: m.Project, c: m.Client | None) -> dict:
    return {"id": p.id, "project_number": p.project_number, "name": p.name, "status": p.status or "LEAD", "budget": None if p.budget is None else f"{p.budget:.2f}",
            "client_id": p.client_id, "client_name": c.name if c else None, "progress": p.progress or 0, "archived": bool(p.archived),
            "site_address": p.site_address, "target_date": p.target_date.date().isoformat() if p.target_date else None,
            "created_at": p.created_at.isoformat() if p.created_at else None, "completed_at": p.completed_at.isoformat() if p.completed_at else None}

def visible_projects(db: Session, user: dict):
    """CLIENT users only ever see their own client's projects; staff see all — or only their teams' projects when
    'Limit staff to their projects' is on (services/access)."""
    from app.services import access
    return access.scope(db.query(m.Project), m.Project.id, db, user)

@router.get("/projects", tags=["Projects"])
def list_projects(view: str = "all", db: Session = Depends(get_db), user: dict = Depends(current_user)):
    """view: all | active (not archived, not completed) | completed | archived"""
    clients = {c.id: c for c in db.query(m.Client)}
    rows = visible_projects(db, user).order_by(m.Project.project_number).all()
    if view == "active": rows = [p for p in rows if not p.archived and p.status != "COMPLETED"]
    elif view == "completed": rows = [p for p in rows if not p.archived and p.status == "COMPLETED"]
    elif view == "archived": rows = [p for p in rows if p.archived]
    return [_project(p, clients.get(p.client_id)) for p in rows]

@router.patch("/projects/{pid}", tags=["Projects"])
def update_project(pid: str, b: ProjectPatch, db: Session = Depends(get_db), user: dict = Depends(require_roles("ADMIN", "PROJECT_MANAGER", "SALES"))):
    p = db.get(m.Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    d = b.model_dump(exclude_unset=True)
    if d.get("client_id") and not db.get(m.Client, d["client_id"]): raise HTTPException(404, "Client not found")
    for k in ("name", "archived", "status"):
        if k in d and d[k] is None: raise HTTPException(422, f"{k} cannot be empty")
    if "status" in d:
        if user.get("role") not in ("SUPER_ADMIN", "ADMIN", "PROJECT_MANAGER"): raise HTTPException(403, "Only an admin or project manager can change the status by hand")
        if d["status"] not in m.PROJECT_STAGES: raise HTTPException(422, f"status must be one of {', '.join(m.PROJECT_STAGES)}")
        if d["status"] == "COMPLETED" and not db.query(m.Handover).filter_by(project_id=pid).first(): raise HTTPException(409, "A project is completed by recording its handover")
        if d["status"] != (p.status or "LEAD"):
            flow.event(db, pid, "STATUS", f"Status {p.status or 'LEAD'} → {d['status']} (set by hand)", user)
            p.progress = round(100 * flow.stage_index(d["status"]) / (len(m.PROJECT_STAGES) - 1))
    if "archived" in d and d["archived"] != bool(p.archived): flow.event(db, pid, "ARCHIVE", "Project archived" if d["archived"] else "Project restored from archive", user)
    if "target_date" in d: d["target_date"] = _as_dt(d["target_date"])
    for k, v in d.items(): setattr(p, k, v)
    db.commit()
    return _project(p, db.get(m.Client, p.client_id) if p.client_id else None)

@router.post("/projects/{pid}/rooms", tags=["Survey"], status_code=201)
def create_room(pid: str, b: RoomIn, db: Session = Depends(get_db), user: dict = Depends(require_roles("ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "INTERIOR_DESIGNER"))):
    p = db.get(m.Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    r = m.Room(project_id=pid, **b.model_dump()); db.add(r)
    flow.event(db, pid, "SURVEY", f"Room '{b.name}' added", user); flow.advance(db, p, "SURVEY", user, "first room surveyed"); db.commit()
    return {"id": r.id, "name": r.name}

@router.get("/projects/{pid}/rooms", tags=["Survey"])
def list_rooms(pid: str, db: Session = Depends(get_db), user: dict = Depends(current_user)):
    return [{"id": r.id, "name": r.name, "room_type": r.room_type} for r in db.query(m.Room).filter_by(project_id=pid)]

@router.get("/rooms/{rid}/measurements", tags=["Survey"])
def list_measurements(rid: str, db: Session = Depends(get_db), user: dict = Depends(current_user)):
    rows = db.query(m.Measurement).filter_by(room_id=rid).order_by(m.Measurement.label)
    return [{"label": x.label, "value": x.value, "unit": x.unit, "source": x.source,
             "confidence": x.confidence, "verified": x.verified} for x in rows]

class MeasurementIn(BaseModel):
    label: str; value: float = Field(gt=0); unit: str = "mm"
    source: str; confidence: float = Field(default=100, ge=0, le=100)

@router.put("/rooms/{rid}/measurements", tags=["Survey"])
def put_measurement(rid: str, b: MeasurementIn, db: Session = Depends(get_db), user: dict = Depends(require_roles("ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "INTERIOR_DESIGNER"))):
    if not db.get(m.Room, rid): raise HTTPException(404, "Room not found")
    try:
        rec, applied = upsert_measurement(db, rid, b.label, b.value, b.unit, b.source, b.confidence)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"applied": applied, "current": rec,
            "reason": None if applied else "Rejected: existing value has equal or higher source priority"}

def room_openings(db: Session, rid: str) -> list[dict]:
    return [{"id": o.id, "kind": o.kind, "wall": o.wall, "offset": o.offset_mm, "width": o.width_mm, "height": o.height_mm, "sill": o.sill_mm or 0,
             "swing": o.swing, "label": o.label or (f"{'Door' if o.kind == 'DOOR' else 'Window'} {o.wall}")}
            for o in db.query(m.Opening).filter_by(room_id=rid).order_by(m.Opening.created_at)]

def _geo(db: Session, rid: str, L, W, H) -> geometry.Room:
    return geometry.Room(L, W, H, openings=room_openings(db, rid))

def _room_dims(db: Session, rid: str):
    ms = {x.label.lower(): x for x in db.query(m.Measurement).filter_by(room_id=rid)}
    get = lambda k: next((v.value for kk, v in ms.items() if k in kk), None)
    L, W, H = get("length"), get("width"), get("ceiling") or 2750
    if not L or not W: raise HTTPException(409, "Room needs length and width measurements first")
    return L, W, H

# ── Design generation + append-only versioning ───────────────────────────────
class LayoutOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skip: list[str] = Field(default_factory=list, max_length=20)          # optional items to leave out (layouts.OPTIONAL slots)
    kitchen_shape: str = "AUTO"                                            # AUTO | STRAIGHT | L | PARALLEL | U
    seats: int | None = Field(default=None, ge=1, le=12)                   # dining: how many people
    tier: str = "BALANCED"                                                 # BUDGET | BALANCED | PREMIUM
    styles: list[str] = Field(default_factory=list, max_length=6)          # style picked in the UI (else the words in the brief)

class GenerateIn(BaseModel):
    prompt: str = Field(default="", max_length=2000); catalogue_filter_in_stock: bool = True
    room_type: str | None = None                                            # lay the room out as another type (e.g. an OTHER room as a study)
    options: LayoutOptions = LayoutOptions()

@router.get("/layouts/meta", tags=["Design"])
def layouts_meta(user: dict = Depends(current_user)):
    """Room types the generator can lay out, the items each needs/offers, and kitchen shapes — the UI builds its options from this."""
    return {"kinds": list(layouts.KINDS), "room_kind": layouts.ROOM_KIND, "kitchen_shapes": list(layouts.SHAPES), "tiers": list(layouts.TIERS),
            "styles": ["modern", "minimal", "luxury", "scandinavian", "traditional", "industrial"],
            "required": {k: [{"slot": s, "label": layouts.LABEL[s], "categories": list(layouts.SLOTS[s][:1])} for s in v] for k, v in layouts.REQUIRED.items()},
            "optional": {k: [{"slot": s, "label": layouts.LABEL[s], "categories": list(layouts.SLOTS[s][:1])} for s in v] for k, v in layouts.OPTIONAL.items()}}

@router.post("/rooms/{rid}/designs/generate", tags=["Design"])
def generate(rid: str, b: GenerateIn, db: Session = Depends(get_db), user: dict = Depends(require_roles("ADMIN", "PROJECT_MANAGER", "INTERIOR_DESIGNER"))):
    L, W, H = _room_dims(db, rid)
    req = LocalLLMProvider().extract_requirements(b.prompt) if b.prompt else {"style": "modern", "budget": None, "priority": []}
    room = db.get(m.Room, rid)
    as_dict = lambda f: dict(sku=f.sku, name=f.name, category=f.category, length_mm=f.length_mm, width_mm=f.width_mm, height_mm=f.height_mm, price=f.price,
                             mount_mm=f.mount_mm, style=f.style)
    everything = [as_dict(f) for f in _placeable(db).order_by(m.FurnitureItem.created_at)]
    cat = [as_dict(f) for f in _placeable(db).filter(m.FurnitureItem.stock > 0).order_by(m.FurnitureItem.created_at)] if b.catalogue_filter_in_stock else everything
    if b.options.skip and (bad := [s for s in b.options.skip if s not in layouts.SLOTS]): raise HTTPException(422, f"Unknown item(s) to skip: {', '.join(bad)}")
    try:
        grand = lambda objs: compute([Line(Decimal(1), Decimal(str(o.price))) for o in objs])["grand_total"]
        out = layouts.plan(_geo(db, rid, L, W, H), b.room_type or room.room_type, cat, b.options.model_dump(), all_items=everything,
                           styles=b.options.styles or req.get("styles") or [], budget=req.get("budget"), cost=grand)
    except layouts.LayoutError as e:
        raise HTTPException(422, str(e))
    objs = out["objects"]
    check = geometry.validate(_geo(db, rid, L, W, H), objs)
    lines = [Line(Decimal(1), Decimal(str(o.price))) for o in objs]
    cost = compute(lines)
    return {"requirements": req, "kind": out["kind"], "notes": out["notes"], "missing": out["missing"], "objects": [o.__dict__ for o in objs], "validation": check,
            "cost": {k: str(v) for k, v in cost.items()},
            "over_budget": bool(req.get("budget") and cost["grand_total"] > Decimal(str(req["budget"]))),
            "budget_gap": str(abs(cost["grand_total"] - Decimal(str(req["budget"]))).quantize(Decimal("0.01"))) if req.get("budget") else None}   # the browser never subtracts money

class ObjectIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=60)
    x: float; y: float
    length: float = Field(gt=0, le=20000)
    width: float = Field(gt=0, le=20000)
    height: float = Field(default=0, ge=0, le=10000)
    price: float = Field(default=0, ge=0)
    sku: str = Field(default="", max_length=64)
    z: float = Field(default=0, ge=0, le=5000)            # underside above the floor (wall cabinets); old designs have none → 0

class DesignBody(BaseModel):
    objects: list[ObjectIn] = Field(max_length=200)

    @field_validator("objects")
    @classmethod
    def unique_ids(cls, v):
        ids = [o.id for o in v]
        if len(set(ids)) != len(ids): raise ValueError("Object ids must be unique")
        return v

class SaveDesign(DesignBody):
    tier: str = "Balanced"

def _to_objs(items: list[ObjectIn]) -> list[geometry.Obj]:
    return [geometry.Obj(**o.model_dump()) for o in items]

@router.post("/rooms/{rid}/designs/validate", tags=["Design"])
def validate_design(rid: str, b: DesignBody, db: Session = Depends(get_db), user: dict = Depends(current_user)):
    """Authoritative validation without saving. The 3D editor calls this instead of re-implementing geometry in the browser."""
    L, W, H = _room_dims(db, rid)
    return geometry.validate(_geo(db, rid, L, W, H), _to_objs(b.objects))

@router.post("/rooms/{rid}/designs", tags=["Design"], status_code=201)
def save_design(rid: str, b: SaveDesign, db: Session = Depends(get_db), user: dict = Depends(require_roles("ADMIN", "PROJECT_MANAGER", "INTERIOR_DESIGNER"))):
    L, W, H = _room_dims(db, rid)
    check = geometry.validate(_geo(db, rid, L, W, H), _to_objs(b.objects))
    nxt = (db.query(func.max(m.Design.version)).filter_by(room_id=rid).scalar() or 0) + 1   # never overwrite history
    d = m.Design(room_id=rid, version=nxt, tier=b.tier, design_json={"objects": [o.model_dump() for o in b.objects], "validation": check},
                 is_valid=check["valid"], created_by=user["sub"])
    db.add(d)
    room = db.get(m.Room, rid); proj = db.get(m.Project, room.project_id)
    flow.event(db, proj.id, "DESIGN", f"{room.name}: design v{nxt} saved ({'valid' if check['valid'] else 'has errors'})", user)
    flow.advance(db, proj, "DESIGN", user, "first design saved"); db.commit()
    return {"id": d.id, "version": d.version, "is_valid": d.is_valid, "validation": check}

def _design_out(d: m.Design) -> dict:
    return {"id": d.id, "version": d.version, "tier": d.tier, "is_valid": d.is_valid, "status": d.approval_status,
            "objects": d.design_json["objects"], "validation": d.design_json.get("validation")}

@router.get("/rooms/{rid}/designs/latest", tags=["Design"])
def latest_design(rid: str, db: Session = Depends(get_db), user: dict = Depends(current_user)):
    d = db.query(m.Design).filter_by(room_id=rid).order_by(m.Design.version.desc()).first()
    if not d: raise HTTPException(404, "No saved design for this room")
    return _design_out(d)

@router.get("/rooms/{rid}/designs/{version}", tags=["Design"])
def get_design(rid: str, version: int, db: Session = Depends(get_db), user: dict = Depends(current_user)):
    d = db.query(m.Design).filter_by(room_id=rid, version=version).first()
    if not d: raise HTTPException(404, f"Version {version} not found")
    return _design_out(d)

def _placeable(db: Session):
    """Items the designer / 3D editor may place: active furniture that has a size (archived items and materials/lighting/hardware are not placed)."""
    F = m.FurnitureItem
    return db.query(F).filter(or_(F.kind.is_(None), F.kind == "FURNITURE"), F.is_active.isnot(False),
                              F.length_mm > 0, F.width_mm > 0, F.height_mm > 0)

@router.get("/catalogue/furniture", tags=["Catalogue"])
def furniture_list(in_stock: bool = False, db: Session = Depends(get_db), user: dict = Depends(current_user)):
    q = _placeable(db)
    if in_stock: q = q.filter(m.FurnitureItem.stock > 0)
    return [{"sku": f.sku, "name": f.name, "category": f.category, "length_mm": f.length_mm, "width_mm": f.width_mm,
             "height_mm": f.height_mm, "price": float(f.price), "stock": f.stock, "mount_mm": f.mount_mm, "style": f.style} for f in q.order_by(m.FurnitureItem.category)]

@router.get("/rooms/{rid}/designs", tags=["Design"])
def design_history(rid: str, db: Session = Depends(get_db), user: dict = Depends(current_user)):
    rows = db.query(m.Design).filter_by(room_id=rid).order_by(m.Design.version)
    return [{"id": d.id, "version": d.version, "tier": d.tier, "is_valid": d.is_valid, "status": d.approval_status} for d in rows]

# ── BOQ / cost (Decimal) ─────────────────────────────────────────────────────
class LineIn(BaseModel):
    qty: Decimal; rate: Decimal; labour: Decimal = Decimal(0)
class CostIn(BaseModel):
    lines: list[LineIn]
    overhead_pct: Decimal = Decimal(8); margin_pct: Decimal = Decimal(18)
    discount_pct: Decimal = Decimal(5); gst_pct: Decimal = Decimal(18)

@router.post("/boq/compute", tags=["Estimation"])
def boq(b: CostIn, user: dict = Depends(current_user)):
    r = compute([Line(l.qty, l.rate, l.labour) for l in b.lines], b.overhead_pct, b.margin_pct, b.discount_pct, b.gst_pct)
    return {k: str(v) for k, v in r.items()}

# ── CAD (DXF) generated from Room Model + Design Model ───────────────────────
def _latest_objs(db: Session, rid: str):
    d = db.query(m.Design).filter_by(room_id=rid).order_by(m.Design.version.desc()).first()
    return [] if not d else d.design_json["objects"]

@router.get("/rooms/{rid}/cad/{kind}", tags=["CAD"])
def cad_file(rid: str, kind: str, db: Session = Depends(get_db), user: dict = Depends(current_user)):
    r = db.get(m.Room, rid)
    if not r: raise HTTPException(404, "Room not found")
    L, W, H = _room_dims(db, rid); objs = _latest_objs(db, rid)
    ops = room_openings(db, rid)
    if kind == "floor-plan": data = cad.floor_plan(r.name, L, W, ops)
    elif kind == "furniture": data = cad.furniture_layout(r.name, L, W, objs, ops)
    elif kind == "elevation-north":    # only what stands against the north wall (previously every object was drawn on it)
        from app.services import mep
        nw = next(w for w in mep.elevations(L, W, H, objs, ops) if w["wall"] == "NORTH"); data = cad.elevation(r.name, L, H, nw["items"], nw["openings"])
    else: raise HTTPException(404, "Unknown drawing type")
    return Response(data, media_type="application/dxf", headers={"Content-Disposition": f'attachment; filename="{kind}.dxf"'})

@router.get("/health", tags=["System"])
def health(): return {"status": "ok"}
