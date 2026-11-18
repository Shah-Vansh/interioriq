"""Ceiling and electrical layouts from the saved Design Model (deterministic rules, mm, origin at the room's south-west corner).
These are design-intent drawings for discussion with the client and the electrician — every rule is listed in `rules` and assumptions are flagged."""
import math

COVE = 450               # false-ceiling cove band from each wall
DL_SPACING = 1200        # target downlight spacing
TALL = 1800              # objects taller than this get no downlight above them (light the front instead)


def _nearest_wall(o, L, W):
    d = {"S": o["y"], "N": W - (o["y"] + o["width"]), "W": o["x"], "E": L - (o["x"] + o["length"])}
    return min(d, key=d.get)


def _over(x, y, o, pad=0):
    return o["x"] - pad <= x <= o["x"] + o["length"] + pad and o["y"] - pad <= y <= o["y"] + o["width"] + pad


def ceiling(L, W, H, objs) -> dict:
    tall = [o for o in objs if (o.get("z") or 0) + (o.get("height") or 0) > TALL]
    iL, iW = L - 2 * COVE, W - 2 * COVE
    nx, ny = max(1, round(iL / DL_SPACING)), max(1, round(iW / DL_SPACING))
    lights, skipped = [], 0
    for i in range(nx):
        for j in range(ny):
            x, y = COVE + iL * (i + 0.5) / nx, COVE + iW * (j + 0.5) / ny
            if any(_over(x, y, o, 150) for o in tall): skipped += 1; continue
            lights.append({"type": "DOWNLIGHT", "x": round(x), "y": round(y), "label": "LED downlight 7W"})
    for o in tall:                                    # a light in front of each tall unit (wardrobe) so the shutters are lit
        wall = _nearest_wall(o, L, W); cx, cy = o["x"] + o["length"] / 2, o["y"] + o["width"] / 2
        off = {"S": (cx, o["y"] + o["width"] + 450), "N": (cx, o["y"] - 450), "W": (o["x"] + o["length"] + 450, cy), "E": (o["x"] - 450, cy)}[wall]
        lights.append({"type": "SPOTLIGHT", "x": round(off[0]), "y": round(off[1]), "label": f"Spot to light {o['name']}"})
    fan = (L / 2, W / 2)
    if any(_over(fan[0], fan[1], o, 300) for o in tall): fan = None
    return {"room": {"L": L, "W": W, "H": H}, "false_ceiling_height": H - 300, "cove": COVE,
            "gypsum_area_m2": round(L * W / 1e6, 2), "cove_strip_m": round(2 * (iL + iW) / 1000, 2),
            "lights": lights, "fan": None if fan is None else {"x": round(fan[0]), "y": round(fan[1])},
            "rules": [f"False ceiling 300 mm below the slab, {COVE} mm cove band with LED strip on all walls.",
                      f"Downlights on a ~{DL_SPACING} mm grid inside the cove ({nx}×{ny}); {skipped} skipped above tall units.",
                      "One spotlight 450 mm in front of every unit taller than 1800 mm.", "Fan point at the room centre unless a tall unit is there."]}


def _on_wall(wall, along, L, W):
    """Point `along` mm along a wall (plan offset convention) → plan (x, y)."""
    return {"S": (along, 0), "N": (along, W), "W": (0, along), "E": (L, along)}[wall]


def electrical(L, W, H, objs, openings=()) -> dict:
    pts, n = [], [0]
    def add(kind, label, x, y, h, note=""):
        n[0] += 1; pts.append({"id": f"E{n[0]}", "type": kind, "label": label, "x": round(x), "y": round(y), "height": h, "note": note})
    door = next((o for o in openings if o["kind"] == "DOOR"), None)
    if door:
        wall_len = L if door["wall"] in ("N", "S") else W
        along = door["offset"] + door["width"] + 150 if door["offset"] + door["width"] + 300 <= wall_len else door["offset"] - 150
        sx, sy = _on_wall(door["wall"], along, L, W)
        add("SWITCHBOARD", f"Main switchboard (lights, fan, AC) beside {door['label']}", sx, sy, 1200, "")
    else:
        add("SWITCHBOARD", "Main switchboard (lights, fan, AC)", 150, 0, 1200, "ASSUMED at the entrance on the south wall — no door is recorded for this room (Survey → Rooms); confirm on site.")
    ac_done = kitchen = False
    for o in objs:
        cat = (o.get("category") or "").lower(); x, y, l, w = o["x"], o["y"], o["length"], o["width"]
        wall = _nearest_wall(o, L, W)
        if cat == "bed":
            if wall in ("N", "S"):
                hy = y + w if wall == "N" else y
                add("SOCKET", "Bedside 5A + USB socket (left)", x - 150, hy, 450); add("SOCKET", "Bedside 5A + USB socket (right)", x + l + 150, hy, 450)
                add("SWITCH", "2-way light switch at bed", x + l + 150, hy, 900)
                add("AC", "AC point (16A) above headboard", x + l / 2, hy, 2100); ac_done = True
            else:
                hx = x if wall == "W" else x + l
                add("SOCKET", "Bedside 5A + USB socket (left)", hx, y - 150, 450); add("SOCKET", "Bedside 5A + USB socket (right)", hx, y + w + 150, 450)
                add("SWITCH", "2-way light switch at bed", hx, y + w + 150, 900)
                add("AC", "AC point (16A) above headboard", hx, y + w / 2, 2100); ac_done = True
        elif cat == "wardrobe":
            add("LIGHT", "Wardrobe internal profile light + door sensor", x + l / 2, y + w / 2, max(0, (o.get("height") or 2100) - 100))
        elif cat in ("study", "desk"):
            add("SOCKET", "2 × 6A sockets + data point above desk", x + l / 2, y + w / 2, 900)
        elif cat == "tv unit":
            add("SOCKET", "TV point: 3 × 6A + HDMI/data", x + l / 2, y + w / 2, 1100)
        elif cat == "sofa":
            add("SOCKET", "6A socket at sofa end", x + l + 150, y + w / 2, 300)
        elif cat in ("dining", "dining table"):
            add("LIGHT", "Pendant point over dining table", x + l / 2, y + w / 2, H)
        elif cat == "kitchen":
            kitchen = True
            if (o.get("height") or 0) >= 1800: add("SOCKET", "16A socket for fridge / appliance (tall unit)", x + l / 2, y + w / 2, 300)
            else: add("SOCKET", "6/16A counter socket", x + l / 2, y + w / 2, 1100)
        elif cat == "kitchen sink":
            kitchen = True; add("SOCKET", "6A socket under the sink (RO / dishwasher)", x + l / 2, y + w / 2, 300)
        elif cat == "kitchen hob":
            kitchen = True; add("SOCKET", "Chimney point (6A) above the hob", x + l / 2, y + w / 2, 2100); add("SOCKET", "16A hob point (induction)", x + l / 2, y + w / 2, 300)
        elif cat == "kitchen wall":
            kitchen = True; add("LIGHT", "Under-cabinet LED strip", x + l / 2, y + w / 2, round(o.get("z") or 1450))
    hob = any((o.get("category") or "").lower() == "kitchen hob" for o in objs)
    if kitchen and not hob:
        base = [o for o in objs if (o.get("category") or "").lower() == "kitchen" and (o.get("height") or 0) < 1800]
        if base:
            o = max(base, key=lambda b: b["length"] * b["width"]); add("SOCKET", "Chimney point (6A) above the hob", o["x"] + o["length"] / 2, o["y"] + o["width"] / 2, 2100)
    if not kitchen and not ac_done: add("AC", "AC point (16A)", L / 2, W, 2100, "No bed in the design: placed on the north wall centre.")
    return {"room": {"L": L, "W": W, "H": H}, "points": pts,
            "rules": ["Heights are to the centre of the plate from finished floor.", "Bedside sockets 150 mm beyond each side of the bed at 450 mm; 2-way switch at 900 mm.",
                      "AC point at 2100 mm on the headboard wall (else north wall).", "Wardrobes get an internal profile light; desks 2 sockets + data at 900 mm; TV units a TV point at 1100 mm.",
                      "Kitchens: a counter socket at 1100 mm per base unit, a 16A appliance socket at 300 mm per tall unit, chimney (2100) + 16A hob point over the hob unit, a socket under the sink, an LED strip under each wall cabinet; no AC point."],
            "assumptions": [p["note"] for p in pts if p["note"].startswith("ASSUMED")]}


def elevations(L, W, H, objs, openings=()) -> list[dict]:
    """Objects within 100 mm of a wall, projected onto it as seen from inside the room (left → right)."""
    walls = {"NORTH": L, "EAST": W, "SOUTH": L, "WEST": W}
    out = []
    for name, length in walls.items():
        items = []
        for o in objs:
            x, y, l, w, h, z = o["x"], o["y"], o["length"], o["width"], o.get("height") or 0, o.get("z") or 0
            if name == "NORTH" and W - (y + w) <= 100: pos, ext = x, l
            elif name == "SOUTH" and y <= 100: pos, ext = L - (x + l), l
            elif name == "WEST" and x <= 100: pos, ext = y, w
            elif name == "EAST" and L - (x + l) <= 100: pos, ext = W - (y + w), w
            else: continue
            items.append({"name": o["name"], "category": o.get("category"), "x": round(pos), "length": round(ext), "height": round(h), "z": round(z)})
        ops = []
        for op in openings:
            if op["wall"] != name[0]: continue
            a, w = op["offset"], op["width"]
            pos = {"NORTH": a, "SOUTH": L - (a + w), "WEST": a, "EAST": W - (a + w)}[name]     # as seen from inside, left → right
            ops.append({"label": op["label"], "kind": op["kind"], "x": round(pos), "width": round(w), "height": round(op["height"]), "sill": round(op.get("sill") or 0)})
        out.append({"wall": name, "length": round(length), "height": round(H), "items": sorted(items, key=lambda i: i["x"]), "openings": sorted(ops, key=lambda i: i["x"])})
    return out


def dxf(kind: str, data, L, W, openings=()) -> bytes:
    from app.services import cad
    d, msp = cad._doc(); cad._shell(msp, L, W); cad.draw_openings(msp, L, W, openings)
    if kind == "ceiling":
        c = COVE; msp.add_lwpolyline([(c, c), (L - c, c), (L - c, W - c), (c, W - c)], close=True, dxfattribs={"layer": "CEILING"})
        for p in data["lights"]:
            msp.add_circle((p["x"], p["y"]), 60 if p["type"] == "DOWNLIGHT" else 80, dxfattribs={"layer": "LIGHTS"})
        if data["fan"]: msp.add_circle((data["fan"]["x"], data["fan"]["y"]), 150, dxfattribs={"layer": "LIGHTS"})
    else:
        for p in data["points"]:
            msp.add_circle((p["x"], p["y"]), 50, dxfattribs={"layer": "ELECTRICAL"})
            msp.add_text(f"{p['id']} {p['label']} @{p['height']}", dxfattribs={"layer": "TEXT", "height": 50, "insert": (p["x"] + 70, p["y"] + 20)})
    return cad._bytes(d)
