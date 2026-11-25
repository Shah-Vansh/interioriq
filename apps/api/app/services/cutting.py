"""Cutting list for in-house carcass furniture (wardrobes, TV units, study units …) from its overall size, and board nesting.
Deterministic rules, no LLM. It is a production ESTIMATE from the outer size (carcass + shelves + partitions + shutters + back),
good for ordering boards and planning the cutting; the workshop still checks the final drawing.

Size convention (same as the catalogue / 3D editor): length_mm = width along the wall, width_mm = depth, height_mm = height."""
import math

MANUFACTURED = {"wardrobe", "tv unit", "study", "dresser", "shoe rack", "kitchen", "side table", "storage", "bookshelf", "vanity", "crockery", "cabinet",
                "kitchen sink", "kitchen hob", "kitchen wall", "linen cabinet", "mirror cabinet", "utility base", "utility tall", "utility wall"}
T, BACK_T = 18, 8                     # board thicknesses (mm)
SHEET_L, SHEET_W, KERF = 2440, 1220, 4  # 8 x 4 ft sheet, saw kerf
BOARD = {T: "18mm carcass board", BACK_T: "8mm back panel", 12: "12mm drawer board"}


def is_manufactured(category: str | None, L, W, H) -> bool:
    return (category or "").strip().lower() in MANUFACTURED and all(v and v > 0 for v in (L, W, H))


def _fit(a: float, b: float) -> list[tuple[float, float, int]]:
    """Split a panel that is larger than a sheet into equal pieces that fit (pieces are joined on site). Returns [(len, wid, pieces)]."""
    a, b = max(a, b), min(a, b)
    if a <= SHEET_L and b <= SHEET_W: return [(a, b, 1)]
    na = math.ceil(a / SHEET_L) if a > SHEET_L else 1
    nb = math.ceil(b / SHEET_W) if b > SHEET_W else 1
    pa, pb = a / na, b / nb
    return [(round(max(pa, pb)), round(min(pa, pb)), na * nb)]


PLINTH = 100                          # floor kitchen / utility / vanity units stand on a plinth (not part of the carcass height)
DRAWERS = 3


def wardrobe_layout(L: float, D: float, H: float) -> dict:
    """Internal layout of a wardrobe (shared by the cutting list, the shop drawing and the working drawings): shutters ~450 mm in pairs,
    one bay per pair; the middle bay(s) are HANGING (rod near the top, a row of two small drawers + two full drawers at the bottom), the
    others SHELVES (equal shelves ~350 mm apart). A single wardrobe bay is hanging."""
    doors = max(1, round(L / 450)); door_w = L / doors
    groups = [2] * (doors // 2) + ([1] if doors % 2 else [])
    n = len(groups); inner = L - 2 * T - (n - 1) * T
    widths = [inner * g / doors for g in groups]
    kinds = ["HANGING"] if n == 1 else ["SHELVES", "HANGING"] if n == 2 else ["SHELVES"] + ["HANGING"] * (n - 2) + ["SHELVES"]
    bays, x = [], T
    CH = H - 2 * T
    for w, k in zip(widths, kinds):
        b = {"x0": round(x), "x1": round(x + w), "kind": k, "width": round(w)}
        if k == "SHELVES": b["shelves"] = max(3, round(CH / 350) - 1)
        else: b.update(rod_from_top=80, small_drawers=2 if w >= 600 else 1, drawers=2, drawer_h=220, small_h=160)
        bays.append(b); x += w + T
    return {"doors": doors, "door_w": round(door_w), "bays": bays, "partitions": [round(b["x1"]) for b in bays[:-1]]}


def unit_kind(category: str | None, H: float) -> str | None:
    """None = generic carcass (old behaviour). sink / hob / base (floor units on a plinth), wall, tall — shared with the shop drawings."""
    cat = (category or "").strip().lower()
    if not cat: return None
    if cat == "wardrobe": return "wardrobe"
    if cat == "kitchen sink": return "sink"
    if cat == "kitchen hob": return "hob"
    if cat in ("kitchen wall", "utility wall", "mirror cabinet"): return "wall"
    if H >= 1800: return "tall"
    if H <= 1000 and cat in ("kitchen", "utility base", "vanity"): return "base"
    return "unit"


def panels(L: float, D: float, H: float, category: str | None = None) -> list[dict]:
    """Panels of one unit. With a category the unit type is respected: floor units lose the plinth from the carcass height (+ a plinth
    board), sink units have no shelf, hob units are a 3-drawer stack (fronts + drawer boxes) instead of shutters."""
    W = L; kind = unit_kind(category, H)
    plinth = PLINTH if kind in ("base", "sink", "hob") else 0
    CH = H - plinth                                          # carcass height
    bays = max(1, math.ceil(W / 900))                       # vertical partition roughly every 900 mm
    parts = bays - 1
    bay_w = (W - 2 * T - parts * T) / bays
    shelves_per_bay = 0 if kind in ("sink", "hob") else 1 if CH < 900 else max(1, round(CH / 450) - 1)
    doors = max(1, round(W / 450))
    door_w, door_h = W / doors - 3, CH - 3
    if kind == "wardrobe":                                   # internal layout = wardrobe_layout (shelf bays + hanging bays with drawers)
        wl = wardrobe_layout(W, D, CH)
        raw = [("Side", CH, D, 2, T, CH * 2), ("Top", W - 2 * T, D, 1, T, W - 2 * T), ("Bottom", W - 2 * T, D, 1, T, W - 2 * T)]
        if wl["partitions"]: raw.append(("Partition", CH - 2 * T, D, len(wl["partitions"]), T, (CH - 2 * T) * len(wl["partitions"])))
        for b in wl["bays"]:
            if b["kind"] == "SHELVES": raw.append(("Shelf", b["width"], D - 20, b["shelves"], T, b["width"] * b["shelves"]))
            else:
                raw.append(("Drawer front", b["width"] - 3, b["drawer_h"] - 3, b["drawers"], T, 2 * (b["width"] + b["drawer_h"]) * b["drawers"]))
                sw = b["width"] / b["small_drawers"]
                raw.append(("Small drawer front", sw - 3, b["small_h"] - 3, b["small_drawers"], T, 2 * (sw + b["small_h"]) * b["small_drawers"]))
                k = b["drawers"] + b["small_drawers"]
                raw.append(("Drawer side", D - 60, 140, 2 * k, T, 0)); raw.append(("Drawer bottom", b["width"] - 30, D - 60, k, BACK_T, 0))
                raw.append(("Shelf above drawers", b["width"], D - 20, 1, T, b["width"]))
        raw.append(("Shutter", CH - 3, wl["door_w"] - 3, wl["doors"], T, 2 * (CH - 3 + wl["door_w"] - 3) * wl["doors"]))
        raw.append(("Back", W, CH, 1, BACK_T, 0))
        out = []
        for name, a, b, qty, th, edge in raw:
            for pl, pw, pieces in _fit(a, b):
                out.append({"name": name + (f" (in {pieces} pieces)" if pieces > 1 else ""), "length": int(round(pl)), "width": int(round(pw)),
                            "qty": int(qty * pieces), "thickness": th, "edge_m": round(edge / 1000, 2)})
        return out
    raw = [("Side", CH, D, 2, T, CH * 2), ("Top", W - 2 * T, D, 1, T, W - 2 * T), ("Bottom", W - 2 * T, D, 1, T, W - 2 * T)]
    if parts: raw.append(("Partition", CH - 2 * T, D, parts, T, (CH - 2 * T) * parts))
    if shelves_per_bay: raw.append(("Shelf", bay_w, D - 20, shelves_per_bay * bays, T, bay_w * shelves_per_bay * bays))
    if kind == "hob":
        dh = CH / DRAWERS
        raw.append(("Drawer front", W - 3, dh - 3, DRAWERS, T, 2 * (W - 3 + dh - 3) * DRAWERS))
        raw.append(("Drawer side", D - 50, dh - 80, 2 * DRAWERS, T, (D - 50) * 2 * DRAWERS))
        raw.append(("Drawer back / inner front", bay_w - 26 - 2 * T, dh - 80, 2 * DRAWERS, T, (bay_w - 26 - 2 * T) * 2 * DRAWERS))
        raw.append(("Drawer bottom", bay_w - 26, D - 50, DRAWERS, BACK_T, 0))
    else:
        raw.append(("Shutter", door_h, door_w, doors, T, 2 * (door_h + door_w) * doors))
    raw.append(("Back", W, CH, 1, BACK_T, 0))
    if plinth: raw.append(("Plinth", W - 40, plinth, 1, T, W - 40))
    out = []
    for name, a, b, qty, th, edge in raw:
        for pl, pw, pieces in _fit(a, b):
            out.append({"name": name + (f" (in {pieces} pieces)" if pieces > 1 else ""), "length": int(round(pl)), "width": int(round(pw)),
                        "qty": int(qty * pieces), "thickness": th, "edge_m": round(edge / 1000, 2)})
    return out


def nest(pcs: list[tuple[int, int]]) -> tuple[int, float]:
    """First-fit-decreasing shelf packing on SHEET_L x SHEET_W with kerf. Returns (sheets, utilisation 0..1)."""
    items = sorted(((max(a, b), min(a, b)) for a, b in pcs), key=lambda p: (-p[1], -p[0]))
    sheets: list[list[list[float]]] = []           # sheet -> shelves [y, height, x_used]
    used_h: list[float] = []
    for l, w in items:
        placed = False
        for si, shelves in enumerate(sheets):
            for sh in shelves:
                if w <= sh[1] and sh[2] + l <= SHEET_L: sh[2] += l + KERF; placed = True; break
            if not placed and used_h[si] + w <= SHEET_W:
                shelves.append([used_h[si], w, l + KERF]); used_h[si] += w + KERF; placed = True
            if placed: break
        if not placed:
            sheets.append([[0, w, l + KERF]]); used_h.append(w + KERF)
    area = sum(l * w for l, w in items)
    return len(sheets), (area / (len(sheets) * SHEET_L * SHEET_W) if sheets else 0.0)


def cut_list(L: float, D: float, H: float, category: str | None = None) -> dict:
    p = panels(L, D, H, category)
    by_t: dict[int, list] = {}
    for x in p: by_t.setdefault(x["thickness"], []).extend([(x["length"], x["width"])] * x["qty"])
    sheets = {}
    for th, pcs in by_t.items():
        n, util = nest(pcs); sheets[str(th)] = {"board": BOARD[th], "sheets": n, "utilisation_pct": round(util * 100, 1)}
    return {"size": {"length": L, "depth": D, "height": H}, "panels": p, "sheets": sheets,
            "edge_band_m": round(sum(x["edge_m"] for x in p), 2), "kind": unit_kind(category, H), "category": category,
            "basis": "Estimate from outer size: 18mm carcass, 8mm back, partitions every ~900mm, shelves every ~450mm, shutters ~450mm wide"
                     + ("; floor unit on a 100mm plinth" if unit_kind(category, H) in ("base", "sink", "hob") else "")
                     + ("; 3-drawer stack" if unit_kind(category, H) == "hob" else "; no shelf (sink)" if unit_kind(category, H) == "sink" else "") + "."}
