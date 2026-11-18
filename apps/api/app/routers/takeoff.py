"""Take-off rules (which catalogue item prices each measured quantity, with waste %) and a per-design preview."""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models import models as m
from app.services import takeoff
from app.services.takeoff import plain

router = APIRouter(tags=["Take-off"])
READ = ("ADMIN", "PROJECT_MANAGER", "ESTIMATOR", "INTERIOR_DESIGNER", "SALES", "PROCUREMENT_MANAGER")
WRITE = ("ADMIN", "PROJECT_MANAGER", "ESTIMATOR")


@router.get("/takeoff/rules")
def get_rules(db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    rs = takeoff.rules(db)
    skus = [r["sku"] for r in rs.values() if r["sku"]]
    items = {i.sku.upper(): i for i in db.query(m.FurnitureItem).filter(func.upper(m.FurnitureItem.sku).in_([s.upper() for s in skus]))} if skus else {}
    out = []
    for k, (label, unit, waste, kinds) in takeoff.KEYS.items():
        r = rs[k]; it = items.get((r["sku"] or "").upper())
        out.append({"key": k, "label": label, "unit": unit, "default_waste_pct": waste, "kinds": kinds, "sku": r["sku"], "waste_pct": plain(r["waste_pct"]),
                    "item": {"id": it.id, "name": it.name, "unit": it.unit or "No.", "price": f"{Decimal(it.price):.2f}", "is_active": it.is_active is not False} if it else None,
                    "unit_ok": (takeoff.convert(Decimal(1), unit, it.unit or "No.") is not None) if it else None})
    return out


@router.put("/takeoff/rules")
def put_rules(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    bad = [k for k in body if k not in takeoff.KEYS]
    if bad: raise HTTPException(422, f"Unknown take-off item(s): {', '.join(bad)}")
    cur = {k: {"sku": v["sku"], "waste_pct": str(v["waste_pct"])} for k, v in takeoff.rules(db).items()}
    for k, v in body.items():
        if not isinstance(v, dict): raise HTTPException(422, f"{k}: expected {{sku, waste_pct}}")
        sku = (v.get("sku") or "").strip().upper() or None
        if sku:
            it = db.query(m.FurnitureItem).filter(func.upper(m.FurnitureItem.sku) == sku).first()
            if not it: raise HTTPException(404, f"{takeoff.KEYS[k][0]}: SKU {sku} is not in the catalogue")
            if takeoff.convert(Decimal(1), takeoff.KEYS[k][1], it.unit or "No.") is None:
                raise HTTPException(422, f"{takeoff.KEYS[k][0]} is measured in {takeoff.KEYS[k][1]}, but {it.sku} is sold per {it.unit}. Pick an item sold per {takeoff.KEYS[k][1]}"
                                         + (" or sq.ft" if takeoff.KEYS[k][1] == "sq.m" else " or r.ft" if takeoff.KEYS[k][1] == "r.m" else "") + ".")
        try: w = Decimal(str(v.get("waste_pct", cur[k]["waste_pct"])))
        except Exception: raise HTTPException(422, f"{takeoff.KEYS[k][0]}: waste % must be a number")
        if w < 0 or w > 50 or w != w.quantize(Decimal("0.1")): raise HTTPException(422, f"{takeoff.KEYS[k][0]}: waste % must be 0–50 with at most 1 decimal")
        cur[k] = {"sku": sku, "waste_pct": str(w)}
    row = db.get(m.CompanySetting, "takeoff_rules")
    if row: row.value, row.updated_by = cur, user.get("name")
    else: db.add(m.CompanySetting(key="takeoff_rules", value=cur, updated_by=user.get("name")))
    db.commit(); return get_rules(db, user)


@router.get("/rooms/{rid}/designs/{version}/takeoff")
def preview(rid: str, version: int, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    d = db.query(m.Design).filter_by(room_id=rid, version=version).first()
    if not d: raise HTTPException(404, f"Design version {version} not found")
    t = takeoff.for_design(db, rid, d.design_json.get("objects", []))
    return {"version": version, "rows": t["rows"], "skipped": t["skipped"], "lines": len(t["lines"]), "configured": takeoff.configured(db)}
