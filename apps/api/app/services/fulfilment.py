"""What an APPROVED BOQ still needs: per line, how much is made / bought / allocated, on order, delivered, and deliverable now.
All counts come from the ledgers (work orders, PO lines, stock movements, delivery notes) — nothing is stored twice."""
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import models as m
from app.services import cutting

SERVICE = {"Transport", "Installation"}


def _int(q) -> int:
    d = Decimal(q)
    return int(d) if d == d.to_integral() else int(d) + 1          # fractional quantities round UP for physical units


def allocated(db: Session, boq_id: str, item_id: str) -> int:
    v = db.query(func.coalesce(func.sum(m.StockMovement.delta), 0)).filter(m.StockMovement.ref_type == "ALLOC", m.StockMovement.ref_id == boq_id,
                                                                           m.StockMovement.item_id == item_id).scalar()
    return -int(v or 0)


def on_order(db: Session, boq_id: str, item_id: str) -> int:
    q = (db.query(func.coalesce(func.sum(m.POLine.qty - m.POLine.received), 0)).join(m.PurchaseOrder, m.PurchaseOrder.id == m.POLine.po_id)
         .filter(m.PurchaseOrder.boq_id == boq_id, m.PurchaseOrder.status.in_(["DRAFT", "ISSUED", "PARTIAL"]), m.POLine.item_id == item_id))
    return int(q.scalar() or 0)


def delivered_map(db: Session, boq_id: str, statuses=("SCHEDULED", "DISPATCHED", "DELIVERED")) -> dict:
    """key (sku or description) -> qty on delivery notes in `statuses`. Booked = not cancelled (so nothing is double-booked)."""
    out = defaultdict(int)
    rows = (db.query(m.DeliveryLine.sku, m.DeliveryLine.description, func.sum(m.DeliveryLine.qty)).join(m.DeliveryNote, m.DeliveryNote.id == m.DeliveryLine.dn_id)
            .filter(m.DeliveryNote.boq_id == boq_id, m.DeliveryNote.status.in_(statuses)).group_by(m.DeliveryLine.sku, m.DeliveryLine.description))
    for sku, desc, q in rows: out[sku or desc] += int(q or 0)
    return out


def lines(db: Session, boq: m.Boq) -> list[dict]:
    items = db.query(m.BoqItem).filter_by(boq_id=boq.id).order_by(m.BoqItem.line_no).all()
    cat = {i.sku: i for i in db.query(m.FurnitureItem).filter(m.FurnitureItem.sku.in_([x.sku for x in items if x.sku]))}
    booked, delivered = delivered_map(db, boq.id), delivered_map(db, boq.id, ("DELIVERED",))
    ready_wo = dict(db.query(m.WorkOrder.sku, func.count()).filter(m.WorkOrder.boq_id == boq.id, m.WorkOrder.stage == "READY").group_by(m.WorkOrder.sku).all())
    wo_total = dict(db.query(m.WorkOrder.sku, func.count()).filter(m.WorkOrder.boq_id == boq.id).group_by(m.WorkOrder.sku).all())
    out = []
    for x in items:
        if x.category in SERVICE: continue
        qty = _int(x.quantity); it = cat.get(x.sku) if x.sku else None
        key = x.sku or x.description
        row = {"line": x.line_no, "sku": x.sku, "description": x.description, "category": x.category, "unit": x.unit, "qty": qty,
               "item_id": it.id if it else None, "supplier": x.supplier, "booked": booked.get(key, 0), "delivered": delivered.get(key, 0)}
        if it and cutting.is_manufactured(it.category, it.length_mm, it.width_mm, it.height_mm):
            row.update(kind="MANUFACTURED", ready=ready_wo.get(x.sku, 0), work_orders=wo_total.get(x.sku, 0), on_order=0,
                       size=(it.length_mm, it.width_mm, it.height_mm))
        elif it:
            row.update(kind="BOUGHT_OUT", ready=allocated(db, boq.id, it.id), on_order=on_order(db, boq.id, it.id))
        else:
            row.update(kind="MANUAL", ready=qty, on_order=0)          # not in the catalogue: procured outside the system
        row["deliverable"] = max(0, min(qty, row["ready"]) - row["booked"])
        out.append(row)
    return out


def board_need(db: Session, boq: m.Boq) -> dict:
    """Sheets (by thickness) and edge band (m) for every manufactured unit of this BOQ, nested together."""
    pcs: dict[int, list] = defaultdict(list); edge = 0.0
    for r in lines(db, boq):
        if r["kind"] != "MANUFACTURED": continue
        L, W, H = r["size"]
        for p in cutting.panels(L, W, H):
            pcs[p["thickness"]].extend([(p["length"], p["width"])] * (p["qty"] * r["qty"])); edge += p["edge_m"] * r["qty"]
    return {"sheets": {th: cutting.nest(v)[0] for th, v in pcs.items()}, "edge_band_m": round(edge, 2)}


def fully_delivered(db: Session, boq: m.Boq) -> bool:
    return all(r["delivered"] >= r["qty"] for r in lines(db, boq))
