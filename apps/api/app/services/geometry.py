"""Deterministic geometry. The LLM never performs these calculations."""
from dataclasses import dataclass, field
from shapely.geometry import box

@dataclass
class Obj:
    id: str; name: str; category: str
    x: float; y: float; length: float; width: float; height: float = 0
    price: float = 0
    sku: str = ""
    z: float = 0          # height of the object's underside above the floor (wall cabinets, wall-hung units); 0 = stands on the floor

@dataclass
class Room:
    length: float; width: float; ceiling: float = 2750
    doors: list = field(default_factory=list)      # legacy: {"x","y","w","swing"} square swing zones
    openings: list = field(default_factory=list)   # doors/windows: {"kind","wall","offset","width","height","sill","swing","label"}


APPROACH = 450      # every doorway keeps 450 mm clear in front of it (also sliding / outward doors)


def opening_span(room: "Room", o: dict):
    """(x0, y0, x1, y1) of the opening's footprint ON the wall line, plus the inward normal (dx, dy)."""
    a, w, L, W = o["offset"], o["width"], room.length, room.width
    return {"S": ((a, 0, a + w, 0), (0, 1)), "N": ((a, W, a + w, W), (0, -1)), "W": ((0, a, 0, a + w), (1, 0)), "E": ((L, a, L, a + w), (-1, 0))}[o["wall"]]


def door_zones(room: "Room") -> list[tuple[str, object]]:
    """Floor areas that must stay clear: the swing square of inward doors, a 450 mm approach for every door."""
    out = []
    for o in room.openings:
        if o["kind"] != "DOOR": continue
        (x0, y0, x1, y1), (dx, dy) = opening_span(room, o)
        depth = max(o["width"], APPROACH) if (o.get("swing") or "").startswith("INWARD") else APPROACH
        if dx == 0: zone = box(x0, min(y0, y0 + dy * depth), x1, max(y0, y0 + dy * depth))
        else: zone = box(min(x0, x0 + dx * depth), y0, max(x0, x0 + dx * depth), y1)
        out.append((o.get("label") or "door", zone))
    return out

MIN_WALKWAY = 600   # mm
WALL_MOUNTED = 1200  # underside at/above this height: wall-mounted — doesn't take floor space, walkways or working zones
DOOR_HEAD = 2100     # a unit fixed higher than a door's head can't block it
def _rect(o: Obj): return box(o.x, o.y, o.x + o.length, o.y + o.width)
def top(o: Obj) -> float: return (o.z or 0) + (o.height or 0)
def on_floor(o: Obj) -> bool: return (o.z or 0) < WALL_MOUNTED
def stacked_apart(a: Obj, b: Obj) -> bool:
    """True when one is entirely above the other (a wall cabinet over a base unit), so their footprints may overlap."""
    return top(a) <= (b.z or 0) + 0.01 or top(b) <= (a.z or 0) + 0.01
def area_overlap(a, b) -> bool:
    ra, rb = _rect(a), _rect(b); return ra.intersects(rb) and ra.intersection(rb).area > 0

def validate(room: Room, objs: list[Obj]) -> dict:
    errors, warnings, flagged = [], [], set()
    shell = box(0, 0, room.length, room.width)
    for o in objs:
        if not shell.contains(_rect(o)):
            errors.append(f"{o.name}: outside room boundary"); flagged.add(o.id)
        if room.ceiling and top(o) > room.ceiling:
            errors.append(f"{o.name}: taller than ceiling ({top(o):.0f} > {room.ceiling:.0f}mm)"); flagged.add(o.id)
    for i, a in enumerate(objs):
        for b in objs[i + 1:]:
            if area_overlap(a, b) and not stacked_apart(a, b):
                errors.append(f"Collision: {a.name} overlaps {b.name}"); flagged.update((a.id, b.id))
    for label, zone in door_zones(room):          # doors from the room model (swing / approach)
        for o in objs:
            if (o.z or 0) < DOOR_HEAD and zone.intersects(_rect(o)) and zone.intersection(_rect(o)).area > 0:
                errors.append(f"{o.name}: blocks {label} (keep its swing / approach clear)"); flagged.add(o.id)
    for wnd in [x for x in room.openings if x["kind"] == "WINDOW"]:     # tall units standing in front of a window
        (x0, y0, x1, y1), (dx, dy) = opening_span(room, wnd)
        strip = box(x0, min(y0, y0 + dy * 150), x1, max(y0, y0 + dy * 150)) if dx == 0 else box(min(x0, x0 + dx * 150), y0, max(x0, x0 + dx * 150), y1)
        lo, hi = wnd.get("sill", 0), wnd.get("sill", 0) + wnd.get("height", 1200)
        for o in objs:
            if (o.z or 0) < hi and top(o) > lo and strip.intersects(_rect(o)) and strip.intersection(_rect(o)).area > 0:
                warnings.append(f"{o.name}: covers {wnd.get('label') or 'window'} (" + (f"taller than its {lo:.0f} mm sill)" if not o.z else f"fixed across it, {o.z:.0f}–{top(o):.0f} mm)"))
    for d in room.doors:      # door swing clearance (quarter-circle approximated by its bounding square)
        swing = box(d["x"], d["y"], d["x"] + d["w"], d["y"] + d["w"])
        for o in objs:
            if (o.z or 0) < DOOR_HEAD and swing.intersects(_rect(o)) and swing.intersection(_rect(o)).area > 0:
                errors.append(f"{o.name}: blocks door swing"); flagged.add(o.id)
    floor = [o for o in objs if on_floor(o)]      # wall-mounted units don't take floor space
    free = shell
    for o in floor: free = free.difference(_rect(o))
    walk = free.buffer(-MIN_WALKWAY / 2)
    if floor and walk.is_empty:
        warnings.append("No continuous 600mm walkway remains")
    occ = sum(_rect(o).area for o in floor) / shell.area
    if occ > 0.6: warnings.append(f"High furniture occupancy ({occ:.0%})")
    if occ > 0.75: errors.append(f"Furniture occupancy {occ:.0%} too high")
    return {"valid": not errors, "errors": errors, "warnings": warnings,
            "occupancy": round(occ, 3), "flagged": sorted(flagged)}

def place_bedroom(room: Room, catalogue: list[dict]) -> list[Obj]:
    """Rule-based bedroom layout. Tries the bed's headboard on each wall (north first) and the wardrobe in each corner run,
    and keeps the first combination the validator accepts — so doors, windows and walkways are respected. If none is valid,
    returns the preferred layout so the user sees exactly what is wrong."""
    G, L, W = 50, room.length, room.width
    def pick(cat): return next((c for c in catalogue if c["category"].lower() == cat), None)
    bed, war = pick("bed"), pick("wardrobe")
    def B(x, y, l, w): return Obj("bed", bed["name"], "Bed", x, y, l, w, bed["height_mm"], float(bed["price"]), bed.get("sku", ""))
    def R(x, y, l, w): return Obj("wardrobe", war["name"], "Wardrobe", x, y, l, w, war["height_mm"], float(war["price"]), war.get("sku", ""))
    beds, wars = [None], [None]
    if bed:
        bl, bw = bed["length_mm"], bed["width_mm"]
        beds = [B((L - bl) / 2, W - bw - G, bl, bw), B((L - bl) / 2, G, bl, bw), B(G, (W - bl) / 2, bw, bl), B(L - bw - G, (W - bl) / 2, bw, bl)]
    if war:
        wl, ww = war["length_mm"], war["width_mm"]
        wars = [R(G, G, wl, ww), R(L - wl - G, G, wl, ww), R(G, W - ww - G, wl, ww), R(L - wl - G, W - ww - G, wl, ww),
                R(G, G, ww, wl), R(G, W - wl - G, ww, wl), R(L - ww - G, G, ww, wl), R(L - ww - G, W - wl - G, ww, wl)]
    combos = [[o for o in (b, r) if o] for b in beds for r in wars]
    for objs in combos:
        if validate(room, objs)["valid"]: return objs
    return combos[0]
