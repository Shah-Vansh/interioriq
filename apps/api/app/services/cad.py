import io
import ezdxf

def _doc():
    d = ezdxf.new("R2010")
    for name, color in [("WALLS", 7), ("FURNITURE", 2), ("DIMENSIONS", 1), ("TEXT", 7), ("STRUCTURE", 8), ("BEAMS", 5)]:
        d.layers.add(name, color=color)
    if "DASHED" not in d.linetypes: d.linetypes.add("DASHED", pattern=[12.0, 6.0, -6.0], description="Dashed __ __ __")
    return d, d.modelspace()

def _bytes(doc) -> bytes:
    buf = io.StringIO(); doc.write(buf); return buf.getvalue().encode()

def _shell(msp, L, W, shell=None):
    """Walls: the room outline (M41: L-shaped / angled rooms) with every wall's length dimensioned; overall L x W."""
    pts = [tuple(p) for p in (shell or {}).get("outline") or [(0, 0), (L, 0), (L, W), (0, W)]]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALLS", "lineweight": 50})
    msp.add_linear_dim(base=(0, -300), p1=(0, 0), p2=(L, 0), dxfattribs={"layer": "DIMENSIONS"}).render()
    msp.add_linear_dim(base=(-300, 0), p1=(0, 0), p2=(0, W), angle=90, dxfattribs={"layer": "DIMENSIONS"}).render()
    if len(pts) > 4:                                                     # each wall of an odd room, measured along the wall
        for a, b in zip(pts, pts[1:] + pts[:1]):
            msp.add_aligned_dim(p1=a, p2=b, distance=-180, dxfattribs={"layer": "DIMENSIONS"}).render()


def beam_underside(shell: dict, s: dict) -> float:
    from shapely.geometry import box
    from app.services import shape as shp
    cp = shell.get("ceiling") if (shell.get("ceiling") or {}).get("type") not in (None, "FLAT") else None
    return shp.lowest_over(cp, shell.get("H") or 2750, shell.get("L") or 1, shell.get("W") or 1,
                           box(s["x"], s["y"], s["x"] + s["length"], s["y"] + s["width"])) - (s.get("depth") or 0)


def draw_structures(msp, shell):
    """Columns / pillars: box with a cross (floor to ceiling). Beams / ceiling drops: dashed box + size + underside height."""
    if not shell: return
    for s in shell.get("structures") or []:
        x, y, l, w = s["x"], s["y"], s["length"], s["width"]
        box_ = [(x, y), (x + l, y), (x + l, y + w), (x, y + w)]
        if s["kind"] in ("COLUMN", "PILLAR"):
            msp.add_lwpolyline(box_, close=True, dxfattribs={"layer": "STRUCTURE", "lineweight": 35})
            msp.add_line((x, y), (x + l, y + w), dxfattribs={"layer": "STRUCTURE"}); msp.add_line((x, y + w), (x + l, y), dxfattribs={"layer": "STRUCTURE"})
            msp.add_text(f"{s['label']} {l:.0f}x{w:.0f}", dxfattribs={"layer": "TEXT", "height": 50, "insert": (x, y + w + 40)})
        else:
            msp.add_lwpolyline(box_, close=True, dxfattribs={"layer": "BEAMS", "linetype": "DASHED"})
            msp.add_text(f"{s['label']} {min(l, w):.0f} wide x {s.get('depth') or 0:.0f} deep, underside {beam_underside(shell, s):.0f}",
                         dxfattribs={"layer": "TEXT", "height": 50, "insert": (x + 40, y + w / 2), "rotation": 90 if w > l else 0})


def floor_plan(name: str, L: float, W: float, openings=(), shell=None) -> bytes:
    d, m = _doc(); _shell(m, L, W, shell); draw_openings(m, L, W, openings); draw_structures(m, shell)
    m.add_text(f"{name.upper()}  {L:.0f} x {W:.0f} mm", dxfattribs={"layer": "TEXT", "height": 120, "insert": (L / 2 - 800, W / 2)})
    return _bytes(d)

def furniture_layout(name: str, L: float, W: float, objs: list[dict], openings=(), shell=None) -> bytes:
    d, m = _doc(); _shell(m, L, W, shell); draw_openings(m, L, W, openings); draw_structures(m, shell)
    for o in objs:
        x, y, l, w = o["x"], o["y"], o["length"], o["width"]
        from app.services.geometry import corners
        m.add_lwpolyline(corners(o), close=True, dxfattribs={"layer": "FURNITURE"})              # M30: angled units drawn at their angle
        m.add_text(o["name"], dxfattribs={"layer": "TEXT", "height": 70, "insert": (x + 40, y + w / 2)})
    return _bytes(d)

def elevation(name: str, wall_len: float, ceiling: float, objs: list[dict], openings=(), e: dict | None = None) -> bytes:
    d, m = _doc()
    top = [tuple(p) for p in (e or {}).get("ceiling_line") or [(0, ceiling), (wall_len, ceiling)]]   # M41: sloped / uneven ceiling line
    m.add_lwpolyline([(0, 0), (wall_len, 0)] + top[::-1], close=True, dxfattribs={"layer": "WALLS", "lineweight": 50})
    for s in (e or {}).get("structures") or []:                       # beams / drops meeting this wall, columns against it
        x, w, z = s["x"], s["width"], s["z"]
        h = max(hh for _, hh in top)
        m.add_lwpolyline([(x, z), (x + w, z), (x + w, h), (x, h)], close=True, dxfattribs={"layer": "STRUCTURE" if s["kind"] in ("COLUMN", "PILLAR") else "BEAMS"})
        m.add_text(s["label"] + ("" if s["kind"] in ("COLUMN", "PILLAR") else f" u/s {z:.0f}"), dxfattribs={"layer": "TEXT", "height": 60, "insert": (x + 20, z - 90 if z else 60)})
    for o in objs:
        x, l, z = o["x"], o["length"], o.get("z") or 0; h = z + o["height"]
        m.add_lwpolyline([(x, z), (x + l, z), (x + l, h), (x, h)], close=True, dxfattribs={"layer": "FURNITURE"})
        m.add_text(o["name"], dxfattribs={"layer": "TEXT", "height": 70, "insert": (x + 40, h + 60)})
    for op in openings or ():
        x, w, b, h = op["x"], op["width"], op.get("sill", 0), op["height"]
        m.add_lwpolyline([(x, b), (x + w, b), (x + w, b + h), (x, b + h)], close=True, dxfattribs={"layer": "DOORS" if op["kind"] == "DOOR" else "WINDOWS"})
    m.add_linear_dim(base=(-300, 0), p1=(-100, 0), p2=(-100, ceiling), angle=90, dxfattribs={"layer": "DIMENSIONS"}).render()
    return _bytes(d)



def draw_openings(msp, L, W, openings):
    """DOORS: leaf + 90° swing arc for inward doors (a line across for sliding/outward). WINDOWS: two parallel lines in the wall."""
    for o in openings or ():
        a, w, wall = o["offset"], o["width"], o["wall"]
        # start/end on the wall line and the inward normal (M41: resolved openings carry them - any wall, incl. angled ones)
        if "x0" in o: p0, p1, n = (o["x0"], o["y0"]), (o["x1"], o["y1"]), (o["nx"], o["ny"])
        else: p0, p1, n = {"S": ((a, 0), (a + w, 0), (0, 1)), "N": ((a, W), (a + w, W), (0, -1)), "W": ((0, a), (0, a + w), (1, 0)), "E": ((L, a), (L, a + w), (-1, 0))}[wall]
        if o["kind"] == "WINDOW":
            msp.add_line(p0, p1, dxfattribs={"layer": "WINDOWS"})
            msp.add_line((p0[0] + n[0] * 100, p0[1] + n[1] * 100), (p1[0] + n[0] * 100, p1[1] + n[1] * 100), dxfattribs={"layer": "WINDOWS"})
        else:
            hinge, other = (p1, p0) if o.get("swing") == "INWARD_RIGHT" else (p0, p1)
            if (o.get("swing") or "").startswith("INWARD"):
                leaf_end = (hinge[0] + n[0] * w, hinge[1] + n[1] * w)
                msp.add_line(hinge, leaf_end, dxfattribs={"layer": "DOORS"})
                import math
                a0 = math.degrees(math.atan2(other[1] - hinge[1], other[0] - hinge[0])); a1 = math.degrees(math.atan2(n[1], n[0]))
                lo, hi = (a0, a1) if (a1 - a0) % 360 <= 180 else (a1, a0)
                msp.add_arc(hinge, w, lo, hi, dxfattribs={"layer": "DOORS"})
            else:
                msp.add_line(p0, p1, dxfattribs={"layer": "DOORS"})
        msp.add_text(o.get("label") or o["kind"].title(), dxfattribs={"layer": "TEXT", "height": 60, "insert": ((p0[0] + p1[0]) / 2 + n[0] * 150, (p0[1] + p1[1]) / 2 + n[1] * 150)})
