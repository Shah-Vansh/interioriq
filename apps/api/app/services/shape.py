"""Room shape, walls and ceiling (M41) — deterministic, shared by validation, the layout generator, drawings, take-off and 3D.

Plan coordinates: origin at the south-west corner of the room's bounding box, x east (Length), y north (Width), mm.

Shapes
  RECT     (default) the L × W rectangle
  CUTS     the rectangle with a rectangular notch taken out of one or more corners: {"type": "CUTS", "cuts": {"NE": [l, w], ...}}
           l = along x, w = along y. One cut = L-shaped room, two = U/T-ish, four = plus-shaped.
  POLYGON  any outline (angled walls, odd rooms): {"type": "POLYGON", "points": [[x, y], ...]} that fills the L × W box (touches all four sides)

Walls = outline edges, numbered from 0 (counter-clockwise, edge i runs from point i to point i+1). An opening is either on a side of the
box (wall N/E/S/W + offset from the west / south end — the pre-M41 rule) or on edge #i (offset from that edge's start point).

Ceilings
  FLAT     one height (the room's Ceiling Height measurement)
  SLOPED   {"type": "SLOPED", "low": mm, "high": mm, "high_wall": "N"}: rises evenly from the opposite side to the high side
  UNEVEN   {"type": "UNEVEN", "points": [[x, y, h], ...]} heights measured at spots; between them the height is blended
           (inverse-distance), and anything is checked against the LOWEST height over its footprint, so nothing is placed by guessing high.
"""
import math

from shapely.geometry import Polygon, box
from shapely.geometry.polygon import orient

CORNERS = ("SW", "SE", "NE", "NW")
SIDES = ("N", "E", "S", "W")
TOL = 1.0                      # mm
MIN_WALL = 300                 # mm — shortest wall / narrowest leftover strip accepted
MIN_H, MAX_H = 1800, 9000      # ceiling heights accepted (mm)


class ShapeError(ValueError): pass


# ── outline ──────────────────────────────────────────────────────────────────
def outline(L: float, W: float, shape: dict | None) -> list[tuple[float, float]]:
    """Counter-clockwise outline, starting at the south-west. A shape that no longer fits the measurements falls back to the rectangle."""
    pts = _raw_outline(L, W, shape)
    if len(pts) > 4:
        pg = Polygon(pts)
        if not pg.is_valid or pg.area <= 0: return [(0.0, 0.0), (float(L), 0.0), (float(L), float(W)), (0.0, float(W))]
    return pts


def _raw_outline(L: float, W: float, shape: dict | None) -> list[tuple[float, float]]:
    t = (shape or {}).get("type") or "RECT"
    if t == "POLYGON": return [(float(x), float(y)) for x, y in shape["points"]]
    cuts = (shape or {}).get("cuts") or {} if t == "CUTS" else {}
    pts: list = []
    a, b = cuts.get("SW") or (0, 0); pts += [(0, b), (a, b), (a, 0)] if a and b else [(0, 0)]
    a, b = cuts.get("SE") or (0, 0); pts += [(L - a, 0), (L - a, b), (L, b)] if a and b else [(L, 0)]
    a, b = cuts.get("NE") or (0, 0); pts += [(L, W - b), (L - a, W - b), (L - a, W)] if a and b else [(L, W)]
    a, b = cuts.get("NW") or (0, 0); pts += [(a, W), (a, W - b), (0, W - b)] if a and b else [(0, W)]
    return [(float(x), float(y)) for x, y in pts]


def polygon(L: float, W: float, shape: dict | None) -> Polygon:
    t = (shape or {}).get("type") or "RECT"
    return box(0, 0, L, W) if t == "RECT" else Polygon(outline(L, W, shape))


def is_rect(shape: dict | None) -> bool:
    return ((shape or {}).get("type") or "RECT") == "RECT" or ((shape or {}).get("type") == "CUTS" and not (shape or {}).get("cuts"))


def clean_shape(L: float, W: float, shape: dict | None) -> dict | None:
    """Validate + normalise a shape for a room of L × W (raises ShapeError with a reason a person understands)."""
    if not shape: return None
    t = str(shape.get("type") or "RECT").upper()
    if t == "RECT": return None
    if t == "CUTS":
        raw = shape.get("cuts") or {}
        if not isinstance(raw, dict): raise ShapeError("cuts must be {corner: [length, width]}")
        cuts = {}
        for k, v in raw.items():
            k = str(k).upper()
            if k not in CORNERS: raise ShapeError(f"Unknown corner '{k}' (use SW, SE, NE or NW)")
            try: a, b = float(v[0]), float(v[1])
            except Exception: raise ShapeError(f"Cut at {k} needs [length, width] in mm")
            if a <= 0 and b <= 0: continue
            if a < MIN_WALL or b < MIN_WALL: raise ShapeError(f"Cut at {k}: each side must be at least {MIN_WALL} mm (got {a:.0f} × {b:.0f})")
            if a > L - MIN_WALL or b > W - MIN_WALL: raise ShapeError(f"Cut at {k} ({a:.0f} × {b:.0f}) leaves less than {MIN_WALL} mm of the {L:.0f} × {W:.0f} room")
            cuts[k] = [round(a), round(b)]
        for (c1, c2, i, lim, side) in (("SW", "SE", 0, L, "south"), ("NW", "NE", 0, L, "north"), ("SW", "NW", 1, W, "west"), ("SE", "NE", 1, W, "east")):
            if c1 in cuts and c2 in cuts and cuts[c1][i] + cuts[c2][i] > lim - MIN_WALL:
                raise ShapeError(f"The {c1} and {c2} cuts leave less than {MIN_WALL} mm of the {side} wall")
        if not cuts: return None
        s = {"type": "CUTS", "cuts": cuts}
        if not Polygon(_raw_outline(L, W, s)).is_valid: raise ShapeError("These cuts don't leave one connected room")
        return s
    if t == "POLYGON":
        raw = shape.get("points") or []
        if not (3 <= len(raw) <= 24): raise ShapeError("An outline needs 3 to 24 corner points")
        try: pts = [(round(float(p[0])), round(float(p[1]))) for p in raw]
        except Exception: raise ShapeError("Each point must be [x, y] in mm")
        pg = Polygon(pts)
        if not pg.is_valid or pg.area <= 0: raise ShapeError("The outline crosses itself — list the corners in order around the room")
        x0, y0, x1, y1 = pg.bounds
        if abs(x0) > TOL or abs(y0) > TOL or abs(x1 - L) > 5 or abs(y1 - W) > 5:
            raise ShapeError(f"The outline must fill the {L:.0f} × {W:.0f} mm box (Length × Width): its extent is {x1 - x0:.0f} × {y1 - y0:.0f} mm from ({x0:.0f}, {y0:.0f})")
        pg = orient(pg, 1.0)                                                 # counter-clockwise
        c = list(pg.exterior.coords)[:-1]
        k = min(range(len(c)), key=lambda i: (round(c[i][1]), c[i][0]))      # start at the south-most, then west-most corner
        c = c[k:] + c[:k]
        for i in range(len(c)):
            if math.dist(c[i], c[(i + 1) % len(c)]) < 100: raise ShapeError("Two corners are closer than 100 mm — remove one")
        return {"type": "POLYGON", "points": [[round(x), round(y)] for x, y in c]}
    raise ShapeError("shape type must be RECT, CUTS or POLYGON")


# ── walls ────────────────────────────────────────────────────────────────────
def compass(nx: float, ny: float) -> str:
    """N/E/S/W that an OUTWARD normal points to (the dominant axis)."""
    return ("E" if nx > 0 else "W") if abs(nx) > abs(ny) + 1e-9 else ("N" if ny > 0 else "S")


def edges(L: float, W: float, shape: dict | None) -> list[dict]:
    pts = outline(L, W, shape); out = []
    for i, (a, b) in enumerate(zip(pts, pts[1:] + pts[:1])):
        dx, dy = b[0] - a[0], b[1] - a[1]; ln = math.hypot(dx, dy)
        if ln < 1e-6: continue
        ux, uy = dx / ln, dy / ln
        side = ("S" if abs(a[1]) < TOL and abs(b[1]) < TOL else "N" if abs(a[1] - W) < TOL and abs(b[1] - W) < TOL else
                "W" if abs(a[0]) < TOL and abs(b[0]) < TOL else "E" if abs(a[0] - L) < TOL and abs(b[0] - L) < TOL else None)
        out.append({"i": i, "x0": a[0], "y0": a[1], "x1": b[0], "y1": b[1], "length": round(ln, 1), "ux": ux, "uy": uy,
                    "nx": -uy, "ny": ux,                                   # inward normal (CCW outline: interior on the left)
                    "wall": compass(uy, -ux), "side": side})
    return out


def resolve_opening(L: float, W: float, shape: dict | None, o: dict) -> dict:
    """The opening's two end points on its wall line + inward normal. Raises ShapeError when it doesn't sit on a wall."""
    es = edges(L, W, shape); off, w = float(o["offset"]), float(o["width"])
    if o.get("edge") is not None:
        e = next((e for e in es if e["i"] == o["edge"]), None)
        if not e: raise ShapeError(f"The room has no wall #{o['edge'] + 1} (walls 1–{len(es)})")
        if off < -TOL or off + w > e["length"] + TOL: raise ShapeError(f"The opening runs past the end of wall #{e['i'] + 1} ({off:.0f} + {w:.0f} > {e['length']:.0f} mm)")
        x0, y0 = e["x0"] + e["ux"] * off, e["y0"] + e["uy"] * off
        x1, y1 = e["x0"] + e["ux"] * (off + w), e["y0"] + e["uy"] * (off + w)
        wall = e["wall"]
        proj = min(x0, x1) if wall in "NS" else min(y0, y1)               # pre-M41 readers: the position along the N/S (x) or E/W (y) axis
        return {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "nx": e["nx"], "ny": e["ny"], "wall": wall, "offset": proj, "edge": e["i"], "angled": e["side"] is None}
    wall = o["wall"]
    a, b = off, off + w
    x0, y0, x1, y1 = {"S": (a, 0, b, 0), "N": (a, W, b, W), "W": (0, a, 0, b), "E": (L, a, L, b)}[wall]
    nx, ny = {"S": (0, 1), "N": (0, -1), "W": (1, 0), "E": (-1, 0)}[wall]
    if not is_rect(shape):                                                # must lie on a real wall on that side (not across a cut)
        ok = False
        for e in es:
            if e["side"] != wall: continue
            lo, hi = (min(e["x0"], e["x1"]), max(e["x0"], e["x1"])) if wall in "NS" else (min(e["y0"], e["y1"]), max(e["y0"], e["y1"]))
            if a >= lo - TOL and b <= hi + TOL: ok = True; break
        if not ok:
            spans = ", ".join(f"{(min(e['x0'], e['x1']) if wall in 'NS' else min(e['y0'], e['y1'])):.0f}–{(max(e['x0'], e['x1']) if wall in 'NS' else max(e['y0'], e['y1'])):.0f}"
                              for e in es if e["side"] == wall) or "none"
            raise ShapeError(f"There is no wall on the {wall} side at {a:.0f}–{b:.0f} mm (the {wall} side has wall at {spans} mm) — pick the wall by number instead")
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "nx": nx, "ny": ny, "wall": wall, "offset": off, "edge": None, "angled": False}


# ── ceiling ──────────────────────────────────────────────────────────────────
def clean_ceiling(L: float, W: float, prof: dict | None) -> dict | None:
    if not prof: return None
    t = str(prof.get("type") or "FLAT").upper()
    if t == "FLAT": return None
    if t == "SLOPED":
        try: lo, hi = float(prof["low"]), float(prof["high"])
        except Exception: raise ShapeError("A sloped ceiling needs low and high heights (mm)")
        hw = str(prof.get("high_wall") or "").upper()
        if hw not in SIDES: raise ShapeError("high_wall must be N, E, S or W (the side where the ceiling is highest)")
        if not (MIN_H <= lo <= MAX_H and MIN_H <= hi <= MAX_H): raise ShapeError(f"Ceiling heights must be {MIN_H}–{MAX_H} mm")
        if hi <= lo: raise ShapeError("high must be more than low (for a level ceiling choose FLAT)")
        return {"type": "SLOPED", "low": round(lo), "high": round(hi), "high_wall": hw}
    if t == "UNEVEN":
        raw = prof.get("points") or []
        if not (2 <= len(raw) <= 30): raise ShapeError("Measure the height at 2 to 30 spots")
        pts = []
        for p in raw:
            try: x, y, h = float(p[0]), float(p[1]), float(p[2])
            except Exception: raise ShapeError("Each spot must be [x, y, height] in mm")
            if not (-TOL <= x <= L + TOL and -TOL <= y <= W + TOL): raise ShapeError(f"Spot ({x:.0f}, {y:.0f}) is outside the room")
            if not MIN_H <= h <= MAX_H: raise ShapeError(f"Ceiling heights must be {MIN_H}–{MAX_H} mm (got {h:.0f})")
            pts.append([round(x), round(y), round(h)])
        return {"type": "UNEVEN", "points": pts}
    raise ShapeError("ceiling type must be FLAT, SLOPED or UNEVEN")


def ceiling_at(prof: dict | None, H: float, L: float, W: float, x: float, y: float) -> float:
    t = (prof or {}).get("type") or "FLAT"
    if t == "SLOPED":
        hw = prof["high_wall"]
        f = {"N": y / W, "S": 1 - y / W, "E": x / L, "W": 1 - x / L}[hw] if L and W else 0
        return prof["low"] + (prof["high"] - prof["low"]) * min(1.0, max(0.0, f))
    if t == "UNEVEN":
        num = den = 0.0
        for px, py, h in prof["points"]:
            d2 = (x - px) ** 2 + (y - py) ** 2
            if d2 < 1: return float(h)
            num += h / d2; den += 1 / d2
        return num / den
    return float(H)


def ceiling_range(prof: dict | None, H: float, L: float, W: float) -> tuple[float, float]:
    t = (prof or {}).get("type") or "FLAT"
    if t == "SLOPED": return float(prof["low"]), float(prof["high"])
    if t == "UNEVEN": hs = [p[2] for p in prof["points"]]; return float(min(hs)), float(max(hs))
    return float(H), float(H)


def lowest_over(prof: dict | None, H: float, L: float, W: float, poly) -> float:
    """Lowest ceiling over a footprint (corners, edge midpoints, centre — the profile is linear / smooth, so that's where the minimum is)."""
    if not prof: return float(H)
    if prof.get("type") == "UNEVEN":                                       # a measured spot inside the footprint can be the lowest
        inside = [p[2] for p in prof["points"] if poly.buffer(1).contains(box(p[0], p[1], p[0] + 0.1, p[1] + 0.1))]
    else: inside = []
    cs = list(poly.exterior.coords)[:-1]
    pts = cs + [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(cs, cs[1:] + cs[:1])] + [tuple(poly.centroid.coords)[0]]
    return min([ceiling_at(prof, H, L, W, x, y) for x, y in pts] + inside)
