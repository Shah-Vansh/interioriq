"""Whole-home plan: every room of a project placed on one house plan (mm; x = east, y = north, origin at the south-west corner of the
plot), so the home can be drawn, exported and viewed in 3D as one. Each room keeps its own rectangle and its own design; the plan only
adds where the room sits. Rooms are separated by walls, so neighbours should be one wall thickness apart (auto-arrange does this);
real overlaps are reported, touching is fine.

Zoning used by auto-arrange (front of the house → back): entrance / verandah / foyer → living / dining / kitchen / wash area →
bedrooms / bathrooms / study / pooja / store. Inside a zone the biggest rooms go first, rows fill west → east."""
import io
import math

import ezdxf

from app.models import models as m
from app.services import cad, geometry

WALL = 150                       # gap left between rooms for the wall between them (mm)
ZONE = {"VERANDAH": 0, "BALCONY": 0, "FOYER": 0, "PASSAGE": 1, "LIVING": 1, "DINING": 1, "KITCHEN": 1, "WASH_AREA": 1, "UTILITY": 1,
        "MASTER_BEDROOM": 2, "BEDROOM": 2, "KIDS_BEDROOM": 2, "GUEST_BEDROOM": 2, "BATHROOM": 2, "STUDY": 2, "POOJA": 2, "STORE": 2}
ROOM_TYPES = ["FOYER", "LIVING", "DINING", "KITCHEN", "WASH_AREA", "UTILITY", "MASTER_BEDROOM", "BEDROOM", "KIDS_BEDROOM", "GUEST_BEDROOM",
              "BATHROOM", "STUDY", "POOJA", "STORE", "PASSAGE", "VERANDAH", "BALCONY", "OTHER"]


def dims(db, room: m.Room):
    ms = {x.label.lower(): x.value for x in db.query(m.Measurement).filter_by(room_id=room.id)}
    get = lambda k: next((v for kk, v in ms.items() if k in kk), None)
    L, W = get("length"), get("width")
    return (L, W, get("ceiling") or 2750) if L and W else None


def boxes(db, pid: str) -> list[dict]:
    out = []
    for r in db.query(m.Room).filter_by(project_id=pid).order_by(m.Room.name):
        d = dims(db, r)
        out.append({"id": r.id, "name": r.name, "room_type": r.room_type, "x": r.plan_x, "y": r.plan_y, "level": r.level or 0,
                    "L": d[0] if d else None, "W": d[1] if d else None, "H": d[2] if d else None, "placed": r.plan_x is not None and r.plan_y is not None})
    return out


def overlaps(rows: list[dict]) -> list[str]:
    bad = []
    rs = [r for r in rows if r["placed"] and r["L"]]
    for i, a in enumerate(rs):
        for b in rs[i + 1:]:
            if (a["level"] or 0) != (b["level"] or 0): continue
            ox = min(a["x"] + a["L"], b["x"] + b["L"]) - max(a["x"], b["x"]); oy = min(a["y"] + a["W"], b["y"] + b["W"]) - max(a["y"], b["y"])
            if ox > 1 and oy > 1: bad.append(f"{a['name']} overlaps {b['name']} by {ox:.0f} × {oy:.0f} mm")
            elif (ox > 1 and -WALL + 1 < oy <= 1) or (oy > 1 and -WALL + 1 < ox <= 1):
                bad.append(f"{a['name']} and {b['name']} are closer than a wall ({WALL} mm) — leave room for the wall between them")
    return bad


def arrange(rows: list[dict], only_unplaced: bool = True) -> dict:
    """{room id: (x, y)} for rooms to place. Rows of rooms by zone; row width ≈ 1.6 × √(total area) (a sensible plot shape)."""
    todo = [r for r in rows if r["L"] and (not only_unplaced or not r["placed"])]
    if not todo: return {}
    fixed = [r for r in rows if r["placed"] and r["L"] and r not in todo]
    y0 = max((r["y"] + r["W"] for r in fixed), default=-WALL) + WALL
    width = 1.6 * math.sqrt(sum(r["L"] * r["W"] for r in todo + fixed))
    out = {}; x = 0.0; row_h = 0.0; y = y0
    for r in sorted(todo, key=lambda r: (ZONE.get((r["room_type"] or "").upper(), 2), -(r["L"] * r["W"]))):
        if x > 0 and x + r["L"] > width: y += row_h + WALL; x = 0.0; row_h = 0.0
        out[r["id"]] = (round(x / 50) * 50, round(y / 50) * 50); x += r["L"] + WALL; row_h = max(row_h, r["W"])
    return out


def house_dxf(db, pid: str, project_name: str) -> bytes:
    """One DXF of the whole home: each room = a block (walls, openings, furniture of its latest design, name + size) inserted at its plan
    position, plus overall dimensions."""
    from app.routers.api import room_openings, room_shape                         # one place builds openings + the room shell
    from shapely.geometry import Polygon
    d = ezdxf.new("R2010"); msp = d.modelspace()
    for n, c in (("WALLS", 7), ("FURNITURE", 2), ("DOORS", 3), ("WINDOWS", 4), ("DIMENSIONS", 1), ("TEXT", 7), ("STRUCTURE", 8), ("BEAMS", 5)): d.layers.add(n, color=c)
    d.linetypes.add("DASHED", pattern=[12.0, 6.0, -6.0], description="Dashed __ __ __")
    rows = [r for r in boxes(db, pid) if r["placed"] and r["L"]]
    for i, r in enumerate(rows):
        blk = d.blocks.new(name=f"ROOM_{i + 1}")
        sh = room_shape(db, r["id"]); pts = [tuple(p) for p in sh["outline"]]                 # M41: L-shaped / angled rooms
        blk.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALLS", "lineweight": 50})
        blk.add_lwpolyline([(round(x), round(y)) for x, y in list(Polygon(pts).buffer(115, join_style=2).exterior.coords)[:-1]], close=True, dxfattribs={"layer": "WALLS"})
        cad.draw_openings(blk, r["L"], r["W"], room_openings(db, r["id"])); cad.draw_structures(blk, sh)
        des = db.query(m.Design).filter_by(room_id=r["id"]).order_by(m.Design.version.desc()).first()
        for o in (des.design_json.get("objects", []) if des else []):
            blk.add_lwpolyline(geometry.corners(o), close=True, dxfattribs={"layer": "FURNITURE"})
        blk.add_text(r["name"].upper(), dxfattribs={"layer": "TEXT", "height": 160, "insert": (r["L"] / 2 - len(r["name"]) * 50, r["W"] / 2 + 100)})
        blk.add_text(f"{r['L']:.0f} x {r['W']:.0f}", dxfattribs={"layer": "TEXT", "height": 100, "insert": (r["L"] / 2 - 350, r["W"] / 2 - 120)})
        msp.add_blockref(blk.name, (r["x"], r["y"]))
    if rows:
        x0, y0 = min(r["x"] for r in rows) - 115, min(r["y"] for r in rows) - 115
        x1, y1 = max(r["x"] + r["L"] for r in rows) + 115, max(r["y"] + r["W"] for r in rows) + 115
        msp.add_linear_dim(base=(x0, y0 - 700), p1=(x0, y0), p2=(x1, y0), dxfattribs={"layer": "DIMENSIONS"}).render()
        msp.add_linear_dim(base=(x0 - 700, y0), p1=(x0, y0), p2=(x0, y1), angle=90, dxfattribs={"layer": "DIMENSIONS"}).render()
        msp.add_text(f"{project_name.upper()} - HOME PLAN", dxfattribs={"layer": "TEXT", "height": 250, "insert": (x0, y1 + 500)})
    buf = io.StringIO(); d.write(buf); return buf.getvalue().encode("utf-8")
