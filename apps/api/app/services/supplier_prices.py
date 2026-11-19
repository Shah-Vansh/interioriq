"""M34 per-supplier prices: which supplier to buy an item from, at what rate, for a quantity on a date (Decimal, server-side only)."""
from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import models as m
from app.services import followups as fups


def _aw(t): return t if t is None or t.tzinfo else t.replace(tzinfo=timezone.utc)
def at(d: date) -> datetime: return datetime.combine(d, time(0), tzinfo=fups.local_tz()).astimezone(timezone.utc)


def valid(q: m.SupplierPrice, on: date, qty: int = 1) -> bool:
    start = _aw(q.valid_from); end = _aw(q.valid_to)
    t = at(on)
    return start <= t and (end is None or t <= end) and (q.min_qty or 1) <= qty


def quotes(db: Session, item_id: str) -> list[m.SupplierPrice]:
    return db.query(m.SupplierPrice).filter_by(item_id=item_id).order_by(m.SupplierPrice.created_at.desc()).all()


def best(db: Session, item: m.FurnitureItem, qty: int, on: date | None = None):
    """(supplier_id, rate, source, quote) — the cheapest VALID quote from an ACTIVE supplier for this quantity today (ties: shorter lead time,
    then the item's default supplier); with none: the item's default supplier at its cost (or selling price, flagged)."""
    on = on or datetime.now(fups.local_tz()).date()
    sups = {s.id: s for s in db.query(m.Supplier)}
    ok = [q for q in quotes(db, item.id) if valid(q, on, qty) and sups.get(q.supplier_id) and sups[q.supplier_id].is_active is not False]
    if ok:
        q = min(ok, key=lambda q: (Decimal(q.price), q.lead_days if q.lead_days is not None else 10 ** 6, q.supplier_id != item.supplier_id))
        return q.supplier_id, Decimal(q.price), "QUOTE", q
    rate = item.cost_price if item.cost_price is not None else item.price
    return item.supplier_id, Decimal(rate), "COST" if item.cost_price is not None else "SELLING_PRICE", None
