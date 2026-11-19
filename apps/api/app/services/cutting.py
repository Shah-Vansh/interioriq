"""Cutting list for in-house carcass furniture (wardrobes, TV units, study units …) from its overall size, and board nesting.
Deterministic rules, no LLM. It is a production ESTIMATE from the outer size (carcass + shelves + partitions + shutters + back),
good for ordering boards and planning the cutting; the workshop still checks the final drawing.

Size convention (same as the catalogue / 3D editor): length_mm = width along the wall, width_mm = depth, height_mm = height."""
import math

MANUFACTURED = {"wardrobe", "tv unit", "study", "dresser", "shoe rack", "kitchen", "side table", "storage", "bookshelf", "vanity", "crockery", "cabinet",
                "kitchen sink", "kitchen hob", "kitchen wall", "linen cabinet", "mirror cabinet", "utility base", "utility tall", "utility wall"}
T, BACK_T = 18, 8                     # board thicknesses (mm)
SHEET_L, SHEET_W, KERF = 2440, 1220, 4  # 8 x 4 ft sheet, saw kerf
BOARD = {T: "18mm carcass board", BACK_T: "8mm back panel"}


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


def panels(L: float, D: float, H: float) -> list[dict]:
    W = L
    bays = max(1, math.ceil(W / 900))                       # vertical partition roughly every 900 mm
    parts = bays - 1
    bay_w = (W - 2 * T - parts * T) / bays
    shelves_per_bay = 1 if H < 900 else max(1, round(H / 450) - 1)
    doors = max(1, round(W / 450))
    door_w, door_h = W / doors - 3, H - 3
    raw = [("Side", H, D, 2, T, H * 2), ("Top", W - 2 * T, D, 1, T, W - 2 * T), ("Bottom", W - 2 * T, D, 1, T, W - 2 * T)]
    if parts: raw.append(("Partition", H - 2 * T, D, parts, T, (H - 2 * T) * parts))
    raw.append(("Shelf", bay_w, D - 20, shelves_per_bay * bays, T, bay_w * shelves_per_bay * bays))
    raw.append(("Shutter", door_h, door_w, doors, T, 2 * (door_h + door_w) * doors))
    raw.append(("Back", W, H, 1, BACK_T, 0))
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


def cut_list(L: float, D: float, H: float) -> dict:
    p = panels(L, D, H)
    by_t: dict[int, list] = {}
    for x in p: by_t.setdefault(x["thickness"], []).extend([(x["length"], x["width"])] * x["qty"])
    sheets = {}
    for th, pcs in by_t.items():
        n, util = nest(pcs); sheets[str(th)] = {"board": BOARD[th], "sheets": n, "utilisation_pct": round(util * 100, 1)}
    return {"size": {"length": L, "depth": D, "height": H}, "panels": p, "sheets": sheets,
            "edge_band_m": round(sum(x["edge_m"] for x in p), 2), "basis": "Estimate from outer size: 18mm carcass, 8mm back, partitions every ~900mm, shelves every ~450mm, shutters ~450mm wide."}
