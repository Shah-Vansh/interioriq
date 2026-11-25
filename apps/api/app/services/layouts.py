"""Rule-based layouts for every common room type: bedroom, living, dining, kitchen, study, bathroom, utility.

Deterministic interior rules, no LLM (constraint 2). Each planner proposes positions from simple rules (against a wall, facing pairs,
clearances in front of units, chairs around a table, counter runs), every proposal is checked incrementally (inside the room, under the
ceiling, no overlap, keeps door swings / approaches clear, keeps every unit's working zone clear) and the finished layout goes through
geometry.validate — the same check the 3D editor and the BOQ use. Items come ONLY from the catalogue; a missing category is reported,
never invented.

Conventions (same as the 3D editor): x along the room length (west → east), y along the width (south → north), objects axis-aligned;
an item's catalogue length_mm runs along the wall it stands against, width_mm is its depth."""
from dataclasses import dataclass, field

from decimal import Decimal

from shapely.geometry import box
from shapely.ops import unary_union

from .cost_engine import inr

from .geometry import DOOR_HEAD, WALL_MOUNTED, Obj, Room, area_overlap, door_zones, on_floor, stacked_apart, top, validate

G = 50                               # gap left between a unit and the wall
ROOM_KIND = {"MASTER_BEDROOM": "BEDROOM", "BEDROOM": "BEDROOM", "KIDS_BEDROOM": "BEDROOM", "GUEST_BEDROOM": "BEDROOM",
             "LIVING": "LIVING", "DINING": "DINING", "KITCHEN": "KITCHEN", "STUDY": "STUDY", "BATHROOM": "BATHROOM", "TOILET": "BATHROOM",
             "UTILITY": "UTILITY", "LAUNDRY": "UTILITY", "WASH_AREA": "UTILITY",
             "VERANDAH": "OUTDOOR", "BALCONY": "OUTDOOR", "FOYER": "FOYER", "PASSAGE": "FOYER", "POOJA": "POOJA", "STORE": "STORE"}
KINDS = ("BEDROOM", "LIVING", "DINING", "KITCHEN", "STUDY", "BATHROOM", "UTILITY", "OUTDOOR", "FOYER", "POOJA", "STORE")

# slot → catalogue categories (case-insensitive, exact); the first alias that has items wins
SLOTS = {
    "bed": ("bed",), "wardrobe": ("wardrobe",), "bedside": ("bedside table", "nightstand"), "dresser": ("dresser",),
    "sofa": ("sofa",), "tv": ("tv unit",), "coffee": ("coffee table", "centre table", "center table"),
    "armchair": ("armchair", "accent chair", "lounge chair"), "bookshelf": ("bookshelf", "bookcase", "storage"),
    "dining_table": ("dining table", "dining"), "dining_chair": ("dining chair", "chair"), "crockery": ("crockery", "crockery unit"),
    "base": ("kitchen",), "tall": ("kitchen",), "desk": ("study", "desk"), "desk_chair": ("office chair", "study chair", "chair"),
    "sink": ("kitchen sink",), "hob": ("kitchen hob",), "wall_unit": ("kitchen wall",), "filler": ("kitchen filler",),
    # M32 bathroom + utility
    "wc": ("wc", "toilet", "water closet"), "vanity": ("vanity", "vanity unit", "washbasin", "wash basin"), "shower": ("shower enclosure", "shower"),
    "mirror": ("mirror cabinet", "bathroom mirror"), "linen": ("linen cabinet", "bathroom storage"),
    "washer": ("washing machine",), "utility_base": ("utility base", "utility cabinet"), "utility_tall": ("utility tall", "broom cabinet"),
    "utility_wall": ("utility wall",),
    # M37 verandah / balcony, foyer, pooja room, store
    "outdoor_seat": ("outdoor chair", "lounge chair", "armchair"), "outdoor_table": ("outdoor table", "side table", "coffee table"), "planter": ("planter", "plant"),
    "shoe_rack": ("shoe rack",), "console": ("console table", "console"), "pooja_unit": ("pooja unit", "mandir"), "store_unit": ("storage", "utility tall", "linen cabinet"),
}
LABEL = {"bed": "Bed", "wardrobe": "Wardrobe", "bedside": "Bedside table", "dresser": "Dresser", "sofa": "Sofa", "tv": "TV unit",
         "coffee": "Coffee table", "armchair": "Armchair", "bookshelf": "Bookshelf", "dining_table": "Dining table", "dining_chair": "Dining chair",
         "crockery": "Crockery unit", "base": "Kitchen base unit", "tall": "Kitchen tall unit", "desk": "Study desk", "desk_chair": "Desk chair",
         "sink": "Sink unit", "hob": "Hob unit", "wall_unit": "Wall cabinet", "filler": "Filler panel",
         "wc": "WC", "vanity": "Vanity / washbasin", "shower": "Shower enclosure", "mirror": "Mirror cabinet", "linen": "Linen cabinet",
         "washer": "Washing machine", "utility_base": "Utility base cabinet", "utility_tall": "Utility tall cabinet", "utility_wall": "Utility wall cabinet",
         "outdoor_seat": "Outdoor seat", "outdoor_table": "Side table", "planter": "Planter", "shoe_rack": "Shoe rack", "console": "Console table",
         "pooja_unit": "Pooja unit", "store_unit": "Storage unit"}
REQUIRED = {"BEDROOM": ("bed", "wardrobe"), "LIVING": ("sofa", "tv"), "DINING": ("dining_table", "dining_chair"), "KITCHEN": ("base",), "STUDY": ("desk",),
            "BATHROOM": ("wc", "vanity"), "UTILITY": ("washer",), "OUTDOOR": ("outdoor_seat",), "FOYER": ("shoe_rack",), "POOJA": ("pooja_unit",),
            "STORE": ("store_unit",)}
OPTIONAL = {"BEDROOM": ("bedside", "dresser"), "LIVING": ("coffee", "armchair", "bookshelf"), "DINING": ("crockery",), "KITCHEN": ("tall", "sink", "hob", "wall_unit", "filler"),
            "STUDY": ("desk_chair", "bookshelf"), "BATHROOM": ("shower", "mirror", "linen"), "UTILITY": ("utility_base", "utility_tall", "utility_wall"),
            "OUTDOOR": ("outdoor_table", "planter"), "FOYER": ("console",), "POOJA": (), "STORE": ()}
# clear zone kept in front of a unit (mm): doors/drawers open, you stand or sit there
FRONT = {"wardrobe": 600, "dresser": 600, "sofa": 400, "tv": 600, "armchair": 400, "bookshelf": 600, "crockery": 600, "base": 1000, "tall": 1000, "desk": 750,
         "wc": 600, "vanity": 700, "shower": 600, "linen": 600, "washer": 700, "utility_base": 800, "utility_tall": 700,
         "outdoor_seat": 350, "shoe_rack": 500, "console": 450, "pooja_unit": 900, "store_unit": 600}
WC_SIDE = 200                        # clear elbow room each side of a WC (the 600 mm zone in front is widened by this)
MIRROR_AT = 1200                     # default underside of a mirror cabinet over the vanity
VIEW_MIN = 1500                      # sofa front ↔ TV front
CHAIR_PULL = 400                     # room behind a dining chair to pull it out and sit
SEAT_W = 600                         # table edge length per diner
SHAPES = ("AUTO", "STRAIGHT", "L", "PARALLEL", "U")
TIERS = ("BUDGET", "BALANCED", "PREMIUM")         # cheapest first / largest that fits / dearest first (after style)
WALL_UNIT_AT = 1450                              # default underside of kitchen wall cabinets (850 counter + 600 splash-back)
FILLER_MAX = 300                                 # wider gaps stay open (dishwasher / bin space) and are reported
TRIANGLE_LEG = (1200, 2700); TRIANGLE_MAX = 7900  # sink–hob–fridge work triangle (mm)
NO_SWAP = {"dining_table", "desk", "base", "sink", "hob", "tall", "filler"}          # sized to their surroundings — never swapped for budget
DROPPABLE = ("armchair", "bookshelf", "dresser", "crockery", "wall_unit", "coffee", "bedside")   # extras dropped (in this order) to meet a budget
OPP = {"N": "S", "S": "N", "E": "W", "W": "E"}
ADJ = {"N": ("W", "E"), "S": ("W", "E"), "E": ("S", "N"), "W": ("S", "N")}


class LayoutError(ValueError): pass


@dataclass
class Zone:
    poly: object; owner: str; allow: set = field(default_factory=set)
    def blocks(self, o: Obj) -> bool:
        if not on_floor(o): return False                                                     # wall cabinets hang above working zones
        if o.id == self.owner or o.id in self.allow or any(o.id.startswith(a[:-1]) for a in self.allow if a.endswith("*")): return False   # "desk_chair*" = any desk chair
        r = box(o.x, o.y, o.x + o.length, o.y + o.width)
        return self.poly.intersects(r) and self.poly.intersection(r).area > 0


@dataclass
class Plan:
    room: Room; kind: str
    objs: list = field(default_factory=list); zones: list = field(default_factory=list); notes: list = field(default_factory=list)
    missing: list = field(default_factory=list); ids: dict = field(default_factory=dict); wall: dict = field(default_factory=dict)
    slot_of: dict = field(default_factory=dict)          # object id → (slot, catalogue item) — for style notes and budget swaps

    def adopt(self, t: "Plan"):
        self.objs, self.zones, self.wall, self.ids, self.slot_of = t.objs, t.zones, t.wall, t.ids, {**self.slot_of, **t.slot_of}

    def in_slot(self, *slots): return [o for o in self.objs if self.slot_of.get(o.id, ("",))[0] in slots]

    def nid(self, slot):
        self.ids[slot] = self.ids.get(slot, 0) + 1
        return slot if self.ids[slot] == 1 and slot in ("bed", "wardrobe", "sofa", "tv", "coffee", "dining_table", "desk", "dresser", "crockery") else f"{slot}-{self.ids[slot]}"

    def ok(self, o: Obj, zone=None, ignore=()) -> bool:
        """o fits: inside the shell, under the ceiling, no overlap, clear of door zones and of every unit's working zone (and its own zone is free)."""
        R = self.room; r = box(o.x, o.y, o.x + o.length, o.y + o.width)
        if o.x < -0.01 or o.y < -0.01 or o.x + o.length > R.length + 0.01 or o.y + o.width > R.width + 0.01: return False
        if R.ceiling and top(o) > R.ceiling: return False
        for p in self.objs:
            if p.id in ignore: continue
            if area_overlap(p, o) and not stacked_apart(p, o): return False
        if (o.z or 0) < DOOR_HEAD:
            for _, dz in door_zones(R):
                if dz.intersects(r) and dz.intersection(r).area > 0: return False
        if any(z.blocks(o) for z in self.zones if z.owner not in ignore): return False
        if zone is not None:
            if not box(0, 0, R.length, R.width).contains(zone.poly): return False
            if any(zone.blocks(p) for p in self.objs if p.id not in ignore): return False
        return True

    def add(self, o: Obj, zone=None, wall=None):
        self.objs.append(o)
        if zone is not None: self.zones.append(zone)
        if wall: self.wall[o.id] = wall

    def remove(self, oid):
        self.objs = [o for o in self.objs if o.id != oid]; self.zones = [z for z in self.zones if z.owner != oid]


# ── catalogue + geometry helpers ─────────────────────────────────────────────
def candidates(cat: list[dict], slot: str) -> list[dict]:
    for alias in SLOTS[slot]:
        hit = [c for c in cat if (c.get("category") or "").strip().lower() == alias]
        if slot == "base": hit = [c for c in hit if c["height_mm"] <= 1000]
        if slot == "tall": hit = [c for c in hit if c["height_mm"] >= 1800]
        if hit: return sorted(hit, key=lambda c: (c.get("_pref", (0, 0)), -(c["length_mm"] * c["width_mm"])))   # style, tier, then largest first (stable)
    return []


def wall_len(R: Room, wall: str) -> float: return R.length if wall in "NS" else R.width


def mk(plan: Plan, slot: str, item: dict, x, y, along_x: bool) -> Obj:
    l, w = item["length_mm"], item["width_mm"]
    o = Obj(plan.nid(slot), item["name"], item["category"], x, y, l if along_x else w, w if along_x else l,
            item["height_mm"], float(item["price"]), item.get("sku", "") or "", float(item.get("mount_mm") or 0))
    plan.slot_of[o.id] = (slot, item)
    return o


def on_wall(plan: Plan, slot: str, item: dict, wall: str, pos: float, gap=G) -> Obj:
    """Back against `wall`, starting `pos` mm along it (west → east on N/S, south → north on W/E)."""
    R, w = plan.room, item["width_mm"]
    x, y, ax = {"S": (pos, gap, True), "N": (pos, R.width - w - gap, True), "W": (gap, pos, False), "E": (R.length - w - gap, pos, False)}[wall]
    return mk(plan, slot, item, x, y, ax)


def front_zone(o: Obj, wall: str, depth: float, allow=()) -> Zone:
    if wall == "S": p = box(o.x, o.y + o.width, o.x + o.length, o.y + o.width + depth)
    elif wall == "N": p = box(o.x, o.y - depth, o.x + o.length, o.y)
    elif wall == "W": p = box(o.x + o.length, o.y, o.x + o.length + depth, o.y + o.width)
    else: p = box(o.x - depth, o.y, o.x, o.y + o.width)
    return Zone(p, o.id, set(allow))


def positions(R: Room, length: float, wall: str, prefer="center", around=None) -> list[float]:
    span = wall_len(R, wall) - length - 2 * G
    if span < 0: return []
    lo, hi = G, G + span
    steps = [lo + k * 100 for k in range(int(span // 100) + 1)] + [hi]
    target = around if around is not None else (lo + span / 2)
    if prefer == "corner": key = lambda p: min(p - lo, hi - p)
    else: key = lambda p: abs(p - target)
    first = [min(max(target, lo), hi)] if prefer != "corner" else [lo, hi]
    out = []
    for p in first + sorted(steps, key=key):
        p = round(p / 10) * 10
        if lo - 0.01 <= p <= hi + 0.01 and p not in out: out.append(p)
    return out


def walls_by_length(R: Room) -> list[str]:
    return ["N", "S", "W", "E"] if R.length >= R.width else ["W", "E", "N", "S"]


def windows_on(R: Room, wall: str) -> bool: return any(o["kind"] == "WINDOW" and o["wall"] == wall for o in R.openings)


def place_on_walls(plan: Plan, slot: str, items: list[dict], walls, prefer="center", allow=()) -> Obj | None:
    for it in items:
        for wall in walls:
            for pos in positions(plan.room, it["length_mm"], wall, prefer):
                o = on_wall(plan, slot, it, wall, pos); z = front_zone(o, wall, FRONT[slot], allow) if slot in FRONT else None
                plan.ids[slot] -= 1                                    # mk() reserved an id; only keep it when placed
                if plan.ok(o, z):
                    plan.ids[slot] += 1; plan.add(o, z, wall); return o
    return None


def first_fit(plan: Plan, slot: str, items: list[dict], walls, prefer="center", allow=(), label=None):
    o = place_on_walls(plan, slot, items, walls, prefer, allow)
    if o: return o
    plan.notes.append(f"{label or LABEL[slot]} left out: no wall position keeps doors, walkways and the other units' working space clear.")
    return None


# ── bedroom ──────────────────────────────────────────────────────────────────
def bedroom(plan: Plan, cat, opts):
    R = plan.room; L, W = R.length, R.width
    beds, wars = candidates(cat, "bed"), candidates(cat, "wardrobe")
    def bed_spots(b):
        bl, bw = b["length_mm"], b["width_mm"]
        centred = [("N", (L - bl) / 2, W - bw - G, True), ("S", (L - bl) / 2, G, True), ("W", G, (W - bl) / 2, False), ("E", L - bw - G, (W - bl) / 2, False)]
        slid = []                                       # then slide the headboard along each wall (a door near a corner)
        for wall in ("N", "S", "W", "E"):
            for p in positions(R, bl, wall)[1:]:
                slid.append({"N": ("N", p, W - bw - G, True), "S": ("S", p, G, True), "W": ("W", G, p, False), "E": ("E", L - bw - G, p, False)}[wall])
        return centred + slid
    def war_spots(r):
        wl, ww = r["length_mm"], r["width_mm"]
        return [("S", G, G, True), ("S", L - wl - G, G, True), ("N", G, W - ww - G, True), ("N", L - wl - G, W - ww - G, True),
                ("W", G, G, False), ("W", G, W - wl - G, False), ("E", L - ww - G, G, False), ("E", L - ww - G, W - wl - G, False)]
    first = None
    for war_list, bed_list in ((wars or [None], beds or [None]), ([None], beds), (wars, [None])):   # both → bed only → wardrobe only
      if not bed_list or not war_list: continue
      for b in bed_list:
        for bs in (bed_spots(b) if b else [None]):
            for r in war_list:
                for ws in (war_spots(r) if r else [None]):
                    trial = Plan(R, plan.kind); objs = []
                    if b:
                        o = mk(trial, "bed", b, bs[1], bs[2], bs[3]); objs.append(o)
                        if not trial.ok(o): o = None
                        else: trial.add(o, wall=bs[0])
                    if r:
                        o2 = mk(trial, "wardrobe", r, ws[1], ws[2], ws[3]); objs.append(o2)
                        z = front_zone(o2, ws[0], FRONT["wardrobe"])
                        if not trial.ok(o2, z): o2 = None
                        else: trial.add(o2, z, ws[0])
                    first = first or objs
                    if len(trial.objs) == len(objs) and validate(R, trial.objs)["valid"]:
                        plan.adopt(trial)
                        bed = next((o for o in plan.objs if o.id == "bed"), None)
                        if bed: plan.notes.append(f"{bed.name}: headboard on the {wall_name(plan.wall['bed'])} wall.")
                        war = next((o for o in plan.objs if o.id == "wardrobe"), None)
                        if war: plan.notes.append(f"{war.name} on the {wall_name(plan.wall['wardrobe'])} wall with 600 mm clear in front for its doors.")
                        if wars and not war: plan.notes.append("Wardrobe left out: it doesn't fit beside the bed with the doors and 600 mm in front of it kept clear (a smaller wardrobe in the catalogue would help).")
                        if beds and not bed: plan.notes.append("Bed left out: no bed in the catalogue fits beside the wardrobe with the doors kept clear.")
                        return bedroom_extras(plan, cat, opts)
    plan.objs = first or []
    plan.notes.append("No bed + wardrobe arrangement fits this room with its doors kept clear — showing the preferred one so you can see what is wrong.")


def bedroom_extras(plan: Plan, cat, opts):
    bed = next((o for o in plan.objs if o.id == "bed"), None)
    if want(opts, "bedside") and bed and (bs := candidates(cat, "bedside")):
        t = bs[0]; wall = plan.wall["bed"]; tl, tw = t["length_mm"], t["width_mm"]
        if wall in "NS":
            y = bed.y + bed.width - tw if wall == "N" else bed.y
            pair = [mk(plan, "bedside", t, bed.x - tl, y, True), mk(plan, "bedside", t, bed.x + bed.length, y, True)]
        else:
            x = bed.x + bed.length - tw if wall == "E" else bed.x
            pair = [mk(plan, "bedside", t, x, bed.y - tl, False), mk(plan, "bedside", t, x, bed.y + bed.width, False)]
        if plan.ok(pair[0]) and (plan.add(pair[0]) or True) and plan.ok(pair[1]): plan.add(pair[1]); plan.notes.append("Bedside tables on both sides of the bed.")
        else:
            plan.remove(pair[0].id); plan.ids["bedside"] = 0; plan.notes.append("Bedside tables left out: there isn't room on both sides of the bed.")
    if want(opts, "dresser") and (ds := candidates(cat, "dresser")):
        first_fit(plan, "dresser", ds, walls_by_length(plan.room))


# ── living room ──────────────────────────────────────────────────────────────
def living(plan: Plan, cat, opts):
    R = plan.room; sofas, tvs = candidates(cat, "sofa"), candidates(cat, "tv")
    best = None
    for relaxed in (False, True):
        for s in sofas:
            for wall in walls_by_length(R):
                for pos in positions(R, s["length_mm"], wall):
                    so = on_wall(plan, "sofa", s, wall, pos); plan.ids["sofa"] -= 1
                    sz = front_zone(so, wall, FRONT["sofa"])
                    if not plan.ok(so, sz): continue
                    if not tvs: best = (so, sz, wall, None); break
                    tw = OPP[wall]; centre = (so.x + so.length / 2) if wall in "NS" else (so.y + so.width / 2)
                    for t in tvs:
                        for tpos in positions(R, t["length_mm"], tw, around=centre - t["length_mm"] / 2):
                            to = on_wall(plan, "tv", t, tw, tpos); plan.ids["tv"] -= 1
                            tz = front_zone(to, tw, FRONT["tv"])
                            view = distance(so, to, wall)
                            if (relaxed or view >= VIEW_MIN) and plan.ok(to, tz) and not sz.blocks(to) and not tz.blocks(so):
                                best = (so, sz, wall, (to, tz, tw, view)); break
                        if best: break
                    if best: break
                if best: break
            if best: break
        if best: break
    if not best:
        plan.notes.append("No sofa position fits this room with its doors and walkways kept clear."); return
    so, sz, wall, tv = best
    plan.ids["sofa"] = 1; plan.add(so, sz, wall); plan.notes.append(f"{so.name} against the {wall_name(wall)} wall.")
    if tv:
        to, tz, tw, view = tv; plan.ids["tv"] = 1; plan.add(to, tz, tw)
        plan.notes.append(f"{to.name} on the opposite ({wall_name(tw)}) wall, {view / 1000:.1f} m from the sofa"
                          + ("." if view >= VIEW_MIN else f" — closer than the {VIEW_MIN / 1000:.1f} m viewing distance this room allows."))
    if want(opts, "coffee") and (cs := candidates(cat, "coffee")):
        placed = False
        for c in cs:
            ax = wall in "NS"; cl, cw = c["length_mm"], c["width_mm"]
            if ax:
                x = so.x + (so.length - cl) / 2; y = so.y - FRONT["sofa"] - cw if wall == "N" else so.y + so.width + FRONT["sofa"]
            else:
                y = so.y + (so.width - cl) / 2; x = so.x - FRONT["sofa"] - cw if wall == "E" else so.x + so.length + FRONT["sofa"]
            o = mk(plan, "coffee", c, x, y, ax); plan.ids["coffee"] -= 1
            if plan.ok(o):
                plan.ids["coffee"] += 1; plan.add(o); plan.notes.append(f"{o.name} centred in front of the sofa, 400 mm away."); placed = True; break
        if not placed: plan.notes.append("Coffee table left out: it would block the walkway in front of the TV unit.")
    if want(opts, "armchair") and (ac := candidates(cat, "armchair")):
        first_fit(plan, "armchair", ac, ADJ[wall])
    if want(opts, "bookshelf") and (bk := candidates(cat, "bookshelf")):
        first_fit(plan, "bookshelf", bk, walls_by_length(R), prefer="corner")


def distance(a: Obj, b: Obj, a_wall: str) -> float:
    """Gap between the fronts of two units standing on opposite walls."""
    return {"S": b.y - (a.y + a.width), "N": a.y - (b.y + b.width), "W": b.x - (a.x + a.length), "E": a.x - (b.x + b.length)}[a_wall]


# ── dining room ──────────────────────────────────────────────────────────────
def dining(plan: Plan, cat, opts):
    R = plan.room; tables, chairs = candidates(cat, "dining_table"), candidates(cat, "dining_chair")
    seats_wanted = opts.get("seats")
    if seats_wanted: tables = sorted(tables, key=lambda t: (capacity(t) < seats_wanted, capacity(t) if capacity(t) >= seats_wanted else -capacity(t)))
    long_x = R.length >= R.width
    best = None
    for t in tables:
        tl, tw = t["length_mm"], t["width_mm"]; Lx, Ly = (tl, tw) if long_x else (tw, tl)
        cx, cy = (R.length - Lx) / 2, (R.width - Ly) / 2
        for dx, dy in ((0, 0), (-300, 0), (300, 0), (0, -300), (0, 300)):
            trial = Plan(R, plan.kind)
            to = mk(trial, "dining_table", t, cx + dx, cy + dy, long_x)
            if not trial.ok(to): continue
            trial.add(to)
            seated = seat(trial, to, chairs[0], long_x, seats_wanted) if chairs else 0
            if best is None or seated > best[1]: best = (trial, seated, t)
            if chairs and seated >= min(capacity(t), seats_wanted or 99): break
        if best and chairs and best[1] >= min(capacity(best[2]), seats_wanted or 99): break
    if not best:
        plan.notes.append("No dining table fits this room with its doors kept clear."); return
    trial, seated, t = best
    plan.adopt(trial)
    plan.notes.append(f"{t['name']} centred in the room with {seated} chair(s), {CHAIR_PULL} mm behind each chair to pull it out.")
    if chairs and seated < capacity(t): plan.notes.append(f"Only {seated} of the table's {capacity(t)} seats fit with chair space kept clear.")
    if want(opts, "crockery") and (cr := candidates(cat, "crockery")):
        first_fit(plan, "crockery", cr, walls_by_length(R), allow=())


def capacity(t: dict) -> int:
    per_side = max(1, int(t["length_mm"] // SEAT_W)); ends = 2 if t["length_mm"] >= 2100 else 0
    return per_side * 2 + ends


def seat(plan: Plan, table: Obj, chair: dict, long_x: bool, wanted=None) -> int:
    """Chairs on both long sides (one per 600 mm of table), plus the ends of long tables; each keeps 400 mm behind it to pull out."""
    cl, cw = chair["length_mm"], chair["width_mm"]                 # chair width along the table edge, depth away from it
    tl = table.length if long_x else table.width
    n = max(1, int(tl // SEAT_W)); seg = tl / n; spots = []
    for side in (0, 1):
        for i in range(n):
            a = (table.x if long_x else table.y) + seg * i + (seg - cl) / 2
            if long_x:
                y = table.y - cw if side == 0 else table.y + table.width
                spots.append((a, y, True, box(a, y - CHAIR_PULL, a + cl, y) if side == 0 else box(a, y + cw, a + cl, y + cw + CHAIR_PULL)))
            else:
                x = table.x - cw if side == 0 else table.x + table.length
                spots.append((x, a, False, box(x - CHAIR_PULL, a, x, a + cl) if side == 0 else box(x + cw, a, x + cw + CHAIR_PULL, a + cl)))
    if tl >= 2100:
        for end in (0, 1):
            if long_x:
                x = table.x - cw if end == 0 else table.x + table.length; y = table.y + (table.width - cl) / 2
                spots.append((x, y, False, box(x - CHAIR_PULL, y, x, y + cl) if end == 0 else box(x + cw, y, x + cw + CHAIR_PULL, y + cl)))
            else:
                y = table.y - cw if end == 0 else table.y + table.width; x = table.x + (table.length - cl) / 2
                spots.append((x, y, True, box(x, y - CHAIR_PULL, x + cl, y) if end == 0 else box(x, y + cw, x + cl, y + cw + CHAIR_PULL)))
    seated = 0
    for x, y, along, pull in spots:
        if wanted and seated >= wanted: break
        # a chair faces the table: its seat width runs along the table edge
        o = Obj(f"dining_chair-{seated + 1}", chair["name"], chair["category"], x, y, cl if along else cw, cw if along else cl,
                chair["height_mm"], float(chair["price"]), chair.get("sku", "") or "")
        z = Zone(pull, o.id)
        if plan.ok(o, z): plan.add(o, z); plan.slot_of[o.id] = ("dining_chair", chair); seated += 1
    plan.ids["dining_chair"] = seated
    return seated


# ── kitchen ──────────────────────────────────────────────────────────────────
def kitchen(plan: Plan, cat, opts):
    R = plan.room; bases, talls = candidates(cat, "base"), (candidates(cat, "tall") if want(opts, "tall") else [])
    shape = (opts.get("kitchen_shape") or "AUTO").upper()
    if shape not in SHAPES: raise LayoutError(f"Kitchen shape must be one of {', '.join(SHAPES)}")
    if not bases:
        plan.notes.append("No kitchen base units in the catalogue (category 'Kitchen', up to 1000 mm high) — add them in Catalogue → Furniture."); return
    layouts = []
    for w in ("N", "S", "W", "E"):
        a, b = ADJ[w]
        layouts += [("STRAIGHT", [w]), ("L", [w, a]), ("L", [w, b]), ("PARALLEL", [w, OPP[w]]), ("U", [w, a, b])]
    best = None
    for name, walls in layouts:
        if shape != "AUTO" and name != shape: continue
        trial = Plan(R, plan.kind)
        if talls: place_tall(trial, talls, walls)
        for w in walls: fill_run(trial, bases, w)
        run = sum(along_len(o, trial.wall[o.id]) for o in trial.objs if o.height <= 1000)
        if run == 0: continue
        if len(walls) > 1 and any(not any(trial.wall[o.id] == w and o.height <= 1000 for o in trial.objs) for w in walls): continue   # every run of the shape got counter
        clean = not [x for x in validate(R, trial.objs)["warnings"] if "walkway" in x]
        score = (validate(R, trial.objs)["valid"], clean, run)
        if best is None or score > best[0]: best = (score, trial, name, walls, run)
    if not best:
        plan.notes.append("No counter run fits: every wall is taken by a door or is too short." if shape == "AUTO"
                          else f"A {shape.lower()} kitchen doesn't fit this room (doors / 1000 mm working aisle); try Auto.")
        return
    _, trial, name, walls, run = best
    plan.adopt(trial)
    mods = [o for o in plan.objs if o.height <= 1000]
    plan.notes.append(f"{dict(STRAIGHT='Straight', L='L-shaped', PARALLEL='Parallel', U='U-shaped')[name]} kitchen on the "
                      f"{' + '.join(wall_name(w) for w in walls)} wall(s): {len(mods)} base unit(s), {run / 1000:.2f} m of counter, 1000 mm working aisle kept clear.")
    if talls and not any(o.height >= 1800 for o in plan.objs): plan.notes.append("Tall unit left out: no run end has room for it.")
    sink = place_special(plan, cat, "sink") if want(opts, "sink") else None
    hob = place_special(plan, cat, "hob") if want(opts, "hob") else None
    fridge = next(iter(plan.in_slot("tall")), None)
    if sink and hob and fridge:
        legs = [dist(sink, hob), dist(hob, fridge), dist(fridge, sink)]
        good = all(TRIANGLE_LEG[0] <= d <= TRIANGLE_LEG[1] for d in legs) and sum(legs) <= TRIANGLE_MAX
        plan.notes.append(f"Work triangle sink → hob → fridge: {' + '.join(f'{d / 1000:.1f}' for d in legs)} = {sum(legs) / 1000:.1f} m — "
                          + ("within the usual 1.2–2.7 m per side and 7.9 m in total." if good else "outside the usual 1.2–2.7 m per side / 7.9 m total; check the cooking flow on site."))
    if want(opts, "wall_unit"): wall_units(plan, cat)
    if want(opts, "filler"): fillers(plan, cat, walls)


def along_start(o: Obj, wall: str) -> float: return o.x if wall in "NS" else o.y
def along_len(o: Obj, wall: str) -> float: return o.length if wall in "NS" else o.width
def dist(a: Obj, b: Obj) -> float:
    return ((a.x + a.length / 2 - b.x - b.length / 2) ** 2 + (a.y + a.width / 2 - b.y - b.width / 2) ** 2) ** 0.5
def touches(a: Obj, b: Obj) -> bool:
    ra, rb = box(a.x, a.y, a.x + a.length, a.y + a.width), box(b.x, b.y, b.x + b.length, b.y + b.width)
    return ra.distance(rb) < 1 and (ra.intersection(rb).area == 0)


def windows_over(R: Room, wall: str, a0: float, a1: float) -> list:
    return [w for w in R.openings if w["kind"] == "WINDOW" and w["wall"] == wall and w["offset"] < a1 and w["offset"] + w["width"] > a0]


def covers_window(R: Room, o: Obj, wall: str) -> bool:
    a0 = along_start(o, wall); a1 = a0 + along_len(o, wall)
    return any((o.z or 0) < w.get("sill", 0) + w.get("height", 1200) and top(o) > w.get("sill", 0) for w in windows_over(R, wall, a0, a1))


def place_special(plan: Plan, cat, slot: str):
    """Swap one base unit for the sink unit (under a window if possible) or the hob unit (counter both sides, away from the sink,
    tall unit and windows). The swapped unit keeps the same wall position, so the run stays valid."""
    items = sorted(candidates(cat, slot), key=lambda c: (c.get("_pref", (0, 0))[0], -c["length_mm"]))
    if not items: return None
    R = plan.room; mods = plan.in_slot("base"); sink = next(iter(plan.in_slot("sink")), None); tall = next(iter(plan.in_slot("tall")), None)
    counter = plan.in_slot("base", "sink", "hob", "tall")
    runs = {}
    for o in mods: runs.setdefault(plan.wall[o.id], []).append(o)
    def score(m):
        w = plan.wall[m.id]; a0 = along_start(m, w); win = bool(windows_over(R, w, a0, a0 + along_len(m, w)))
        mid = sum(along_start(o, w) + along_len(o, w) / 2 for o in runs[w]) / len(runs[w])
        s = -abs(a0 + along_len(m, w) / 2 - mid) / 1000
        n = sum(1 for o in counter if o.id != m.id and touches(o, m))
        if slot == "sink": s += 10 if win else 0
        else:
            s += -20 if win else 0
            s += 4 if n >= 2 else -6                                                     # counter on both sides of the hob
            if tall and touches(m, tall): s -= 10
            if sink:
                s += -15 if touches(m, sink) else 0
                s += 5 if TRIANGLE_LEG[0] <= dist(m, sink) <= TRIANGLE_LEG[1] else 0
                s += 2 if plan.wall[m.id] != plan.wall[sink.id] else 0
        return s
    for m in sorted(mods, key=score, reverse=True):
        w = plan.wall[m.id]; ml = along_len(m, w)
        for it in [i for i in items if i["length_mm"] <= ml + 0.01]:
            new = on_wall(plan, slot, it, w, along_start(m, w))
            zone = front_zone(new, w, FRONT["base"], allow=kitchen_allow(plan, w))
            for zz in plan.zones:
                if m.id in zz.allow: zz.allow.add(new.id)
            if plan.ok(new, zone, ignore={m.id}):
                plan.remove(m.id); plan.add(new, zone, w); plan.wall.pop(m.id, None)
                a0 = along_start(new, w); win = windows_over(R, w, a0, a0 + along_len(new, w))
                if slot == "sink":
                    plan.notes.append(f"{new.name} on the {wall_name(w)} run" + (f", under {win[0].get('label') or 'the window'}." if win else " (no window over the counter)."))
                else:
                    gap = f", {dist(new, sink) / 1000:.1f} m from the sink" if sink else ""
                    plan.notes.append(f"{new.name} on the {wall_name(w)} run{gap}, with counter on both sides; chimney point above it.")
                return new
            plan.ids[slot] -= 1
            for zz in plan.zones: zz.allow.discard(new.id)
    plan.notes.append(f"{LABEL[slot]} left out: no base unit position suits it (needs a unit at least {items[-1]['length_mm']:.0f} mm long).")
    return None


def wall_units(plan: Plan, cat):
    items = sorted(candidates(cat, "wall_unit"), key=lambda c: (c.get("_pref", (0, 0))[0], -c["length_mm"]))
    if not items: return
    R = plan.room; placed = skipped_window = 0
    for m in plan.in_slot("base", "sink"):                               # not over the hob (chimney) or the tall unit
        w = plan.wall[m.id]; ml = along_len(m, w)
        for it in [i for i in items if i["length_mm"] <= ml + 0.01]:
            o = on_wall(plan, "wall_unit", it, w, along_start(m, w)); o.z = float(it.get("mount_mm") or WALL_UNIT_AT)
            if covers_window(R, o, w): plan.ids["wall_unit"] -= 1; skipped_window += 1; break
            if plan.ok(o): plan.add(o, wall=w); placed += 1; break
            plan.ids["wall_unit"] -= 1
    if placed:
        at = int(next(o.z for o in plan.in_slot("wall_unit")))
        extra = ([f"none in front of the window ({skipped_window} spot(s) left open)"] if skipped_window else []) + (["none above the hob (the chimney goes there)"] if plan.in_slot("hob") else [])
        plan.notes.append(f"{placed} wall cabinet(s) {at} mm above the floor over the counter" + ("; " + "; ".join(extra) if extra else "") + ".")
    else: plan.notes.append("Wall cabinets left out: no counter position has room under the ceiling away from windows.")


def fillers(plan: Plan, cat, walls):
    """Close the gaps a run leaves (corners, run ends against a wall, a short sink/hob unit) with filler panels cut to size."""
    items = candidates(cat, "filler")
    if not items: return
    it = items[0]; R = plan.room; D = max((min(o.length, o.width) for o in plan.in_slot("base", "sink", "hob")), default=600)
    blocked = unary_union([box(o.x, o.y, o.x + o.length, o.y + o.width) for o in plan.objs if on_floor(o)] + [z for _, z in door_zones(R)])
    doors = unary_union([z for _, z in door_zones(R)]) if R.openings else None
    added, wide = 0, []
    for w in walls:
        n = wall_len(R, w)
        strip = {"S": box(G, G, n - G, G + D), "N": box(G, R.width - G - D, n - G, R.width - G),
                 "W": box(G, G, G + D, n - G), "E": box(R.length - G - D, G, R.length - G, n - G)}[w]
        free = strip.difference(blocked)
        for pc in getattr(free, "geoms", [free]):
            if pc.is_empty or pc.area < 1: continue
            x0, y0, x1, y1 = pc.bounds
            if abs(pc.area - (x1 - x0) * (y1 - y0)) > 1: continue                      # not a clean rectangle
            along, depth = ((x1 - x0), (y1 - y0)) if w in "NS" else ((y1 - y0), (x1 - x0))
            if depth < D - 1 or along < 20: continue
            if doors is not None and not doors.is_empty and pc.distance(doors) < 1: continue    # open end at a doorway
            if along > FILLER_MAX: wide.append(along); continue
            o = Obj(plan.nid("filler"), f"{it['name']} ({along:.0f} mm)", it["category"], x0, y0, x1 - x0, y1 - y0, it["height_mm"], float(it["price"]), it.get("sku", "") or "")
            if plan.ok(o): plan.add(o, wall=w); plan.slot_of[o.id] = ("filler", it); added += 1
            else: plan.ids["filler"] -= 1
    if added: plan.notes.append(f"{added} filler panel(s) close the gaps at corners and run ends.")
    if wide: plan.notes.append(f"{len(wide)} gap(s) wider than {FILLER_MAX} mm left open ({', '.join(f'{g:.0f}' for g in wide)} mm) — room for a dishwasher or bin pull-out.")


def place_tall(plan: Plan, talls, walls):
    for t in talls:
        for w in walls:
            for pos in positions(plan.room, t["length_mm"], w, prefer="corner")[:2]:
                o = on_wall(plan, "tall", t, w, pos); z = front_zone(o, w, FRONT["tall"], allow=kitchen_allow(plan, w))
                plan.ids["tall"] -= 1
                if plan.ok(o, z): plan.ids["tall"] += 1; plan.add(o, z, w); return o
    return None


def kitchen_allow(plan: Plan, wall: str) -> set:
    """A counter's working zone may run into the units of the adjacent wall (that's the corner), not the opposite one."""
    return {oid for oid, w in plan.wall.items() if w in ADJ[wall]}


def fill_run(plan: Plan, bases, wall):
    R = plan.room; end = wall_len(R, wall) - G; cur = G; smallest = min(b["length_mm"] for b in bases)
    while cur + smallest <= end + 0.01:
        placed = False
        for b in bases:
            if cur + b["length_mm"] > end + 0.01: continue
            o = on_wall(plan, "base", b, wall, cur); plan.ids["base"] -= 1
            z = front_zone(o, wall, FRONT["base"], allow=kitchen_allow(plan, wall))
            # the corner: units already on the adjacent walls may stand in this unit's zone, and this unit may stand in theirs
            saved = [zz for zz in plan.zones if zz.owner in kitchen_allow(plan, wall)]
            for zz in saved: zz.allow.add(o.id)
            if plan.ok(o, z):
                plan.ids["base"] += 1; plan.add(o, z, wall); cur += b["length_mm"]; placed = True; break
            for zz in saved: zz.allow.discard(o.id)
        if not placed: cur += 50


# ── study ────────────────────────────────────────────────────────────────────
def study(plan: Plan, cat, opts):
    R = plan.room; desks = candidates(cat, "desk")
    walls = sorted(walls_by_length(R), key=lambda w: not windows_on(R, w))     # daylight: a wall with a window first
    d = first_fit(plan, "desk", desks, walls, allow=("desk_chair*",))
    if not d: return
    dw = plan.wall[d.id]; plan.notes.append(f"{d.name} on the {wall_name(dw)} wall" + (" (by the window for daylight)." if windows_on(R, dw) else "."))
    if want(opts, "desk_chair") and (ch := candidates(cat, "desk_chair")):
        c = ch[0]; cl, cw = c["length_mm"], c["width_mm"]
        if dw in "NS":
            x = d.x + (d.length - cl) / 2; y = d.y - cw if dw == "N" else d.y + d.width
            o = mk(plan, "desk_chair", c, x, y, True)
        else:
            y = d.y + (d.width - cl) / 2; x = d.x - cw if dw == "E" else d.x + d.length
            o = mk(plan, "desk_chair", c, x, y, False)
        if plan.ok(o): plan.add(o); plan.notes.append(f"{o.name} at the desk.")
        else: plan.ids["desk_chair"] -= 1; plan.notes.append("Desk chair left out: no room in front of the desk.")
    if want(opts, "bookshelf") and (bk := candidates(cat, "bookshelf")):
        first_fit(plan, "bookshelf", bk, walls_by_length(R), prefer="corner")


# ── bathroom (M32) ───────────────────────────────────────────────────────────
def door_walls(R: Room) -> set: return {o["wall"] for o in R.openings if o["kind"] == "DOOR"}


def away_from_door(R: Room) -> list[str]:
    """Walls ordered: no door on it first, the wall opposite a door before the door's side walls."""
    dw = door_walls(R)
    return sorted(walls_by_length(R), key=lambda w: (w in dw, not any(OPP[d] == w for d in dw)))


def _bath_wc(plan: Plan, cat, prefer: str) -> Obj | None:
    R = plan.room
    for it in candidates(cat, "wc"):
        for wall in away_from_door(R):
            for pos in positions(R, it["length_mm"] + 2 * WC_SIDE, wall, prefer):
                o = on_wall(plan, "wc", it, wall, pos + WC_SIDE); plan.ids["wc"] -= 1
                z = front_zone(o, wall, FRONT["wc"])
                z = Zone(z.poly.buffer(WC_SIDE, join_style=2).intersection(box(0, 0, R.length, R.width)), o.id)   # elbow room both sides
                side = Zone(box(o.x - WC_SIDE, o.y - WC_SIDE, o.x + o.length + WC_SIDE, o.y + o.width + WC_SIDE).intersection(box(0, 0, R.length, R.width)), o.id)
                if plan.ok(o, z) and not any(side.blocks(p) for p in plan.objs):
                    plan.ids["wc"] += 1; plan.add(o, z, wall); plan.zones.append(side)
                    plan.notes.append(f"{o.name} on the {wall_name(wall)} wall with {FRONT['wc']} mm clear in front and {WC_SIDE} mm each side"
                                      + (" — not facing the door." if door_walls(R) and wall not in {OPP[d] for d in door_walls(R)} else "."))
                    return o
    plan.notes.append("WC left out: no wall keeps 600 mm in front and elbow room at the sides.")
    return None


def _bath_vanity(plan: Plan, cat, opts) -> Obj | None:
    R = plan.room
    v = first_fit(plan, "vanity", candidates(cat, "vanity"), away_from_door(R)[::-1] if door_walls(R) else walls_by_length(R))
    if not v: return None
    vw = plan.wall[v.id]; plan.notes.append(f"{v.name} on the {wall_name(vw)} wall" + (" near the door, so hands are washed on the way out." if vw in door_walls(R) else "."))
    if want(opts, "mirror") and (mr := candidates(cat, "mirror")):
        it = mr[0]; z0 = it.get("mount_mm") or MIRROR_AT
        ml = min(it["length_mm"], along_len(v, vw)); pos = along_start(v, vw) + (along_len(v, vw) - ml) / 2
        o = on_wall(plan, "mirror", {**it, "length_mm": ml, "mount_mm": z0}, vw, pos)
        if (o.z or 0) <= top(v): o.z = top(v) + 300
        if plan.ok(o): plan.add(o, None, vw); plan.notes.append(f"{o.name} over the vanity at {o.z:.0f} mm.")
        else: plan.ids["mirror"] -= 1; plan.notes.append("Mirror cabinet left out: it doesn't fit over the vanity under the ceiling.")
    return v


def _bath_shower(plan: Plan, cat) -> Obj | None:
    s = first_fit(plan, "shower", candidates(cat, "shower"), away_from_door(plan.room), prefer="corner", allow=())
    if s: plan.notes.append(f"{s.name} in a corner on the {wall_name(plan.wall[s.id])} wall, away from the door.")
    return s


def bathroom(plan: Plan, cat, opts):
    """Tries a few orders (shower first / fixtures first) and WC positions (corner / centred) and keeps the layout that places the WC and
    vanity and then the most other fittings — a small bathroom only works when the big shower corner is chosen well."""
    R = plan.room; shower = want(opts, "shower") and bool(candidates(cat, "shower"))
    best, best_key = None, None
    for order in (("shower", "wc", "vanity"), ("wc", "vanity", "shower"), ("wc", "shower", "vanity"), ("vanity", "shower", "wc")):
        if not shower and order[0] == "shower": continue
        for prefer in ("corner", "center"):
            t = Plan(R, plan.kind)
            for step in order:
                if step == "wc" and candidates(cat, "wc"): _bath_wc(t, cat, prefer)
                elif step == "vanity" and candidates(cat, "vanity"): _bath_vanity(t, cat, opts)
                elif step == "shower" and shower: _bath_shower(t, cat)
            if want(opts, "linen") and (ln := candidates(cat, "linen")): first_fit(t, "linen", ln, away_from_door(R), prefer="corner")
            got = {t.slot_of[o.id][0] for o in t.objs}
            key = (("wc" in got) + ("vanity" in got), ("shower" in got), len(t.objs))
            if best_key is None or key > best_key: best, best_key = t, key
    plan.adopt(best); plan.notes.extend(best.notes)


# ── utility / laundry (M32) ──────────────────────────────────────────────────
def utility(plan: Plan, cat, opts):
    R = plan.room; walls = away_from_door(R)
    w = first_fit(plan, "washer", candidates(cat, "washer"), walls, prefer="corner", allow=("utility_base*",)) if candidates(cat, "washer") else None
    if not w: return
    ww = plan.wall[w.id]; plan.notes.append(f"{w.name} in the corner of the {wall_name(ww)} wall (16A socket + water inlet/outlet there).")
    run = [w]
    if want(opts, "utility_base") and (bases := candidates(cat, "utility_base")):
        for it in sorted(bases, key=lambda c: -c["length_mm"]):
            while True:
                end = max(along_start(o, ww) + along_len(o, ww) for o in run); start = min(along_start(o, ww) for o in run)
                placed = None
                for pos in (end, start - it["length_mm"]):
                    if pos < G - 0.01 or pos + it["length_mm"] > wall_len(R, ww) - G + 0.01: continue
                    o = on_wall(plan, "utility_base", it, ww, pos); plan.ids["utility_base"] -= 1
                    z = front_zone(o, ww, FRONT["utility_base"], ("washer",))
                    if plan.ok(o, z): plan.ids["utility_base"] += 1; plan.add(o, z, ww); run.append(o); placed = o; break
                if not placed or len(run) > 6: break
        n = len(run) - 1
        if n: plan.notes.append(f"{n} utility base cabinet(s) beside the washing machine on the same wall (one counter run for folding).")
    if want(opts, "utility_tall") and (talls := candidates(cat, "utility_tall")):
        t = first_fit(plan, "utility_tall", talls, [ww] + [x for x in walls if x != ww], prefer="corner")
        if t: plan.notes.append(f"{t.name} (brooms, ironing board) on the {wall_name(plan.wall[t.id])} wall.")
    if want(opts, "utility_wall") and (wu := candidates(cat, "utility_wall")):
        it = wu[0]; z0 = it.get("mount_mm") or WALL_UNIT_AT; n = 0
        for b in [o for o in run if plan.slot_of[o.id][0] == "utility_base"]:
            l = min(it["length_mm"], along_len(b, ww)); pos = along_start(b, ww) + (along_len(b, ww) - l) / 2
            o = on_wall(plan, "utility_wall", {**it, "length_mm": l, "mount_mm": z0}, ww, pos)
            if plan.ok(o): plan.add(o, None, ww); n += 1
            else: plan.ids["utility_wall"] -= 1
        if n: plan.notes.append(f"{n} wall cabinet(s) over the utility counter at {z0:.0f} mm.")


# ── verandah / balcony, foyer, pooja room, store (M37) ─────────────────────────
def _beside(plan: Plan, slot: str, item: dict, ref: Obj, wall: str, gap=100) -> Obj | None:
    """Place `item` on the same wall right next to `ref` (either side)."""
    for pos in (along_start(ref, wall) + along_len(ref, wall) + gap, along_start(ref, wall) - item["length_mm"] - gap):
        if pos < G - 0.01 or pos + item["length_mm"] > wall_len(plan.room, wall) - G + 0.01: continue
        o = on_wall(plan, slot, item, wall, pos); plan.ids[slot] -= 1
        z = front_zone(o, wall, FRONT.get(slot, 0)) if slot in FRONT else None
        if plan.ok(o, z): plan.ids[slot] += 1; plan.add(o, z, wall); return o
    return None


def outdoor(plan: Plan, cat, opts):
    R = plan.room; walls = away_from_door(R)
    seats = candidates(cat, "outdoor_seat")
    a = first_fit(plan, "outdoor_seat", seats, walls, prefer="center", allow=("outdoor_table*",)) if seats else None
    if not a: return
    w = plan.wall[a.id]; b = _beside(plan, "outdoor_seat", plan.slot_of[a.id][1], a, w, gap=450)
    plan.notes.append(f"Seating against the {wall_name(w)} wall, away from the door" + (" — a pair with a small table between." if b else "."))
    if want(opts, "outdoor_table") and (tb := candidates(cat, "outdoor_table")):
        t = tb[-1] if len(tb) > 1 else tb[0]
        placed = False
        if b:
            mid = (along_start(a, w) + along_len(a, w) + along_start(b, w)) / 2 if along_start(b, w) > along_start(a, w) else (along_start(b, w) + along_len(b, w) + along_start(a, w)) / 2
            o = on_wall(plan, "outdoor_table", t, w, mid - t["length_mm"] / 2); plan.ids["outdoor_table"] -= 1
            if plan.ok(o, ignore=(a.id, b.id)) and not any(area_overlap(o, x) for x in (a, b)): plan.ids["outdoor_table"] += 1; plan.add(o, None, w); placed = True
        if not placed: first_fit(plan, "outdoor_table", [t], walls, prefer="corner")
    if want(opts, "planter") and (pl := candidates(cat, "planter")):
        n = 0
        for wall in walls:
            for pos in positions(R, pl[0]["length_mm"], wall, "corner")[:2]:
                o = on_wall(plan, "planter", pl[0], wall, pos); plan.ids["planter"] -= 1
                if plan.ok(o): plan.ids["planter"] += 1; plan.add(o, None, wall); n += 1
                if n >= 2: break
            if n >= 2: break
        if n: plan.notes.append(f"{n} planter(s) in the corners for greenery.")


def foyer(plan: Plan, cat, opts):
    R = plan.room; dw = door_walls(R)
    side = [w for w in walls_by_length(R) if w not in dw] + [w for w in walls_by_length(R) if w in dw]
    s = first_fit(plan, "shoe_rack", candidates(cat, "shoe_rack"), side, prefer="corner") if candidates(cat, "shoe_rack") else None
    if s: plan.notes.append(f"{s.name} near the entrance on the {wall_name(plan.wall[s.id])} wall — shoes off as you come in.")
    if want(opts, "console") and (cs := candidates(cat, "console")):
        c = first_fit(plan, "console", cs, [w for w in walls_by_length(R) if not s or w != plan.wall[s.id]] or walls_by_length(R))
        if c: plan.notes.append(f"{c.name} on the {wall_name(plan.wall[c.id])} wall — keys, a lamp and a mirror above.")


def pooja(plan: Plan, cat, opts):
    R = plan.room
    order = ["E", "N", "W", "S"]                    # unit on the east wall → you face east while praying (else north)
    walls = [w for w in order if w not in door_walls(R)] + [w for w in order if w in door_walls(R)]
    u = first_fit(plan, "pooja_unit", candidates(cat, "pooja_unit"), walls) if candidates(cat, "pooja_unit") else None
    if u: plan.notes.append(f"{u.name} on the {wall_name(plan.wall[u.id])} wall" + (" — you face east while praying." if plan.wall[u.id] == "E" else
                            " — you face north while praying." if plan.wall[u.id] == "N" else " (east and north walls weren't free)."))


def store(plan: Plan, cat, opts):
    R = plan.room; units = candidates(cat, "store_unit"); n = 0
    for _ in range(6):
        if not place_on_walls(plan, "store_unit", units, walls_by_length(R), prefer="corner"): break
        n += 1
    if n: plan.notes.append(f"{n} storage unit(s) along the walls, keeping a {FRONT['store_unit']} mm aisle.")
    else: plan.notes.append("Storage unit left out: no wall keeps the door and an aisle clear.")


# ── entry point ──────────────────────────────────────────────────────────────
PLANNERS = {"BEDROOM": bedroom, "LIVING": living, "DINING": dining, "KITCHEN": kitchen, "STUDY": study, "BATHROOM": bathroom, "UTILITY": utility,
            "OUTDOOR": outdoor, "FOYER": foyer, "POOJA": pooja, "STORE": store}


def want(opts: dict, slot: str) -> bool: return slot not in set(opts.get("skip") or [])


def wall_name(w: str) -> str: return {"N": "north", "S": "south", "E": "east", "W": "west"}[w]


def kind_of(room_type: str | None) -> str | None: return ROOM_KIND.get((room_type or "").upper())


def rank(catalogue: list[dict], styles, tier: str) -> list[dict]:
    """Annotate each item with its preference: matching style first (when a style was asked for), then the tier's price order."""
    want_styles = {s.strip().lower() for s in (styles or []) if s and s.strip()}
    out = []
    for c in catalogue:
        tags = {t.strip() for t in (c.get("style") or "").lower().split(",") if t.strip()}
        price = float(c["price"])
        out.append({**c, "_pref": (0 if not want_styles or tags & want_styles else 1, price if tier == "BUDGET" else -price if tier == "PREMIUM" else 0)})
    return out


def fit_budget(p: Plan, cat, cost, budget: Decimal):
    """Over budget → swap item groups for the next cheaper catalogue item that fits the same spot (biggest saving first), then drop extras."""
    total = cost(p.objs)
    if total <= budget: return
    tried = set(); swaps = []
    while total > budget:
        best = None
        groups = {}
        for o in p.objs:
            slot, item = p.slot_of.get(o.id, (None, None))
            if slot and slot not in NO_SWAP and not (slot == "bed" and p.in_slot("bedside")): groups.setdefault((slot, item["sku"]), []).append(o)
        for (slot, sku), objs in groups.items():
            item = p.slot_of[objs[0].id][1]
            alts = [c for c in candidates(cat, slot) if float(c["price"]) < float(item["price"]) and c["length_mm"] <= item["length_mm"] + 0.01
                    and c["width_mm"] <= item["width_mm"] + 0.01 and (slot, sku, c["sku"]) not in tried]
            if not alts: continue
            alt = max(alts, key=lambda c: float(c["price"]))                             # the next step down, not the cheapest
            saving = (float(item["price"]) - float(alt["price"])) * len(objs)
            if best is None or saving > best[0]: best = (saving, slot, sku, objs, item, alt)
        if not best: break
        _, slot, sku, objs, item, alt = best; tried.add((slot, sku, alt["sku"]))
        news = [resize(p, o, item, alt) for o in objs]
        if not all(p.ok(n, ignore={o.id}) for o, n in zip(objs, news)): continue
        for o, n in zip(objs, news):
            p.objs[p.objs.index(o)] = n; p.slot_of[n.id] = (slot, alt)
        swaps.append(f"{item['name']} → {alt['name']}" + (f" (×{len(objs)})" if len(objs) > 1 else "")); total = cost(p.objs)
    dropped = []
    for slot in DROPPABLE:
        if total <= budget: break
        for o in p.in_slot(slot):
            p.remove(o.id); dropped.append(o.name)
        total = cost(p.objs)
    if swaps: p.notes.append(f"To fit the ₹{inr(budget)} budget: " + "; ".join(swaps) + ".")
    if dropped: p.notes.append("Left out to stay within budget: " + ", ".join(dict.fromkeys(dropped)) + ".")
    if total > budget: p.notes.append(f"Still ₹{inr(total - budget)} over the ₹{inr(budget)} budget with the cheapest items that fit — raise the budget or add cheaper items to the catalogue.")


def resize(p: Plan, o: Obj, item: dict, alt: dict) -> Obj:
    """The cheaper item in the same spot: back against the same wall, centred where the old one was."""
    along_x = abs(o.length - item["length_mm"]) < 0.5 and abs(o.width - item["width_mm"]) < 0.5
    L, W = (alt["length_mm"], alt["width_mm"]) if along_x else (alt["width_mm"], alt["length_mm"])
    x, y = o.x + (o.length - L) / 2, o.y + (o.width - W) / 2
    wall = p.wall.get(o.id)
    if wall == "S": y = o.y
    elif wall == "N": y = o.y + o.width - W
    elif wall == "W": x = o.x
    elif wall == "E": x = o.x + o.length - L
    return Obj(o.id, alt["name"], alt["category"], x, y, L, W, alt["height_mm"], float(alt["price"]), alt.get("sku", "") or "", o.z)


def plan(room: Room, room_type: str, catalogue: list[dict], options: dict | None = None, all_items: list[dict] | None = None,
         styles=None, budget: Decimal | None = None, cost=None) -> dict:
    """Lay out one room. Returns objects (Obj), notes (why each thing went where / was left out) and missing catalogue categories.
    styles: style words from the brief (preferred items); options['tier']: BUDGET | BALANCED | PREMIUM; budget + cost(objs)->Decimal: fit the total."""
    kind = kind_of(room_type) or ((room_type or "").upper() if (room_type or "").upper() in KINDS else None)
    if not kind:
        raise LayoutError(f"Automatic layouts cover bedrooms, living, dining, kitchen, study, bathroom, utility / wash area, verandah / balcony, foyer, pooja and store rooms — not {room_type}. "
                          "Pick a layout type, or place items by hand in the 3D editor.")
    opts = options or {}; p = Plan(room, kind)
    tier = (opts.get("tier") or "BALANCED").upper()
    if tier not in TIERS: raise LayoutError(f"Tier must be one of {', '.join(TIERS)}")
    catalogue = rank(catalogue, styles, tier)
    for slot in REQUIRED[kind] + OPTIONAL[kind]:
        if slot in OPTIONAL[kind] and not want(opts, slot): continue
        if not candidates(catalogue, slot):
            stocked = all_items is not None and candidates(all_items, slot)
            p.missing.append({"slot": slot, "label": LABEL[slot], "required": slot in REQUIRED[kind], "out_of_stock": bool(stocked),
                              "categories": list(SLOTS[slot][:1])})
    PLANNERS[kind](p, catalogue, opts)
    if styles and p.objs:
        want_s = {s.lower() for s in styles}
        hits = [o for o in p.objs if {t.strip() for t in (p.slot_of.get(o.id, (None, {}))[1].get("style") or "").lower().split(",")} & want_s]
        p.notes.append(f"Style '{', '.join(styles)}': {len(hits)} of {len(p.objs)} item(s) match" + ("." if len(hits) == len(p.objs) else
                       " — tag more catalogue items with this style to get a closer match."))
    if budget is not None and cost is not None and p.objs: fit_budget(p, catalogue, cost, Decimal(str(budget)))
    return {"kind": kind, "objects": p.objs, "notes": p.notes, "missing": p.missing, "walls": {o.id: p.wall[o.id] for o in p.objs if o.id in p.wall}}
