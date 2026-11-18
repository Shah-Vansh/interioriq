"""Material & services take-off from a SAVED design (deterministic, mm in → metric quantities out).
What it adds to a BOQ is what the furniture lines DON'T already contain: ceiling, lighting, electrical points and room finishes.
In-house furniture (wardrobes …) keeps its own catalogue price — its boards/hardware are inside it — so nothing is counted twice.
Each quantity is priced by a catalogue item chosen in the take-off rules (Estimation → Take-off), with a waste %, and converted to the item's unit."""
import math
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import models as m
from app.services import mep

TALL = 1800      # units taller than this, standing against a wall, hide that wall from paint and skirting

# key: (label, measured unit, default waste %, catalogue kinds that make sense)
KEYS = {
    "CEILING_GYPSUM": ("Gypsum false ceiling", "sq.m", 5, ["MATERIAL"]),
    "COVE_STRIP": ("Cove LED strip", "r.m", 5, ["LIGHTING"]),
    "DOWNLIGHT": ("Downlights", "No.", 0, ["LIGHTING"]),
    "SPOTLIGHT": ("Spotlights (in front of tall units)", "No.", 0, ["LIGHTING"]),
    "FAN_POINT": ("Fan point", "No.", 0, ["HARDWARE", "LIGHTING"]),
    "SOCKET": ("Socket points", "No.", 0, ["HARDWARE"]),
    "SWITCH": ("Switch points", "No.", 0, ["HARDWARE"]),
    "SWITCHBOARD": ("Switchboards", "No.", 0, ["HARDWARE"]),
    "AC_POINT": ("AC points (16A)", "No.", 0, ["HARDWARE"]),
    "LIGHT_POINT": ("Light points (wardrobe / pendant)", "No.", 0, ["LIGHTING", "HARDWARE"]),
    "WALL_PAINT": ("Wall paint (walls not hidden by tall units)", "sq.m", 10, ["MATERIAL"]),
    "FLOORING": ("Flooring", "sq.m", 8, ["MATERIAL"]),
    "SKIRTING": ("Skirting", "r.m", 5, ["MATERIAL"]),
}
SQFT_PER_SQM, FT_PER_M = Decimal("10.7639104"), Decimal("3.2808399")
COUNT_UNITS = {"No.", "set", "box", "sheet", "kg", "litre"}


def D(x) -> Decimal: return x if isinstance(x, Decimal) else Decimal(str(x))


def plain(x) -> str:
    """Decimal as a plain number without trailing zeros: 10 → '10' (normalize() alone would give '1E+1'), 16.070 → '16.07'."""
    s = format(D(x), "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def _touching(o, L, W):
    """Walls a unit stands against (within 100 mm) and its length along each."""
    out = []
    if o["y"] <= 100: out.append(o["length"])
    if W - (o["y"] + o["width"]) <= 100: out.append(o["length"])
    if o["x"] <= 100: out.append(o["width"])
    if L - (o["x"] + o["length"]) <= 100: out.append(o["width"])
    return out


def quantities(L: float, W: float, H: float, objs: list[dict], openings=()) -> dict:
    """Measured quantities (before waste), each with the basis it came from."""
    c = mep.ceiling(L, W, H, objs); e = mep.electrical(L, W, H, objs, openings)
    open_area = sum(o["width"] * o["height"] for o in openings); doorways = sum(o["width"] for o in openings if o["kind"] == "DOOR")
    pts = {k: sum(1 for p in e["points"] if p["type"] == k) for k in ("SOCKET", "SWITCH", "SWITCHBOARD", "AC", "LIGHT")}
    tall = [o for o in objs if (o.get("z") or 0) + (o.get("height") or 0) > TALL]     # tall units and wall cabinets hide the wall behind them
    hidden_wall = sum(seg * max(0, min((o.get("z") or 0) + (o.get("height") or 0), H) - (o.get("z") or 0)) for o in tall for seg in _touching(o, L, W))
    hidden_run = sum(seg for o in tall if not (o.get("z") or 0) for seg in _touching(o, L, W))   # only floor-standing units hide the skirting
    perim = 2 * (L + W)
    walls = max(0.0, perim * H - hidden_wall - open_area)
    q = {
        "CEILING_GYPSUM": (c["gypsum_area_m2"], f"{L:.0f} × {W:.0f} mm room"),
        "COVE_STRIP": (c["cove_strip_m"], f"cove {mep.COVE} mm from the walls"),
        "DOWNLIGHT": (sum(1 for x in c["lights"] if x["type"] == "DOWNLIGHT"), "ceiling plan grid"),
        "SPOTLIGHT": (sum(1 for x in c["lights"] if x["type"] == "SPOTLIGHT"), "ceiling plan"),
        "FAN_POINT": (1 if c["fan"] else 0, "ceiling plan"),
        "SOCKET": (pts["SOCKET"], "electrical layout"), "SWITCH": (pts["SWITCH"], "electrical layout"),
        "SWITCHBOARD": (pts["SWITCHBOARD"], "electrical layout"), "AC_POINT": (pts["AC"], "electrical layout"),
        "LIGHT_POINT": (pts["LIGHT"], "electrical layout"),
        "WALL_PAINT": (round(walls / 1e6, 2), f"walls {perim / 1000:.2f} m × {H / 1000:.2f} m − {hidden_wall / 1e6:.2f} sq.m behind tall units"
                                               + (f" − {open_area / 1e6:.2f} sq.m doors/windows" if open_area else "")),
        "FLOORING": (round(L * W / 1e6, 2), "full floor area"),
        "SKIRTING": (round(max(0.0, perim - hidden_run - doorways) / 1000, 2), f"perimeter {perim / 1000:.2f} m − {hidden_run / 1000:.2f} m behind tall units"
                                                                         + (f" − {doorways / 1000:.2f} m doorways" if doorways else "")),
    }
    return {k: {"label": KEYS[k][0], "qty": D(v), "unit": KEYS[k][1], "basis": b} for k, (v, b) in q.items()}


def convert(qty: Decimal, frm: str, to: str) -> Decimal | None:
    """Measured unit → catalogue unit. None when they can't be converted (e.g. an area priced per box)."""
    if frm == to: return qty
    if frm == "sq.m" and to == "sq.ft": return qty * SQFT_PER_SQM
    if frm == "r.m" and to == "r.ft": return qty * FT_PER_M
    if frm == "No." and to in COUNT_UNITS: return qty
    return None


def purchase_qty(qty: Decimal, unit: str) -> Decimal:
    """Round UP to what can be bought: whole units for counts and feet, 2 decimals for metres."""
    if unit in ("sq.m", "r.m"): return qty.quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    return qty.quantize(Decimal("1"), rounding=ROUND_CEILING)


def rules(db: Session) -> dict:
    row = db.get(m.CompanySetting, "takeoff_rules")
    saved = (row.value if row else None) or {}
    return {k: {"sku": (saved.get(k) or {}).get("sku") or None, "waste_pct": D((saved.get(k) or {}).get("waste_pct", KEYS[k][2]))} for k in KEYS}


def configured(db: Session) -> bool: return any(r["sku"] for r in rules(db).values())


def plan(db: Session, L: float, W: float, H: float, objs: list[dict], openings=()) -> dict:
    """Priced take-off: lines to add (item + purchase qty in its unit) and what couldn't be added and why."""
    qs, rs = quantities(L, W, H, objs, openings), rules(db)
    skus = [r["sku"] for r in rs.values() if r["sku"]]
    items = {i.sku.upper(): i for i in db.query(m.FurnitureItem).filter(func.upper(m.FurnitureItem.sku).in_([s.upper() for s in skus]))} if skus else {}
    lines, skipped, rows = [], [], []
    for k, qv in qs.items():
        r = rs[k]; row = {"key": k, **{x: qv[x] for x in ("label", "unit", "basis")}, "measured": f"{qv['qty']}", "waste_pct": plain(r["waste_pct"]), "sku": r["sku"]}
        if qv["qty"] <= 0: row["status"] = "NONE"; rows.append(row); continue
        if not r["sku"]: row["status"] = "UNMAPPED"; rows.append(row); skipped.append(f"{qv['label']}: {qv['qty']} {qv['unit']} — no catalogue item mapped"); continue
        it = items.get(r["sku"].upper())
        if not it: row["status"] = "MISSING"; rows.append(row); skipped.append(f"{qv['label']}: mapped SKU {r['sku']} is not in the catalogue"); continue
        if it.is_active is False: row["status"] = "ARCHIVED"; rows.append(row); skipped.append(f"{qv['label']}: {it.sku} is archived"); continue
        with_waste = qv["qty"] * (100 + r["waste_pct"]) / 100
        conv = convert(with_waste, qv["unit"], it.unit or "No.")
        if conv is None:
            row["status"] = "UNIT"; rows.append(row); skipped.append(f"{qv['label']}: measured in {qv['unit']} but {it.sku} is sold per {it.unit} — pick an item sold per {qv['unit']} (or sq.ft / r.ft)"); continue
        buy = purchase_qty(conv, it.unit or "No.")
        desc = f"{it.name} — {qv['label'].lower()}: {qv['qty']} {qv['unit']}" + (f" + {plain(r['waste_pct'])}% waste" if r["waste_pct"] else "")
        lines.append({"key": k, "item": it, "qty": buy, "description": desc})
        row.update(status="ADDED", item_name=it.name, buy_qty=plain(buy), buy_unit=it.unit or "No.", rate=f"{D(it.price):.2f}")
        rows.append(row)
    return {"lines": lines, "skipped": skipped, "rows": rows}


def for_design(db: Session, room_id: str, objs: list[dict]) -> dict:
    from app.routers.api import _room_dims, room_openings          # the single source of room dimensions (verified measurements win) + doors/windows
    L, W, H = _room_dims(db, room_id)
    return plan(db, L, W, H, objs, room_openings(db, room_id))
