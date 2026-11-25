"""Material & services take-off from a SAVED design (deterministic, mm in → metric quantities out).
What it adds to a BOQ is what the furniture lines DON'T already contain: ceiling, lighting, electrical points and room finishes.
In-house furniture (wardrobes …) keeps its own catalogue price — its boards/hardware are inside it — so nothing is counted twice.
Each quantity is priced by a catalogue item chosen in the take-off rules (Estimation → Take-off), with a waste %, and converted to the item's unit."""
import math
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import models as m
from app.services import mep, shape as shp

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
    # M38 design concept (only when a room has a concept; its ceiling / flooring then replace the generic lines above)
    "ACCENT_FLUTED_WOOD": ("Feature wall: fluted wood panelling", "sq.m", 8, ["MATERIAL"]),
    "ACCENT_WALLPAPER": ("Feature wall: wallpaper", "sq.m", 10, ["MATERIAL"]),
    "ACCENT_STONE": ("Feature wall: stone cladding", "sq.m", 8, ["MATERIAL"]),
    "ACCENT_PANELLING": ("Feature wall: moulded panelling", "sq.m", 8, ["MATERIAL"]),
    "ACCENT_PAINT": ("Feature wall: accent paint", "sq.m", 10, ["MATERIAL"]),
    "ACCENT_TILE": ("Feature wall: feature tiles", "sq.m", 8, ["MATERIAL"]),
    "ACCENT_JAALI": ("Feature wall: backlit jaali", "sq.m", 5, ["MATERIAL"]),
    "ACCENT_BRICK": ("Feature wall: brick cladding", "sq.m", 8, ["MATERIAL"]),
    "CEILING_GRID": ("Grid ceiling (wet area)", "sq.m", 5, ["MATERIAL"]),
    "CEILING_RAFTER": ("Wooden rafter ceiling", "sq.m", 5, ["MATERIAL"]),
    "FLOOR_WOOD": ("Flooring: wood / laminate", "sq.m", 8, ["MATERIAL"]),
    "FLOOR_MARBLE": ("Flooring: marble / large tiles", "sq.m", 8, ["MATERIAL"]),
    "FLOOR_TILE": ("Flooring: anti-skid tiles", "sq.m", 8, ["MATERIAL"]),
    "FLOOR_TERRAZZO": ("Flooring: terrazzo", "sq.m", 5, ["MATERIAL"]),
    "FLOOR_CONCRETE": ("Flooring: polished concrete", "sq.m", 5, ["MATERIAL"]),
    "FLOOR_STONE": ("Flooring: natural stone", "sq.m", 8, ["MATERIAL"]),
    "CURTAIN": ("Curtains (window width + 300 mm)", "r.m", 0, ["MATERIAL", "HARDWARE"]),
    "BLIND": ("Blinds (wet rooms)", "No.", 0, ["MATERIAL"]),
    "RUG": ("Rugs", "No.", 0, ["FURNITURE", "MATERIAL"]),
    "WALL_ART": ("Wall art", "No.", 0, ["FURNITURE", "MATERIAL"]),
    "DECOR_PLANT": ("Decor plants", "No.", 0, ["FURNITURE", "MATERIAL"]),
    "PENDANT": ("Decorative pendant lights", "No.", 0, ["LIGHTING"]),
    "CHANDELIER": ("Chandelier", "No.", 0, ["LIGHTING"]),
}
CONCEPT_KEY = {"concept_cove_led_rm": "COVE_STRIP", "rafter_ceiling_sqm": "CEILING_RAFTER", "curtain_rm": "CURTAIN", "blind_no": "BLIND", "rug_no": "RUG",
               "wall_art_no": "WALL_ART", "decor_plant_no": "DECOR_PLANT", "pendant_light_no": "PENDANT", "chandelier_no": "CHANDELIER"}
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


def _shell_measures(L, W, H, shell):
    """M41: wall area along the real outline at the real (sloped / uneven) height, floor = outline minus columns, plus the faces of
    columns, pillars, beams and ceiling drops that get painted / skirted. Returns (perimeter, wall area, floor area, extra paint, extra skirting, notes)."""
    from shapely.geometry import box
    from app.services import cad, shape as shp
    pg = shp.polygon(L, W, shell.get("shape")); cp = shell.get("ceiling") if (shell.get("ceiling") or {}).get("type") not in (None, "FLAT") else None
    wall = 0.0
    for e in shp.edges(L, W, shell.get("shape")):
        n = 8 if cp else 1
        hs = [shp.ceiling_at(cp, H, L, W, e["x0"] + (e["x1"] - e["x0"]) * k / n, e["y0"] + (e["y1"] - e["y0"]) * k / n) for k in range(n + 1)]
        wall += e["length"] * (sum(hs) - (hs[0] + hs[-1]) / 2) / n                      # trapezoid rule along the wall
    floor = pg.area; paint = skirt = 0.0; notes = []
    for st in shell.get("structures") or []:
        b = box(st["x"], st["y"], st["x"] + st["length"], st["y"] + st["width"]).intersection(pg)
        if b.is_empty: continue
        exposed = b.exterior.length - b.exterior.intersection(pg.exterior.buffer(1)).length      # faces not built into a wall
        if st["kind"] in ("COLUMN", "PILLAR"):
            h = shp.lowest_over(cp, H, L, W, b); paint += exposed * h; skirt += exposed; floor -= b.area
            notes.append(f"{st['label']} {exposed / 1000:.2f} m round")
        else:
            d = st.get("depth") or 0; paint += exposed / 2 * d + b.area                    # the two long sides + the underside (ends sit on walls)
            notes.append(f"{st['label']} {d:.0f} mm deep")
    return pg.exterior.length, wall, floor, paint, skirt, notes


def quantities(L: float, W: float, H: float, objs: list[dict], openings=(), finishes: dict | None = None, shell: dict | None = None) -> dict:
    """Measured quantities (before waste), each with the basis it came from. With a design concept (finishes) its ceiling, flooring,
    feature wall and decor quantities are used; the feature wall's area is taken off the wall paint."""
    c = mep.ceiling(L, W, H, objs, shell); e = mep.electrical(L, W, H, objs, openings)
    open_area = sum(o["width"] * o["height"] for o in openings); doorways = sum(o["width"] for o in openings if o["kind"] == "DOOR")
    pts = {k: sum(1 for p in e["points"] if p["type"] == k) for k in ("SOCKET", "SWITCH", "SWITCHBOARD", "AC", "LIGHT")}
    tall = [o for o in objs if (o.get("z") or 0) + (o.get("height") or 0) > TALL]     # tall units and wall cabinets hide the wall behind them
    hidden_wall = sum(seg * max(0, min((o.get("z") or 0) + (o.get("height") or 0), H) - (o.get("z") or 0)) for o in tall for seg in _touching(o, L, W))
    hidden_run = sum(seg for o in tall if not (o.get("z") or 0) for seg in _touching(o, L, W))   # only floor-standing units hide the skirting
    perim = 2 * (L + W); wall_area = perim * H; floor_area = L * W; extra_paint = extra_skirt = 0.0; snotes = []
    odd = bool(shell) and (not shp.is_rect(shell.get("shape")) or (shell.get("ceiling") or {}).get("type") not in (None, "FLAT") or shell.get("structures"))
    if odd: perim, wall_area, floor_area, extra_paint, extra_skirt, snotes = _shell_measures(L, W, H, shell)
    walls = max(0.0, wall_area + extra_paint - hidden_wall - open_area)
    shell_note = (" (room outline" + (", sloped/uneven ceiling" if (shell.get("ceiling") or {}).get("type") not in (None, "FLAT") else "")
                  + (", " + ", ".join(snotes) if snotes else "") + ")") if odd else ""
    q = {
        "CEILING_GYPSUM": (c["gypsum_area_m2"], f"{L:.0f} × {W:.0f} mm room" + (" outline" if odd else "")),
        "COVE_STRIP": (c["cove_strip_m"], f"cove {mep.COVE} mm from the walls"),
        "DOWNLIGHT": (sum(1 for x in c["lights"] if x["type"] == "DOWNLIGHT"), "ceiling plan grid"),
        "SPOTLIGHT": (sum(1 for x in c["lights"] if x["type"] == "SPOTLIGHT"), "ceiling plan"),
        "FAN_POINT": (1 if c["fan"] else 0, "ceiling plan"),
        "SOCKET": (pts["SOCKET"], "electrical layout"), "SWITCH": (pts["SWITCH"], "electrical layout"),
        "SWITCHBOARD": (pts["SWITCHBOARD"], "electrical layout"), "AC_POINT": (pts["AC"], "electrical layout"),
        "LIGHT_POINT": (pts["LIGHT"], "electrical layout"),
        "WALL_PAINT": (round(walls / 1e6, 2), (f"walls {perim / 1000:.2f} m × {H / 1000:.2f} m" if not odd else f"walls {perim / 1000:.2f} m round, {wall_area / 1e6:.2f} sq.m"
                                               + (f" + {extra_paint / 1e6:.2f} sq.m columns/beams" if extra_paint else "") + shell_note) + f" − {hidden_wall / 1e6:.2f} sq.m behind tall units"
                                               + (f" − {open_area / 1e6:.2f} sq.m doors/windows" if open_area else "")),
        "FLOORING": (round(floor_area / 1e6, 2), "full floor area" + (" (outline, less columns)" if odd else "")),
        "SKIRTING": (round(max(0.0, perim + extra_skirt - hidden_run - doorways) / 1000, 2), f"perimeter {perim / 1000:.2f} m" + (f" + {extra_skirt / 1000:.2f} m round columns" if extra_skirt else "") + f" − {hidden_run / 1000:.2f} m behind tall units"
                                                                         + (f" − {doorways / 1000:.2f} m doorways" if doorways else "")),
    }
    if finishes:
        from app.services import concept
        cq = concept.quantities(finishes); c2 = finishes.get("ceiling") or {}
        q["CEILING_GYPSUM"] = (c2.get("gypsum_sqm", 0) if c2.get("type") in ("COVE", "ISLAND") else 0, f"concept: {c2.get('label', 'ceiling')}")
        q["COVE_STRIP"] = (c2.get("cove_rm", 0), f"concept: {c2.get('label', 'ceiling')}")
        if c2.get("type") == "GRID": q["CEILING_GRID"] = (round(c["gypsum_area_m2"], 2), "concept: grid ceiling, full room")
        fl = finishes.get("floor") or {}
        if fl.get("kind"): q["FLOORING"] = (0, "replaced by the concept's flooring"); q[f"FLOOR_{fl['kind']}"] = (fl.get("area_sqm", round(L * W / 1e6, 2)), f"concept: {fl.get('label', '')}")
        a = finishes.get("accent")
        if a and a.get("area_sqm"):
            k = f"ACCENT_{a['type']}"
            if k in KEYS: q[k] = (a["area_sqm"], f"concept: {a['wall']} wall {a['from']}–{a['to']} mm × {a['height']} mm")
            pv, pb = q["WALL_PAINT"]; q["WALL_PAINT"] = (round(max(0.0, pv - a["area_sqm"]), 2), pb + f" − {a['area_sqm']} sq.m feature wall")
        for ck, key in CONCEPT_KEY.items():
            if ck in cq and key not in ("COVE_STRIP",): q[key] = (cq[ck], "concept")
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


def plan(db: Session, L: float, W: float, H: float, objs: list[dict], openings=(), finishes: dict | None = None, shell: dict | None = None) -> dict:
    """Priced take-off: lines to add (item + purchase qty in its unit) and what couldn't be added and why."""
    qs, rs = quantities(L, W, H, objs, openings, finishes, shell), rules(db)
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


def for_design(db: Session, room_id: str, objs: list[dict], finishes: dict | None = None) -> dict:
    from app.routers.api import _room_dims, room_openings          # the single source of room dimensions (verified measurements win) + doors/windows
    from app.routers.api import room_shape
    L, W, H = _room_dims(db, room_id)
    return plan(db, L, W, H, objs, room_openings(db, room_id), finishes, room_shape(db, room_id))
