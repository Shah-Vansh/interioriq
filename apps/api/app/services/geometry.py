"""Deterministic geometry. The LLM never performs these calculations."""
from dataclasses import dataclass, field
from shapely import affinity
from shapely.geometry import LineString, Polygon, box

from app.services import shape as shp

@dataclass
class Obj:
    id: str; name: str; category: str
    x: float; y: float; length: float; width: float; height: float = 0
    price: float = 0
    sku: str = ""
    z: float = 0          # height of the object's underside above the floor (wall cabinets, wall-hung units); 0 = stands on the floor
    rotation: float = 0   # M30: degrees anticlockwise (seen from above) about the footprint centre; x/y/length/width describe the UNROTATED box

@dataclass
class Room:
    length: float; width: float; ceiling: float = 2750
    doors: list = field(default_factory=list)      # legacy: {"x","y","w","swing"} square swing zones
    openings: list = field(default_factory=list)   # doors/windows: {"kind","wall","offset","width","height","sill","swing","label"} (+ x0,y0,x1,y1,nx,ny)
    shape: dict | None = None                      # M41: room outline (shape.py) — None = the L × W rectangle
    ceiling_profile: dict | None = None            # M41: sloped / uneven ceiling — None = flat at `ceiling`
    structures: list = field(default_factory=list) # M41: {"kind": BEAM|COLUMN|PILLAR|CEILING_DROP, "x","y","length","width","depth","label"}

    _poly: object = field(default=None, repr=False, compare=False)

    def poly(self):
        if self._poly is None: self._poly = shp.polygon(self.length, self.width, self.shape)
        return self._poly
    def ceiling_over(self, poly) -> float:
        """Lowest ceiling over a footprint: the profile (flat / sloped / uneven) — beams and drops are checked separately (named errors)."""
        return shp.lowest_over(self.ceiling_profile, self.ceiling, self.length, self.width, poly) if self.ceiling_profile else self.ceiling
    def solid(self):  # columns / pillars: floor to ceiling
        return [s for s in self.structures if s["kind"] in ("COLUMN", "PILLAR")]
    def overhead(self):  # beams / ceiling drops: hang below the ceiling
        return [s for s in self.structures if s["kind"] in ("BEAM", "CEILING_DROP")]
    def underside(self, s: dict) -> float:
        return self.ceiling_over(box(s["x"], s["y"], s["x"] + s["length"], s["y"] + s["width"])) - (s.get("depth") or 0)
    def blocked(self, poly, z: float, top_: float) -> str | None:
        """Why a footprint `poly` occupying heights z..top_ can't be there (outline, ceiling, structures) — None = fine."""
        if not self.poly().buffer(0.5).contains(poly): return "outside room boundary"
        if self.ceiling and top_ > self.ceiling_over(poly) + 0.5:
            return (f"taller than the ceiling here ({top_:.0f} > {self.ceiling_over(poly):.0f}mm, {self.ceiling_profile['type'].lower()} ceiling)" if self.ceiling_profile
                    else f"taller than ceiling ({top_:.0f} > {self.ceiling:.0f}mm)")
        for s in self.solid():
            r = box(s["x"], s["y"], s["x"] + s["length"], s["y"] + s["width"])
            if r.intersects(poly) and r.intersection(poly).area > 1: return f"hits {s.get('label') or s['kind'].lower()}"
        for s in self.overhead():
            r = box(s["x"], s["y"], s["x"] + s["length"], s["y"] + s["width"])
            if r.intersects(poly) and r.intersection(poly).area > 1 and top_ > self.underside(s) + 0.5:
                return f"hits {s.get('label') or s['kind'].lower().replace('_', ' ')} (underside {self.underside(s):.0f}mm)"
        return None


APPROACH = 450      # every doorway keeps 450 mm clear in front of it (also sliding / outward doors)


def opening_span(room: "Room", o: dict):
    """(x0, y0, x1, y1) of the opening's footprint ON the wall line, plus the inward normal (dx, dy). Resolved openings (M41: any wall,
    incl. the inner walls of an L-shaped room and angled walls) carry their own end points."""
    if "x0" in o: return (o["x0"], o["y0"], o["x1"], o["y1"]), (o["nx"], o["ny"])
    a, w, L, W = o["offset"], o["width"], room.length, room.width
    return {"S": ((a, 0, a + w, 0), (0, 1)), "N": ((a, W, a + w, W), (0, -1)), "W": ((0, a, 0, a + w), (1, 0)), "E": ((L, a, L, a + w), (-1, 0))}[o["wall"]]


def strip(span, normal, depth):
    """The floor strip `depth` mm deep in front of a wall span (works for angled walls too)."""
    (x0, y0, x1, y1), (dx, dy) = span, normal
    return Polygon([(x0, y0), (x1, y1), (x1 + dx * depth, y1 + dy * depth), (x0 + dx * depth, y0 + dy * depth)])


def door_zones(room: "Room") -> list[tuple[str, object]]:
    """Floor areas that must stay clear: the swing square of inward doors, a 450 mm approach for every door."""
    out = []
    for o in room.openings:
        if o["kind"] != "DOOR": continue
        span, n = opening_span(room, o)
        depth = max(o["width"], APPROACH) if (o.get("swing") or "").startswith("INWARD") else APPROACH
        out.append((o.get("label") or "door", strip(span, n, depth)))
    return out

MIN_WALKWAY = 600   # mm
WALL_MOUNTED = 1200  # underside at/above this height: wall-mounted — doesn't take floor space, walkways or working zones
DOOR_HEAD = 2100     # a unit fixed higher than a door's head can't block it
def footprint(x: float, y: float, length: float, width: float, rotation: float = 0):
    """The floor footprint as a polygon — an axis-aligned box, turned about its centre when rotation isn't a multiple of 360."""
    b = box(x, y, x + length, y + width)
    r = (rotation or 0) % 360
    return b if r == 0 else affinity.rotate(b, r, origin="center")
def corners(o: dict) -> list[tuple[float, float]]:
    """Footprint corners of a saved object (dict) — for drawings."""
    return list(footprint(o["x"], o["y"], o["length"], o["width"], o.get("rotation") or 0).exterior.coords)[:4]
def _rect(o: Obj): return footprint(o.x, o.y, o.length, o.width, o.rotation)
def top(o: Obj) -> float: return (o.z or 0) + (o.height or 0)
def on_floor(o: Obj) -> bool: return (o.z or 0) < WALL_MOUNTED
def stacked_apart(a: Obj, b: Obj) -> bool:
    """True when one is entirely above the other (a wall cabinet over a base unit), so their footprints may overlap."""
    return top(a) <= (b.z or 0) + 0.01 or top(b) <= (a.z or 0) + 0.01
def area_overlap(a, b) -> bool:
    ra, rb = _rect(a), _rect(b); return ra.intersects(rb) and ra.intersection(rb).area > 0

def validate(room: Room, objs: list[Obj]) -> dict:
    errors, warnings, flagged = [], [], set()
    shell = room.poly()
    for o in objs:
        why = room.blocked(_rect(o), o.z or 0, top(o))
        if why: errors.append(f"{o.name}: {why}"); flagged.add(o.id)
    for i, a in enumerate(objs):
        for b in objs[i + 1:]:
            if area_overlap(a, b) and not stacked_apart(a, b):
                errors.append(f"Collision: {a.name} overlaps {b.name}"); flagged.update((a.id, b.id))
    for label, zone in door_zones(room):          # doors from the room model (swing / approach)
        for o in objs:
            if (o.z or 0) < DOOR_HEAD and zone.intersects(_rect(o)) and zone.intersection(_rect(o)).area > 0:
                errors.append(f"{o.name}: blocks {label} (keep its swing / approach clear)"); flagged.add(o.id)
    for wnd in [x for x in room.openings if x["kind"] == "WINDOW"]:     # tall units standing in front of a window
        sp, n = opening_span(room, wnd); zone = strip(sp, n, 150)
        lo, hi = wnd.get("sill", 0), wnd.get("sill", 0) + wnd.get("height", 1200)
        for o in objs:
            if (o.z or 0) < hi and top(o) > lo and zone.intersects(_rect(o)) and zone.intersection(_rect(o)).area > 0:
                warnings.append(f"{o.name}: covers {wnd.get('label') or 'window'} (" + (f"taller than its {lo:.0f} mm sill)" if not o.z else f"fixed across it, {o.z:.0f}–{top(o):.0f} mm)"))
    for d in room.doors:      # door swing clearance (quarter-circle approximated by its bounding square)
        swing = box(d["x"], d["y"], d["x"] + d["w"], d["y"] + d["w"])
        for o in objs:
            if (o.z or 0) < DOOR_HEAD and swing.intersects(_rect(o)) and swing.intersection(_rect(o)).area > 0:
                errors.append(f"{o.name}: blocks door swing"); flagged.add(o.id)
    floor = [o for o in objs if on_floor(o)]      # wall-mounted units don't take floor space
    free = shell
    for s in room.solid(): free = free.difference(box(s["x"], s["y"], s["x"] + s["length"], s["y"] + s["width"]))
    for o in floor: free = free.difference(_rect(o))
    walk = free.buffer(-MIN_WALKWAY / 2)
    if floor and walk.is_empty:
        warnings.append("No continuous 600mm walkway remains")
    usable = shell.area - sum(shell.intersection(box(s["x"], s["y"], s["x"] + s["length"], s["y"] + s["width"])).area for s in room.solid())
    occ = sum(_rect(o).area for o in floor) / max(1.0, usable)
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
