"""M9 Catalogue: furniture / materials / lighting / hardware items and suppliers. Prices and stock change only through append-only ledgers."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import current_user, require_roles
from app.models import models as m
from app.services import catalogue as cat, flow, followups as fups, supplier_prices as spl
from app.services.phone import PhoneError, normalize_phone

router = APIRouter(tags=["Catalogue"])
WRITE = ("ADMIN", "PROJECT_MANAGER", "PROCUREMENT_MANAGER")                    # items, prices, suppliers
STOCK = WRITE + ("INVENTORY_MANAGER",)                                          # stock in/out
COST_VIEW = WRITE + ("ESTIMATOR",)                                              # who may see purchase costs and margins
READ = STOCK + ("INTERIOR_DESIGNER", "ESTIMATOR", "SALES", "SITE_ENGINEER", "MANUFACTURING_MANAGER", "INSTALLATION_MANAGER", "QC_MANAGER")  # not CLIENT


def _fail(e: cat.CatalogueError): raise HTTPException(e.status, e.detail)


def _422(msg: str): raise HTTPException(422, [{"loc": ["body"], "msg": msg, "type": "value_error"}])


def _item(db: Session, iid: str) -> m.FurnitureItem:
    it = db.get(m.FurnitureItem, iid)
    if not it: raise HTTPException(404, "Catalogue item not found")
    return it


def sees_cost(user: dict) -> bool: return user.get("role") in COST_VIEW + ("SUPER_ADMIN",)


def _out(db: Session, it: m.FurnitureItem, user: dict | None = None) -> dict:
    return cat.item_out(it, db.get(m.Supplier, it.supplier_id) if it.supplier_id else None, show_cost=sees_cost(user or {"role": "SUPER_ADMIN"}))


@router.get("/catalogue/meta")
def meta(db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    cats: dict[str, list[str]] = {k: [] for k in m.CATALOGUE_KINDS}
    for kind, c in db.query(func.coalesce(m.FurnitureItem.kind, "FURNITURE"), m.FurnitureItem.category).distinct():
        if kind in cats and c not in cats[kind]: cats[kind].append(c)
    return {"kinds": m.CATALOGUE_KINDS, "units": m.CATALOGUE_UNITS, "categories": {k: sorted(v) for k, v in cats.items()}, "csv_columns": cat.COLUMNS}


def _query(db: Session, kind, q, category, supplier_id, status, stock):
    qry = db.query(m.FurnitureItem)
    if kind:
        qry = qry.filter(or_(m.FurnitureItem.kind == kind, m.FurnitureItem.kind.is_(None)) if kind == "FURNITURE" else m.FurnitureItem.kind == kind)
    if status == "active": qry = qry.filter(m.FurnitureItem.is_active.isnot(False))
    elif status == "archived": qry = qry.filter(m.FurnitureItem.is_active.is_(False))
    if category: qry = qry.filter(m.FurnitureItem.category == category)
    if supplier_id: qry = qry.filter(m.FurnitureItem.supplier_id == supplier_id)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        qry = qry.filter(or_(func.lower(m.FurnitureItem.sku).like(like), func.lower(m.FurnitureItem.name).like(like),
                             func.lower(m.FurnitureItem.material).like(like), func.lower(m.FurnitureItem.category).like(like)))
    items = qry.order_by(m.FurnitureItem.category, m.FurnitureItem.name).all()
    if stock in ("LOW", "OUT"): items = [i for i in items if cat.stock_status(i) == stock]
    elif stock == "ATTENTION": items = [i for i in items if cat.stock_status(i) != "OK"]
    return items


@router.get("/catalogue/items")
def list_items(kind: str | None = None, q: str | None = None, category: str | None = None, supplier_id: str | None = None,
               status: str = "active", stock: str | None = None, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    sups = {s.id: s for s in db.query(m.Supplier)}
    show = sees_cost(user)
    return [cat.item_out(i, sups.get(i.supplier_id), show_cost=show) for i in _query(db, kind, q, category, supplier_id, status, stock)]


@router.post("/catalogue/items", status_code=201)
def create_item(b: cat.ItemIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    try: it = cat.create_item(db, b, user)
    except cat.CatalogueError as e: db.rollback(); _fail(e)
    except ValueError as e: db.rollback(); _422(str(e))
    db.commit(); return _out(db, it, user)


@router.get("/catalogue/items/{iid}")
def get_item(iid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    it = _item(db, iid)
    prices = db.query(m.PriceChange).filter_by(item_id=iid)
    if not sees_cost(user): prices = prices.filter((m.PriceChange.field.is_(None)) | (m.PriceChange.field == "PRICE"))
    prices = prices.order_by(m.PriceChange.created_at.desc()).limit(100)
    moves = db.query(m.StockMovement).filter_by(item_id=iid).order_by(m.StockMovement.created_at.desc()).limit(100)
    return {**_out(db, it, user),
            "price_history": [{"field": p.field or "PRICE", "old_price": None if p.old_price is None else f"{p.old_price:.2f}", "new_price": f"{p.new_price:.2f}", "reason": p.reason,
                               "user_name": p.user_name, "created_at": p.created_at.isoformat()} for p in prices],
            "stock_history": [{"delta": s.delta, "balance": s.balance, "reason": s.reason, "user_name": s.user_name, "created_at": s.created_at.isoformat()} for s in moves]}


# ── M34 per-supplier prices ─────────────────────────────────────────────────────
def _sp_out(q: m.SupplierPrice, sups: dict, today=None) -> dict:
    today = today or datetime.now(fups.local_tz()).date()
    tz = fups.local_tz()
    s = sups.get(q.supplier_id)
    return {"id": q.id, "supplier_id": q.supplier_id, "supplier_name": s.name if s else None, "price": f"{Decimal(q.price):.2f}", "min_qty": q.min_qty,
            "valid_from": spl._aw(q.valid_from).astimezone(tz).date().isoformat(), "valid_to": spl._aw(q.valid_to).astimezone(tz).date().isoformat() if q.valid_to else None,
            "lead_days": q.lead_days, "note": q.note, "ended_reason": q.ended_reason, "valid_today": spl.valid(q, today, q.min_qty or 1),
            "user_name": q.user_name, "created_at": q.created_at.isoformat() if q.created_at else None}


class SupplierPriceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supplier_id: str
    price: Decimal = Field(gt=0, le=100_000_000, decimal_places=2)
    min_qty: int = Field(default=1, ge=1, le=100000)
    valid_from: date | None = None
    valid_to: date | None = None
    lead_days: int | None = Field(None, ge=0, le=365)
    note: str | None = Field(None, max_length=300)


@router.get("/catalogue/items/{iid}/supplier-prices")
def list_supplier_prices(iid: str, qty: int = 1, db: Session = Depends(get_db), user: dict = Depends(require_roles(*COST_VIEW))):
    it = _item(db, iid); sups = {s.id: s for s in db.query(m.Supplier)}
    sid, rate, src, q = spl.best(db, it, max(1, qty))
    return {"quotes": [_sp_out(x, sups) for x in spl.quotes(db, iid)],
            "best": {"supplier_id": sid, "supplier_name": sups[sid].name if sid in sups else None, "rate": f"{rate:.2f}", "source": src, "quote_id": q.id if q else None, "qty": max(1, qty)}}


@router.post("/catalogue/items/{iid}/supplier-prices", status_code=201)
def add_supplier_price(iid: str, b: SupplierPriceIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    it = _item(db, iid); s = db.get(m.Supplier, b.supplier_id)
    if not s: raise HTTPException(404, "Supplier not found")
    if s.is_active is False: raise HTTPException(409, f"{s.name} is marked inactive")
    tz = fups.local_tz()
    start = b.valid_from or datetime.now(tz).date()
    if b.valid_to and b.valid_to < start: _422("valid_to is before valid_from")
    q = m.SupplierPrice(item_id=it.id, supplier_id=s.id, price=b.price, min_qty=b.min_qty, valid_from=spl.at(start),
                        valid_to=spl.at(b.valid_to).replace(hour=0) + timedelta(days=1, microseconds=-1) if b.valid_to else None,
                        lead_days=b.lead_days, note=(b.note or "").strip() or None, user_id=user.get("sub"), user_name=user.get("name"))
    db.add(q); db.commit()
    return _sp_out(q, {s.id: s})


class EndQuoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=300)


@router.post("/supplier-prices/{qid}/end")
def end_supplier_price(qid: str, b: EndQuoteIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    q = db.get(m.SupplierPrice, qid)
    if not q: raise HTTPException(404, "Supplier price not found")
    tz = fups.local_tz()
    yesterday_end = spl.at(datetime.now(tz).date()) - timedelta(microseconds=1)
    if q.valid_to is not None and spl._aw(q.valid_to) <= yesterday_end: raise HTTPException(409, "This quote has already ended")
    q.valid_to = max(yesterday_end, spl._aw(q.valid_from) - timedelta(microseconds=1)); q.ended_reason = b.reason.strip()
    db.commit(); return _sp_out(q, {s.id: s for s in db.query(m.Supplier)})


# ── M28 photos ─────────────────────────────────────────────────────────────────
@router.post("/catalogue/items/{iid}/photo")
async def upload_photo(iid: str, file: UploadFile = File(...), db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    from app.services import photos
    it = _item(db, iid)
    data = await file.read(photos.MAX_BYTES + 1)
    try: name = photos.save(it.id, data)
    except photos.PhotoError as e: raise HTTPException(e.status, e.detail)
    old = it.photo; it.photo = name; it.updated_at = flow.now(); db.commit()
    if old and old != name: photos.remove(old)
    return _out(db, it, user)


@router.delete("/catalogue/items/{iid}/photo")
def delete_photo(iid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    from app.services import photos
    it = _item(db, iid); old = it.photo
    it.photo = None; db.commit(); photos.remove(old)
    return _out(db, it, user)


@router.get("/catalogue/items/{iid}/photo")
def get_photo(iid: str, size: str = "thumb", db: Session = Depends(get_db), user: dict = Depends(current_user)):
    """Any signed-in staff member (the designer and 3D editor show photos too); clients don't see the catalogue."""
    from app.services import photos
    if user.get("role") == "CLIENT": raise HTTPException(403, "Not available in the client portal")
    it = _item(db, iid); p = photos.path(it.photo, size)
    if not p: raise HTTPException(404, "This item has no photo")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


@router.patch("/catalogue/items/{iid}")
def patch_item(iid: str, b: cat.ItemPatch, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    it = _item(db, iid)
    data = b.model_dump(exclude_unset=True)
    for k in ("name", "category", "kind", "unit", "is_active"):
        if k in data and data[k] is None: _422(f"{k} cannot be empty")
    if "supplier_id" in data:
        try: cat.check_supplier(db, data["supplier_id"])
        except cat.CatalogueError as e: _fail(e)
    merged = {d: data.get(d, getattr(it, d)) for d in ("length_mm", "width_mm", "height_mm")}
    try: cat.need_dims(data.get("kind", it.kind or "FURNITURE"), merged["length_mm"], merged["width_mm"], merged["height_mm"])
    except ValueError as e: _422(str(e))
    for k, v in data.items(): setattr(it, k, v)
    db.commit(); return _out(db, it, user)


class PriceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    price: Decimal = Field(**cat.PRICE)
    reason: str = Field(min_length=3, max_length=200)


@router.post("/catalogue/items/{iid}/price")
def change_price(iid: str, b: PriceIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    """Changing a price never touches existing BOQs (they are frozen); new BOQs use the new price and warn that the design's saved price differs."""
    it = _item(db, iid)
    if Decimal(it.price) == b.price: raise HTTPException(409, f"The price is already {b.price:.2f}")
    cat.log_price(db, it, it.price, b.price, b.reason.strip(), user); it.price = b.price
    db.commit(); return _out(db, it, user)


class CostIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cost: Decimal = Field(**cat.PRICE)
    reason: str = Field(min_length=3, max_length=200)


@router.post("/catalogue/items/{iid}/cost")
def change_cost(iid: str, b: CostIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    """Purchase cost (what we pay the supplier). New purchase orders use it; existing POs keep their own rates."""
    it = _item(db, iid)
    if it.cost_price is not None and Decimal(it.cost_price) == b.cost: raise HTTPException(409, f"The cost is already {b.cost:.2f}")
    cat.log_price(db, it, it.cost_price, b.cost, b.reason.strip(), user, field="COST"); it.cost_price = b.cost
    db.commit(); return _out(db, it, user)


class StockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delta: int = Field(ge=-1_000_000, le=1_000_000)
    reason: str = Field(min_length=3, max_length=200)

    @field_validator("delta")
    @classmethod
    def _nz(cls, v):
        if v == 0: raise ValueError("Quantity must not be 0")
        return v


@router.post("/catalogue/items/{iid}/stock")
def change_stock(iid: str, b: StockIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STOCK))):
    it = _item(db, iid)
    try: cat.move_stock(db, it, b.delta, b.reason.strip(), user)
    except cat.CatalogueError as e: db.rollback(); _fail(e)
    db.commit(); return _out(db, it, user)


@router.get("/catalogue/export.csv")
def export(kind: str | None = None, status: str = "active", db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    sups = {s.id: s for s in db.query(m.Supplier)}
    rows = [(i, sups.get(i.supplier_id)) for i in _query(db, kind, None, None, None, status, None)]
    name = f"catalogue-{(kind or 'all').lower()}.csv"
    return Response(cat.export_csv(rows, show_cost=sees_cost(user)), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/catalogue/export.xlsx")
def export_xlsx(kind: str | None = None, status: str = "active", db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    sups = {s.id: s for s in db.query(m.Supplier)}
    rows = [(i, sups.get(i.supplier_id)) for i in _query(db, kind, None, None, None, status, None)]
    name = f"catalogue-{(kind or 'all').lower()}.xlsx"
    return Response(cat.export_xlsx(rows, show_cost=sees_cost(user)), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/catalogue/import")
async def import_items(file: UploadFile = File(...), kind: str = "FURNITURE", apply: bool = False,
                       db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    """apply=false → preview only. apply=true → all rows written in ONE transaction, or none if any row has an error."""
    if kind not in m.CATALOGUE_KINDS: _422(f"kind must be one of {', '.join(m.CATALOGUE_KINDS)}")
    data = await file.read(cat.MAX_BYTES + 1)
    try:
        res = cat.import_csv(db, data, kind, user, apply=apply, filename=file.filename or "CSV")
        if res["applied"]: db.commit()
        else: db.rollback()
        return res
    except cat.CatalogueError as e: db.rollback(); _fail(e)
    except Exception: db.rollback(); raise


# ── Suppliers ──────────────────────────────────────────────────────────────────
class SupplierIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    contact_person: str | None = Field(None, max_length=120)
    phone: str | None = None; email: str | None = Field(None, max_length=160)
    city: str | None = Field(None, max_length=80); address: str | None = Field(None, max_length=1000)
    gstin: str | None = None
    lead_time_days: int | None = Field(None, ge=0, le=365)
    payment_terms_days: int | None = Field(None, ge=0, le=365)
    notes: str | None = Field(None, max_length=2000)

    @field_validator("name", "contact_person", "city", "address", "notes", mode="before")
    @classmethod
    def _strip(cls, v): return None if v is None else (str(v).strip() or None)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        if v is None or not v.strip(): return None
        try: normalize_phone(v)
        except PhoneError as e: raise ValueError(str(e))
        return v.strip()

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if v is None or not v.strip(): return None
        v = v.strip()
        if "@" not in v or "." not in v.split("@")[-1] or " " in v: raise ValueError("Not a valid email address")
        return v

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v): return cat.normalize_gstin(v)


class SupplierPatch(SupplierIn):
    name: str | None = Field(None, min_length=1, max_length=160)
    is_active: bool | None = None


def _sup_out(s: m.Supplier, items: int = 0) -> dict:
    return {"id": s.id, "name": s.name, "contact_person": s.contact_person, "phone": s.phone, "email": s.email, "city": s.city, "address": s.address,
            "gstin": s.gstin, "lead_time_days": s.lead_time_days, "payment_terms_days": s.payment_terms_days, "notes": s.notes, "is_active": s.is_active is not False, "items": items,
            "created_at": s.created_at.isoformat() if s.created_at else None}


def _dupes(db: Session, phone_norm, gstin, name, exclude=None):
    q = db.query(m.Supplier)
    if exclude: q = q.filter(m.Supplier.id != exclude)
    if phone_norm and (d := q.filter(m.Supplier.phone_norm == phone_norm).first()): raise HTTPException(409, f"A supplier with this phone number already exists: {d.name}")
    if gstin and (d := q.filter(m.Supplier.gstin == gstin).first()): raise HTTPException(409, f"A supplier with this GSTIN already exists: {d.name}")
    if name and (d := q.filter(func.lower(m.Supplier.name) == name.lower()).first()): raise HTTPException(409, f"A supplier named '{d.name}' already exists")


def _counts(db: Session) -> dict:
    return dict(db.query(m.FurnitureItem.supplier_id, func.count()).filter(m.FurnitureItem.supplier_id.isnot(None)).group_by(m.FurnitureItem.supplier_id).all())


@router.get("/suppliers")
def list_suppliers(q: str | None = None, include_inactive: bool = False, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    qry = db.query(m.Supplier)
    if not include_inactive: qry = qry.filter(m.Supplier.is_active.isnot(False))
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        conds = [func.lower(m.Supplier.name).like(like), func.lower(m.Supplier.city).like(like), func.lower(m.Supplier.contact_person).like(like), func.lower(m.Supplier.gstin).like(like)]
        try:
            if (pn := normalize_phone(q)): conds.append(m.Supplier.phone_norm == pn)
        except PhoneError: pass
        qry = qry.filter(or_(*conds))
    counts = _counts(db)
    return [_sup_out(s, counts.get(s.id, 0)) for s in qry.order_by(m.Supplier.name)]


@router.post("/suppliers", status_code=201)
def create_supplier(b: SupplierIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    pn = normalize_phone(b.phone) if b.phone else None
    _dupes(db, pn, b.gstin, b.name)
    s = m.Supplier(**b.model_dump(), phone_norm=pn, is_active=True); db.add(s); db.commit()
    return _sup_out(s)


@router.get("/suppliers/{sid}")
def get_supplier(sid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    s = db.get(m.Supplier, sid)
    if not s: raise HTTPException(404, "Supplier not found")
    items = db.query(m.FurnitureItem).filter_by(supplier_id=sid).order_by(m.FurnitureItem.name).all()
    return {**_sup_out(s, len(items)), "item_list": [cat.item_out(i, s, show_cost=sees_cost(user)) for i in items]}


@router.patch("/suppliers/{sid}")
def patch_supplier(sid: str, b: SupplierPatch, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    s = db.get(m.Supplier, sid)
    if not s: raise HTTPException(404, "Supplier not found")
    data = b.model_dump(exclude_unset=True)
    if "name" in data and not data["name"]: _422("name cannot be empty")
    if "is_active" in data and data["is_active"] is None: _422("is_active cannot be empty")
    pn = normalize_phone(data["phone"]) if data.get("phone") else None
    _dupes(db, pn if "phone" in data else None, data.get("gstin"), data.get("name"), exclude=sid)
    for k, v in data.items(): setattr(s, k, v)
    if "phone" in data: s.phone_norm = pn
    db.commit(); return _sup_out(s, _counts(db).get(sid, 0))
