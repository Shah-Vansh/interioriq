import io
import ezdxf

def _doc():
    d = ezdxf.new("R2010")
    for name, color in [("WALLS", 7), ("FURNITURE", 2), ("DIMENSIONS", 1), ("TEXT", 7)]:
        d.layers.add(name, color=color)
    return d, d.modelspace()

def _bytes(doc) -> bytes:
    buf = io.StringIO(); doc.write(buf); return buf.getvalue().encode()

def _shell(msp, L, W):
    msp.add_lwpolyline([(0, 0), (L, 0), (L, W), (0, W)], close=True, dxfattribs={"layer": "WALLS", "lineweight": 50})
    msp.add_linear_dim(base=(0, -300), p1=(0, 0), p2=(L, 0), dxfattribs={"layer": "DIMENSIONS"}).render()
    msp.add_linear_dim(base=(-300, 0), p1=(0, 0), p2=(0, W), angle=90, dxfattribs={"layer": "DIMENSIONS"}).render()

def floor_plan(name: str, L: float, W: float, openings=()) -> bytes:
    d, m = _doc(); _shell(m, L, W); draw_openings(m, L, W, openings)
    m.add_text(f"{name.upper()}  {L:.0f} x {W:.0f} mm", dxfattribs={"layer": "TEXT", "height": 120, "insert": (L / 2 - 800, W / 2)})
    return _bytes(d)

def furniture_layout(name: str, L: float, W: float, objs: list[dict], openings=()) -> bytes:
    d, m = _doc(); _shell(m, L, W); draw_openings(m, L, W, openings)
    for o in objs:
        x, y, l, w = o["x"], o["y"], o["length"], o["width"]
        from app.services.geometry import corners
        m.add_lwpolyline(corners(o), close=True, dxfattribs={"layer": "FURNITURE"})              # M30: angled units drawn at their angle
        m.add_text(o["name"], dxfattribs={"layer": "TEXT", "height": 70, "insert": (x + 40, y + w / 2)})
    return _bytes(d)

def elevation(name: str, wall_len: float, ceiling: float, objs: list[dict], openings=()) -> bytes:
    d, m = _doc()
    m.add_lwpolyline([(0, 0), (wall_len, 0), (wall_len, ceiling), (0, ceiling)], close=True, dxfattribs={"layer": "WALLS", "lineweight": 50})
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
        # start/end on the wall line and the inward normal
        p0, p1, n = {"S": ((a, 0), (a + w, 0), (0, 1)), "N": ((a, W), (a + w, W), (0, -1)), "W": ((0, a), (0, a + w), (1, 0)), "E": ((L, a), (L, a + w), (-1, 0))}[wall]
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
