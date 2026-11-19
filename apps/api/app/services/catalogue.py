"""Catalogue rules shared by the API and the CSV import, so a row typed in a form and a row in a spreadsheet are judged identically.
Prices are Decimal. Every price change and stock movement is written to an append-only ledger (PriceChange / StockMovement)."""
import csv
import io
import re
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import models as m

SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-_./]{1,39}$")
DIM = dict(gt=0, le=20000)
PRICE = dict(ge=0, le=1_000_000_000, decimal_places=2)


class CatalogueError(Exception):
    def __init__(self, status: int, detail): self.status, self.detail = status, detail


def _clean(v, n):
    if v is None: return None
    v = str(v).strip()
    return v[:n] or None


# ── GSTIN (Indian GST number): 15 chars, state code + PAN + entity + 'Z' + mod-36 check character ─────────────────
_G = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def gstin_check_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        p = _G.index(ch) * (2 if i % 2 else 1)
        total += p // 36 + p % 36
    return _G[(36 - total % 36) % 36]


def normalize_gstin(raw: str | None) -> str | None:
    if raw is None or not str(raw).strip(): return None
    g = re.sub(r"\s", "", str(raw)).upper()
    if len(g) != 15: raise ValueError("A GSTIN has exactly 15 characters")
    if not GSTIN_RE.match(g): raise ValueError("Not a valid GSTIN format (e.g. 24AAACB1234C1Z5)")
    if not 1 <= int(g[:2]) <= 38 and g[:2] not in ("97", "99"): raise ValueError("GSTIN state code must be 01-38")
    if gstin_check_char(g[:14]) != g[14]: raise ValueError("GSTIN check digit is wrong — please re-check the number")
    return g


# ── Item validation ────────────────────────────────────────────────────────────
class _ItemFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("style", check_fields=False, mode="before")
    @classmethod
    def _style(cls, v):
        if v is None: return None
        tags = [t.strip().lower() for t in re.split(r"[,;/|]", str(v)) if t.strip()]
        if any(not re.fullmatch(r"[a-z][a-z \-]{1,29}", t) for t in tags): raise ValueError("Style: words separated by commas, e.g. modern, minimal")
        return ", ".join(dict.fromkeys(tags)) or None

    @field_validator("name", "category", "material", "colour", check_fields=False, mode="before")
    @classmethod
    def _strip(cls, v):
        return None if v is None else (str(v).strip() or None)

    @field_validator("kind", check_fields=False)
    @classmethod
    def _kind(cls, v):
        if v is None: return v
        v = v.strip().upper()
        if v not in m.CATALOGUE_KINDS: raise ValueError(f"kind must be one of {', '.join(m.CATALOGUE_KINDS)}")
        return v

    @field_validator("unit", check_fields=False)
    @classmethod
    def _unit(cls, v):
        if v is None: return v
        match = next((u for u in m.CATALOGUE_UNITS if u.lower() == v.strip().lower()), None)
        if not match: raise ValueError(f"unit must be one of {', '.join(m.CATALOGUE_UNITS)}")
        return match


class ItemIn(_ItemFields):
    sku: str
    name: str = Field(min_length=1, max_length=160)
    kind: str = "FURNITURE"
    category: str = Field(min_length=1, max_length=60)
    unit: str = "No."
    price: Decimal = Field(**PRICE)
    cost_price: Decimal | None = Field(None, **PRICE)
    stock: int = Field(0, ge=0, le=1_000_000)
    min_stock: int | None = Field(None, ge=0, le=1_000_000)
    length_mm: float | None = Field(None, **DIM); width_mm: float | None = Field(None, **DIM); height_mm: float | None = Field(None, **DIM)
    material: str | None = Field(None, max_length=80); colour: str | None = Field(None, max_length=60)
    mount_mm: float | None = Field(None, ge=0, le=3000); style: str | None = Field(None, max_length=120)
    description: str | None = Field(None, max_length=2000)
    supplier_id: str | None = None

    @field_validator("sku", mode="before")
    @classmethod
    def _sku(cls, v):
        v = re.sub(r"\s+", "-", str(v or "").strip()).upper()
        if not SKU_RE.match(v): raise ValueError("SKU: 2-40 letters/digits/- _ . /, starting with a letter or digit (e.g. BED-KNG-WLT-001)")
        return v


class ItemPatch(_ItemFields):
    """SKU, price and stock are NOT editable here: SKUs are referenced by saved designs, and price/stock changes go through their ledgers."""
    name: str | None = Field(None, min_length=1, max_length=160)
    kind: str | None = None
    category: str | None = Field(None, min_length=1, max_length=60)
    unit: str | None = None
    min_stock: int | None = Field(None, ge=0, le=1_000_000)
    length_mm: float | None = Field(None, **DIM); width_mm: float | None = Field(None, **DIM); height_mm: float | None = Field(None, **DIM)
    material: str | None = Field(None, max_length=80); colour: str | None = Field(None, max_length=60)
    mount_mm: float | None = Field(None, ge=0, le=3000); style: str | None = Field(None, max_length=120)
    description: str | None = Field(None, max_length=2000)
    supplier_id: str | None = None
    is_active: bool | None = None


def need_dims(kind, L, W, H):
    if kind == "FURNITURE" and not (L and W and H):
        raise ValueError("Furniture needs length, width and height in mm (the designer and 3D editor place it by size)")


def stock_status(it: m.FurnitureItem) -> str:
    s = it.stock or 0
    if s <= 0: return "OUT"
    if it.min_stock is not None and s <= it.min_stock: return "LOW"
    return "OK"


def margin_pct(price, cost) -> str | None:
    """Gross margin on the selling price: (price − cost) / price, one decimal. None when either is unknown or price is 0."""
    if cost is None or price is None or Decimal(price) <= 0: return None
    return f"{((Decimal(price) - Decimal(cost)) * 100 / Decimal(price)).quantize(Decimal('0.1'))}"


def item_out(it: m.FurnitureItem, supplier: m.Supplier | None = None, show_cost: bool = True) -> dict:
    return {"id": it.id, "sku": it.sku, "name": it.name, "kind": it.kind or "FURNITURE", "category": it.category, "unit": it.unit or "No.",
            "cost_price": (None if it.cost_price is None else f"{Decimal(it.cost_price):.2f}") if show_cost else None,
            "margin_pct": margin_pct(it.price, it.cost_price) if show_cost else None, "cost_visible": show_cost,
            "price": f"{Decimal(it.price):.2f}", "stock": it.stock or 0, "min_stock": it.min_stock, "stock_status": stock_status(it),
            "length_mm": it.length_mm, "width_mm": it.width_mm, "height_mm": it.height_mm, "material": it.material, "colour": it.colour,
            "mount_mm": it.mount_mm, "style": it.style, "has_photo": bool(getattr(it, "photo", None)), "photo_v": (it.photo or "")[-6:] if getattr(it, "photo", None) else None,
            "description": it.description, "supplier_id": it.supplier_id, "supplier_name": supplier.name if supplier else None,
            "is_active": it.is_active is not False, "updated_at": it.updated_at.isoformat() if it.updated_at else None}


def log_price(db: Session, it: m.FurnitureItem, old, new: Decimal, reason: str, user: dict, field: str = "PRICE"):
    db.add(m.PriceChange(item_id=it.id, old_price=old, new_price=new, reason=reason, field=field, user_id=user.get("sub"), user_name=user.get("name")))


def move_stock(db: Session, it: m.FurnitureItem, delta: int, reason: str, user: dict, *, ref_type: str | None = None, ref_id: str | None = None, project_id: str | None = None,
               unit_cost=None):
    bal = (it.stock or 0) + delta
    if bal < 0: raise CatalogueError(409, f"Only {it.stock or 0} {it.unit or 'No.'} of {it.sku} in stock; cannot remove {-delta}.")
    it.stock = bal
    db.add(m.StockMovement(item_id=it.id, delta=delta, balance=bal, reason=reason, user_id=user.get("sub"), user_name=user.get("name"),
                           ref_type=ref_type, ref_id=ref_id, project_id=project_id, unit_cost=unit_cost))


def check_supplier(db: Session, sid: str | None):
    if sid and not db.get(m.Supplier, sid): raise CatalogueError(404, "Supplier not found")


def create_item(db: Session, b: ItemIn, user: dict) -> m.FurnitureItem:
    if db.query(m.FurnitureItem).filter(func.upper(m.FurnitureItem.sku) == b.sku).first():
        raise CatalogueError(409, f"SKU {b.sku} already exists")
    need_dims(b.kind, b.length_mm, b.width_mm, b.height_mm)
    check_supplier(db, b.supplier_id)
    data = b.model_dump(exclude={"stock"})
    it = m.FurnitureItem(**data, stock=0, is_active=True); db.add(it); db.flush()
    log_price(db, it, None, b.price, "Item created", user)
    if b.cost_price is not None: log_price(db, it, None, b.cost_price, "Item created", user, field="COST")
    if b.stock: move_stock(db, it, b.stock, "Opening stock", user)
    return it


# ── CSV import / export ────────────────────────────────────────────────────────
COLUMNS = ["sku", "name", "kind", "category", "unit", "price", "cost", "stock", "min_stock", "length_mm", "width_mm", "height_mm",
           "material", "colour", "supplier", "description", "mount_mm", "style"]
ALIASES = {"cost price": "cost", "purchase price": "cost", "cost (inr)": "cost", "buying price": "cost", "rate": "price", "mrp": "price", "price (inr)": "price", "price (₹)": "price", "qty": "stock", "quantity": "stock", "reorder level": "min_stock",
           "min stock": "min_stock", "length": "length_mm", "width": "width_mm", "depth": "width_mm", "height": "height_mm", "color": "colour",
           "item": "name", "item name": "name", "mount": "mount_mm", "mounting height": "mount_mm", "styles": "style", "type": "kind", "vendor": "supplier", "supplier name": "supplier", "code": "sku", "item code": "sku"}
MAX_ROWS, MAX_BYTES = 5000, 2_000_000


def _money(raw: str) -> Decimal:
    s = re.sub(r"[₹,\s]|Rs\.?|INR", "", raw, flags=re.I)
    try: return Decimal(s)
    except InvalidOperation: raise ValueError(f"price '{raw}' is not a number")


def _int(raw: str, name: str) -> int:
    s = raw.replace(",", "").strip()
    try: f = float(s)
    except ValueError: raise ValueError(f"{name} '{raw}' is not a number")
    if f != int(f): raise ValueError(f"{name} must be a whole number")
    return int(f)


def export_csv(rows: list[tuple[m.FurnitureItem, m.Supplier | None]], show_cost: bool = True) -> str:
    out = io.StringIO(); w = csv.writer(out); w.writerow(COLUMNS if show_cost else [c for c in COLUMNS if c != "cost"])
    for it, sup in rows:
        cost = ["" if it.cost_price is None else f"{Decimal(it.cost_price):.2f}"] if show_cost else []
        w.writerow([it.sku, it.name, it.kind or "FURNITURE", it.category, it.unit or "No.", f"{Decimal(it.price):.2f}", *cost, it.stock or 0,
                    "" if it.min_stock is None else it.min_stock, *["" if v is None else f"{v:g}" for v in (it.length_mm, it.width_mm, it.height_mm)],
                    it.material or "", it.colour or "", sup.name if sup else "", it.description or "", "" if it.mount_mm is None else f"{it.mount_mm:g}", it.style or ""])
    return "﻿" + out.getvalue()        # BOM so Excel opens ₹/accents correctly


# ── M29 Excel ─────────────────────────────────────────────────────────────────
XLSX_MAGIC = b"PK\x03\x04"
XLS_MAGIC = b"\xd0\xcf\x11\xe0"          # old binary .xls (Excel 97-2003)


def _cell(v) -> str:
    """An Excel cell as the text the CSV importer expects (whole numbers without '.0', no float noise)."""
    from datetime import date, datetime
    if v is None: return ""
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, float):
        if v.is_integer(): return str(int(v))
        return format(Decimal(repr(v)).normalize(), "f")
    if isinstance(v, (datetime, date)): return v.isoformat()[:10]
    return str(v).strip()


def xlsx_to_csv(data: bytes) -> bytes:
    """First worksheet of an .xlsx → CSV bytes, so Excel files go through exactly the same validation as CSV."""
    if data[:4] == XLS_MAGIC: raise CatalogueError(422, "This is an old .xls file. In Excel use File → Save As → 'Excel Workbook (.xlsx)' or 'CSV UTF-8'.")
    try:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except ImportError: raise CatalogueError(422, "Excel import needs the 'openpyxl' package (pip install openpyxl) — or save the sheet as CSV.")
    except Exception: raise CatalogueError(422, "That file is not a readable Excel workbook (.xlsx).")
    try:
        ws = wb.worksheets[0]; out = io.StringIO(); w = csv.writer(out); n = 0
        for row in ws.iter_rows(values_only=True):
            vals = [_cell(v) for v in row]
            while vals and vals[-1] == "": vals.pop()
            if not vals:
                if n: w.writerow([])          # keep row numbers aligned with Excel's
                continue
            w.writerow(vals); n += 1
            if n > 20000: raise CatalogueError(413, "At most 20,000 rows per import")
    finally: wb.close()
    text = out.getvalue().rstrip("\r\n")
    if not text: raise CatalogueError(422, "The first sheet of the workbook is empty")
    return text.encode("utf-8")


def export_xlsx(rows: list[tuple[m.FurnitureItem, m.Supplier | None]], show_cost: bool = True) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    lines = list(csv.reader(io.StringIO(export_csv(rows, show_cost).lstrip("\ufeff"))))
    wb = Workbook(); ws = wb.active; ws.title = "Catalogue"
    numeric = {"price", "cost", "stock", "min_stock", "length_mm", "width_mm", "height_mm", "mount_mm"}
    for r, line in enumerate(lines):
        if r == 0: ws.append(line); continue
        ws.append([(float(v) if "." in v else int(v)) if line and lines[0][c] in numeric and v not in ("",) else v for c, v in enumerate(line)])
    for cell in ws[1]: cell.font = Font(bold=True)
    for col, name in enumerate(lines[0], 1):
        if name in ("price", "cost"):
            for row in ws.iter_rows(min_row=2, min_col=col, max_col=col):
                row[0].number_format = "#,##0.00"
    ws.freeze_panes = "A2"
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try: return data.decode(enc)
        except UnicodeDecodeError: pass
    raise CatalogueError(422, "The file is not readable text. Save it from Excel as 'CSV UTF-8 (Comma delimited)'.")


def import_csv(db: Session, data: bytes, default_kind: str, user: dict, *, apply: bool, filename: str = "CSV") -> dict:
    """All-or-nothing. Returns a preview of every row (CREATE / UPDATE with the exact changes / UNCHANGED) and every error with its row number.
    With apply=True and no errors the changes are written (price changes and stock differences go through the ledgers); with errors nothing is."""
    if len(data) > MAX_BYTES: raise CatalogueError(413, f"File too large (max {MAX_BYTES // 1_000_000} MB)")
    if data[:4] in (XLSX_MAGIC, XLS_MAGIC) or filename.lower().endswith((".xlsx", ".xls")): data = xlsx_to_csv(data)     # M29: Excel → same path as CSV
    text = _decode(data)
    if not text.strip(): raise CatalogueError(422, "The file is empty")
    try: dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t")
    except csv.Error: dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    header = [ALIASES.get(h.strip().lower(), h.strip().lower()) for h in next(reader)]
    unknown = [h for h in header if h and h not in COLUMNS]
    missing = [c for c in ("sku", "name", "category", "price") if c not in header]
    if missing: raise CatalogueError(422, f"Missing column(s): {', '.join(missing)}. Expected columns: {', '.join(COLUMNS)}")
    sups = {s.name.strip().lower(): s for s in db.query(m.Supplier)}
    sup_names = {s.id: s.name for s in sups.values()}
    existing = {i.sku.upper(): i for i in db.query(m.FurnitureItem)}
    rows, errors, seen = [], [], {}
    for n, raw in enumerate(reader, start=2):                                  # row 1 is the header, so numbers match Excel
        if not any(c.strip() for c in raw): continue
        if len(rows) + len(errors) >= MAX_ROWS: raise CatalogueError(413, f"Too many rows (max {MAX_ROWS})")
        rec = {h: (raw[i].strip() if i < len(raw) else "") for i, h in enumerate(header) if h in COLUMNS}
        try:
            sup = None
            if rec.get("supplier"):
                sup = sups.get(rec["supplier"].lower())
                if not sup: raise ValueError(f"supplier '{rec['supplier']}' does not exist — add it under Suppliers first")
            vals = {"sku": rec.get("sku"), "name": rec.get("name"), "category": rec.get("category"), "kind": rec.get("kind") or default_kind,
                    "unit": rec.get("unit") or None, "price": _money(rec.get("price", "")) if rec.get("price") else None,
                    "material": rec.get("material") or None, "colour": rec.get("colour") or None, "description": rec.get("description") or None,
                    "style": rec.get("style") or None,
                    "supplier_id": sup.id if sup else None}
            if rec.get("cost"):
                try: vals["cost_price"] = _money(rec["cost"])
                except ValueError: raise ValueError(f"cost '{rec['cost']}' is not a number")
            if vals["price"] is None: raise ValueError("price is required")
            for k in ("stock", "min_stock"):
                if rec.get(k): vals[k] = _int(rec[k], k)
            for k in ("length_mm", "width_mm", "height_mm", "mount_mm"):
                if rec.get(k):
                    try: vals[k] = float(rec[k].replace(",", ""))
                    except ValueError: raise ValueError(f"{k} '{rec[k]}' is not a number")
            item_in = ItemIn(**{k: v for k, v in vals.items() if v is not None})
            cur = existing.get(item_in.sku)
            dims = [getattr(item_in, d) or (getattr(cur, d) if cur else None) for d in ("length_mm", "width_mm", "height_mm")]
            need_dims(item_in.kind, *dims)
        except ValidationError as e:
            errors.append({"row": n, "sku": rec.get("sku") or None, "error": "; ".join(f"{'.'.join(map(str, x['loc'])) or 'row'}: {x['msg'].removeprefix('Value error, ')}" for x in e.errors())}); continue
        except ValueError as e:
            errors.append({"row": n, "sku": rec.get("sku") or None, "error": str(e)}); continue
        if item_in.sku in seen:
            errors.append({"row": n, "sku": item_in.sku, "error": f"SKU appears twice in the file (also row {seen[item_in.sku]})"}); continue
        seen[item_in.sku] = n
        if not cur:
            rows.append({"row": n, "sku": item_in.sku, "name": item_in.name, "action": "CREATE", "changes": [], "_in": item_in, "_fields": rec}); continue
        changes = []
        given = item_in.model_dump(exclude_unset=True)
        for k, v in given.items():
            if k == "sku": continue
            old = getattr(cur, k)
            if k == "price": same = Decimal(old) == v
            elif k == "cost_price": same = old is not None and Decimal(old) == v
            elif k == "kind": same = (old or "FURNITURE") == v
            elif k == "unit": same = (old or "No.") == v
            else: same = old == v
            if not same:
                show = lambda x: (f"{Decimal(x):.2f}" if k in ("price", "cost_price") and x is not None else (sup_names.get(x, x) if k == "supplier_id" else x))
                changes.append({"field": {"supplier_id": "supplier", "cost_price": "cost"}.get(k, k), "from": show(old), "to": show(v)})
        if cur.is_active is False: changes.append({"field": "is_active", "from": False, "to": True})
        rows.append({"row": n, "sku": item_in.sku, "name": item_in.name, "action": "UPDATE" if changes else "UNCHANGED", "changes": changes, "_in": item_in, "_cur": cur})
    summary = {"create": sum(r["action"] == "CREATE" for r in rows), "update": sum(r["action"] == "UPDATE" for r in rows),
               "unchanged": sum(r["action"] == "UNCHANGED" for r in rows), "errors": len(errors)}
    applied = False
    if apply and not errors and (summary["create"] or summary["update"]):
        reason = f"CSV import ({filename[:80]})"
        for r in rows:
            if r["action"] == "CREATE":
                create_item(db, r["_in"], user)
            elif r["action"] == "UPDATE":
                cur, data = r["_cur"], r["_in"].model_dump(exclude_unset=True)
                for ch in r["changes"]:
                    f = ch["field"]
                    if f == "price": log_price(db, cur, cur.price, data["price"], reason, user); cur.price = data["price"]
                    elif f == "cost": log_price(db, cur, cur.cost_price, data["cost_price"], reason, user, field="COST"); cur.cost_price = data["cost_price"]
                    elif f == "stock": move_stock(db, cur, data["stock"] - (cur.stock or 0), reason + " — stock count", user)
                    elif f == "supplier": cur.supplier_id = data["supplier_id"]
                    elif f == "is_active": cur.is_active = True
                    else: setattr(cur, f, data[f])
        applied = True
    public = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    return {"rows": public, "errors": errors, "summary": summary, "applied": applied, "ignored_columns": unknown}

