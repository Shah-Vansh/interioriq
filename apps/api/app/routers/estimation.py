import re
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models import models as m
from app.services import boq as boqlib, quotation_pdf, company as companylib, flow, takeoff as takeofflib, quote_terms
from app.services.cost_engine import D, split_payments

router = APIRouter(tags=["Estimation"])
WRITE = ("ADMIN", "PROJECT_MANAGER", "ESTIMATOR", "INTERIOR_DESIGNER")
READ = WRITE + ("SALES", "PROCUREMENT_MANAGER")                        # not CLIENT (the client portal gets its own scoped view later)
PCT = dict(ge=0, le=100); MONEY = dict(ge=0, le=100_000_000)


class BoqParams(BaseModel):
    overhead_pct: Decimal = Field(default=Decimal(boqlib.DEFAULTS["overhead_pct"]), **PCT)
    margin_pct: Decimal = Field(default=Decimal(boqlib.DEFAULTS["margin_pct"]), **PCT)
    discount_pct: Decimal = Field(default=Decimal(boqlib.DEFAULTS["discount_pct"]), **PCT)
    gst_pct: Decimal = Field(default=Decimal(boqlib.DEFAULTS["gst_pct"]), **PCT)
    labour_pct: Decimal = Field(default=Decimal(boqlib.DEFAULTS["labour_pct"]), **PCT)
    transport: Decimal = Field(default=Decimal(0), **MONEY)
    gst_enabled: bool | None = None          # None → company default (Settings → Company); False → no GST at all
    include_takeoff: bool | None = None      # None → on when take-off rules are mapped (Estimation → Take-off)
    installation: Decimal = Field(default=Decimal(0), **MONEY)


def _money(x) -> str: return f"{D(x):.2f}"
def _qty(x) -> str: return format(D(x).normalize(), "f")


def _out(db: Session, b: m.Boq) -> dict:
    items = db.query(m.BoqItem).filter_by(boq_id=b.id).order_by(m.BoqItem.line_no).all()
    room = db.get(m.Room, b.room_id); project = db.get(m.Project, room.project_id)
    return {"id": b.id, "room_id": b.room_id, "design_version": b.design_version, "version": b.version, "gst_enabled": boqlib.gst_on(b.params), "include_takeoff": b.params.get("include_takeoff") == "true",
            "quotation_no": flow.quote_no(project.project_number, b), "created_at": b.created_at.isoformat(), "params": b.params, "totals": b.totals,
            "warnings": b.warnings or [],
            "items": [{"line": i.line_no, "sku": i.sku, "category": i.category, "description": i.description, "material": i.material, "qty": _qty(i.quantity), "unit": i.unit,
                       "rate": _money(i.rate), "labour": _money(i.labour), "total": _money(i.total), "supplier": i.supplier, "flags": i.flags or []} for i in items]}


@router.get("/estimation/defaults")
def defaults(db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    c = companylib.get(db)
    return {**boqlib.DEFAULTS, "gst_pct": str(c["default_gst_pct"]), "gst_enabled": bool(c["gst_enabled"]), "include_takeoff": takeofflib.configured(db)}


@router.post("/rooms/{rid}/designs/{version}/boq", status_code=201)
def generate_boq(rid: str, version: int, params: BoqParams = BoqParams(), db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    design = db.query(m.Design).filter_by(room_id=rid, version=version).first()
    if not design: raise HTTPException(404, f"Design version {version} not found")
    if not design.is_valid:
        raise HTTPException(409, f"Design v{version} has validation errors. Fix the layout and save a new version before pricing it.")
    objects = design.design_json.get("objects", [])
    if not objects: raise HTTPException(409, f"Design v{version} has no objects to price.")
    cat = db.query(m.FurnitureItem).all()
    by_name = {c.name: c for c in cat if c.is_active is False}; by_name.update({c.name: c for c in cat if c.is_active is not False})   # name fallback prefers items still on sale
    raw = params.model_dump(); inc = raw.pop("include_takeoff")
    p = boqlib.normalize_params(raw, bool(companylib.get(db)["gst_enabled"]))
    inc = takeofflib.configured(db) if inc is None else inc
    p["include_takeoff"] = "true" if inc else "false"
    qd = quote_terms.company_defaults(db); p["payment_schedule"], p["terms"] = qd["schedule"], qd["terms"]      # M26: the quotation keeps its own copy
    tk = takeofflib.for_design(db, rid, objects) if inc else {"lines": [], "skipped": []}
    try:
        items, warnings, totals = boqlib.build(objects, {c.sku: c for c in cat}, by_name, p, {s.id: s for s in db.query(m.Supplier)}, tk["lines"])
        warnings = warnings + [f"Take-off: {x}" for x in tk["skipped"]]
    except boqlib.BoqError as e:
        raise HTTPException(e.status, e.message)
    nxt = (db.query(func.max(m.Boq.version)).filter_by(room_id=rid).scalar() or 0) + 1        # append-only: never edit an old BOQ
    b = m.Boq(room_id=rid, design_id=design.id, design_version=version, version=nxt, params=p, totals={k: _money(v) for k, v in totals.items()},
              warnings=warnings, created_by=user["sub"])
    db.add(b); db.flush()
    for n, it in enumerate(items, 1):
        db.add(m.BoqItem(boq_id=b.id, line_no=n, sku=it["sku"], category=it["category"], description=it["description"], material=it["material"], quantity=it["qty"],
                         unit=it["unit"], rate=it["rate"], labour=it["labour"], total=it["total"], supplier=it["supplier"], flags=it["flags"]))
    b.status = "DRAFT"
    proj = flow.project_of_boq(db, b); b.quote_seq = flow.next_quote_seq(db, proj.id)
    flow.event(db, proj.id, "QUOTATION", f"{flow.quote_no(proj.project_number, b)} drafted from design v{version} (Rs. {b.totals['grand_total']})", user, "BOQ", b.id)
    flow.advance(db, proj, "QUOTATION", user, "first BOQ priced")
    db.commit()
    return _out(db, b)


@router.get("/rooms/{rid}/boqs")
def list_boqs(rid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    room = db.get(m.Room, rid)
    if not room: return []
    number = db.get(m.Project, room.project_id).project_number
    rows = db.query(m.Boq).filter_by(room_id=rid).order_by(m.Boq.version.desc())
    return [{"id": b.id, "version": b.version, "quotation_no": flow.quote_no(number, b), "design_version": b.design_version, "grand_total": b.totals["grand_total"],
             "warnings": len(b.warnings or []), "created_at": b.created_at.isoformat()} for b in rows]


def _get(db: Session, bid: str) -> m.Boq:
    b = db.get(m.Boq, bid)
    if not b: raise HTTPException(404, "BOQ not found")
    return b


@router.get("/boqs/{bid}")
def get_boq(bid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))): return _out(db, _get(db, bid))


# ── M26 payment schedule + terms ──────────────────────────────────────────────
TERMS_EDIT = ("ADMIN", "PROJECT_MANAGER", "ESTIMATOR", "SALES")


def _terms_lock(db: Session, b: m.Boq) -> str | None:
    st = flow.boq_status(b)
    if st == "APPROVED": return "This quotation is approved — its payment schedule and terms are final."
    if st == "SUPERSEDED": return "This quotation was superseded by another version."
    if db.query(m.Payment).filter_by(boq_id=b.id).count(): return "Payments are recorded against this quotation."
    if db.query(m.Invoice).filter_by(boq_id=b.id).count(): return "Invoices are raised against this quotation."
    return None


def _terms_out(db: Session, b: m.Boq, user: dict | None = None) -> dict:
    sched = quote_terms.schedule_of(b.params)
    shares = split_payments(b.totals["grand_total"], [p for _, p in sched])
    lock = _terms_lock(db, b)
    return {"boq_id": b.id, "grand_total": b.totals["grand_total"], "own": isinstance(b.params.get("payment_schedule"), list),
            "schedule": [{"label": l, "pct": p, "amount": _money(s)} for (l, p), s in zip(sched, shares)], "terms": quote_terms.terms_of(b.params),
            "editable": lock is None and (user is None or user.get("role") in TERMS_EDIT + ("SUPER_ADMIN",)), "locked_reason": lock}


@router.get("/boqs/{bid}/terms")
def get_terms(bid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    return _terms_out(db, _get(db, bid), user)


class TermsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schedule: list[dict]
    terms: list[str] = []


@router.put("/boqs/{bid}/terms")
def put_terms(bid: str, body: TermsIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*TERMS_EDIT))):
    b = _get(db, bid); lock = _terms_lock(db, b)
    if lock: raise HTTPException(409, lock)
    try: sched, terms = quote_terms.clean_schedule(body.schedule), quote_terms.clean_terms(body.terms)
    except quote_terms.TermsError as e: raise HTTPException(422, str(e))
    b.params = {**b.params, "payment_schedule": sched, "terms": terms}          # new dict: JSON columns only save on reassignment
    proj = flow.project_of_boq(db, b)
    summary = ", ".join(r["label"] + " " + r["pct"] + "%" for r in sched)
    flow.event(db, proj.id, "QUOTATION", f"{flow.quote_no(proj.project_number, b)}: payment schedule / terms changed ({summary})", user, "BOQ", b.id)
    db.commit(); return _terms_out(db, b, user)


@router.get("/settings/quote-terms")
def get_default_terms(db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    return quote_terms.company_defaults(db)


@router.put("/settings/quote-terms")
def put_default_terms(body: TermsIn, db: Session = Depends(get_db), user: dict = Depends(require_roles("ADMIN", "PROJECT_MANAGER"))):
    try: return quote_terms.save_company_defaults(db, body.schedule, body.terms, user.get("name"))
    except quote_terms.TermsError as e: raise HTTPException(422, str(e))


@router.delete("/settings/quote-terms")
def reset_default_terms(db: Session = Depends(get_db), user: dict = Depends(require_roles("ADMIN", "PROJECT_MANAGER"))):
    return quote_terms.reset_company_defaults(db)


@router.get("/boqs/{bid}/quotation.pdf")
def quotation(bid: str, photos: bool = True, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    from app.services import photos as photolib
    b = _get(db, bid); out = _out(db, b)
    skus = {i["sku"] for i in out["items"] if i.get("sku")}
    thumbs = {it.sku: photolib.path(it.photo) for it in db.query(m.FurnitureItem).filter(m.FurnitureItem.sku.in_(skus), m.FurnitureItem.photo.isnot(None))} if photos and skus else {}
    thumbs = {k: v for k, v in thumbs.items() if v}
    room = db.get(m.Room, b.room_id); project = db.get(m.Project, room.project_id); client = db.get(m.Client, project.client_id) if project.client_id else None
    pdf = quotation_pdf.render(quotation_no=out["quotation_no"], issued=b.created_at, boq=out, items=out["items"],
                               project={"name": project.name, "project_number": project.project_number}, room={"name": room.name},
                               client={"name": client.name, "company": client.company, "address": client.address, "phone": client.phone, "email": client.email, "city": client.city} if client else None,
                               design_version=b.design_version, company=companylib.get(db), photos=thumbs)
    fname = re.sub(r"[^A-Za-z0-9._-]", "-", out["quotation_no"]) + ".pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"', "X-Content-Type-Options": "nosniff"})
