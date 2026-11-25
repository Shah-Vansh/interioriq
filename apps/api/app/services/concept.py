"""Interior design concept — the creative layer a designer adds on top of the furniture layout: wall colours, a feature (accent) wall,
false-ceiling design, flooring, curtains, rugs, wall art, plants and decorative lights, all from ONE style guide applied consistently to
every room (the way a design studio works from a style book). Deterministic rules, no LLM (constraint 2): the same room + style always
gives the same concept, and every choice can be changed per room.

A room's concept ("finishes") is stored with its design version (design_json["finishes"]); applying or editing it saves a NEW version, so
design history is never overwritten. Geometry (furniture, validation) is untouched; finishes are drawn in 3D, priced through take-off
quantities and printed in the design presentation.

Coordinates are the room's own (mm, x east, y north, origin south-west), like the furniture."""
from __future__ import annotations

ACCENT_TYPES = {"FLUTED_WOOD": "Fluted wood panelling", "WALLPAPER": "Designer wallpaper", "STONE": "Stone cladding", "PANELLING": "Moulded wall panelling",
                "PAINT": "Accent paint", "TILE": "Feature tiles", "JAALI": "Backlit jaali panel", "BRICK": "Exposed brick cladding"}
CEILINGS = {"COVE": "Peripheral false ceiling with cove LED", "ISLAND": "Island false ceiling with cove LED", "PLAIN": "Plain ceiling (paint)",
            "GRID": "Moisture-resistant grid ceiling", "RAFTER": "Wooden rafter ceiling"}
FLOORS = {"WOOD": "Engineered wood / laminate planks", "MARBLE": "Marble / large-format vitrified tiles", "TILE": "Anti-skid ceramic tiles",
          "TERRAZZO": "Terrazzo", "CONCRETE": "Polished concrete finish", "STONE": "Natural stone (Kota / sandstone)"}

STYLES = {
    "modern": {"label": "Modern", "idea": "Clean lines, warm walnut, soft greys and a single bold feature wall; layered lighting with hidden cove LEDs.",
               "wall": "#efebe5", "accent": "#6b4a32", "wood": "#6b4226", "fabric": "#7d8794", "metal": "#2b2b2b", "floor": ("WOOD", "#b88a5a"),
               "accents": {"BEDROOM": "FLUTED_WOOD", "LIVING": "FLUTED_WOOD", "DINING": "PANELLING", "FOYER": "PANELLING", "POOJA": "JAALI", "BATHROOM": "TILE", "KITCHEN": "TILE"},
               "curtain": "#cfc6b8", "rug": "#8a8f96", "art": ["#2f4f6f", "#c7a24a", "#e9e4dc"], "plants": True},
    "minimal": {"label": "Minimal", "idea": "Calm whites and light oak, almost no clutter, hidden storage, one quiet textured wall.",
                "wall": "#f6f4f0", "accent": "#d9d2c5", "wood": "#c8a77e", "fabric": "#d8d2c8", "metal": "#9ca3af", "floor": ("WOOD", "#d2b48c"),
                "accents": {"BEDROOM": "PAINT", "LIVING": "PANELLING", "DINING": "PAINT", "FOYER": "PAINT", "POOJA": "JAALI", "BATHROOM": "TILE", "KITCHEN": "TILE"},
                "curtain": "#f1ede6", "rug": "#e3ddd2", "art": ["#d9d2c5", "#b7b0a4"], "plants": True},
    "luxury": {"label": "Luxury", "idea": "Marble floors, stone and fluted feature walls, brass accents, deep jewel tones and statement lighting.",
               "wall": "#ece6dc", "accent": "#2f3b45", "wood": "#4a2e1f", "fabric": "#2f4a52", "metal": "#b08d57", "floor": ("MARBLE", "#efeae2"),
               "accents": {"BEDROOM": "PANELLING", "LIVING": "STONE", "DINING": "STONE", "FOYER": "STONE", "POOJA": "JAALI", "BATHROOM": "STONE", "KITCHEN": "STONE"},
               "curtain": "#7a6a55", "rug": "#4b5563", "art": ["#b08d57", "#1f2937", "#e5e1d8"], "plants": True},
    "scandinavian": {"label": "Scandinavian", "idea": "Bright and airy: white walls, pale wood, soft pastels, cosy textiles and lots of greenery.",
                     "wall": "#f7f6f2", "accent": "#a9b8a8", "wood": "#d6b98c", "fabric": "#c9cfd3", "metal": "#3f3f46", "floor": ("WOOD", "#dcc39a"),
                     "accents": {"BEDROOM": "PAINT", "LIVING": "PANELLING", "DINING": "WALLPAPER", "FOYER": "PAINT", "POOJA": "JAALI", "BATHROOM": "TILE", "KITCHEN": "TILE"},
                     "curtain": "#ffffff", "rug": "#d9d4c7", "art": ["#a9b8a8", "#e2c6a7", "#8aa0b8"], "plants": True},
    "traditional": {"label": "Traditional Indian", "idea": "Teak and brass, carved jaali screens, rich terracotta and mustard, stone floors and handwoven textiles.",
                    "wall": "#f2e8d8", "accent": "#9c4a2e", "wood": "#6b3f1c", "fabric": "#a64b2a", "metal": "#b08d57", "floor": ("STONE", "#c9b48e"),
                    "accents": {"BEDROOM": "JAALI", "LIVING": "PANELLING", "DINING": "WALLPAPER", "FOYER": "JAALI", "POOJA": "JAALI", "BATHROOM": "TILE", "KITCHEN": "TILE", "OUTDOOR": "STONE"},
                    "curtain": "#c08a3e", "rug": "#8c3b2f", "art": ["#9c4a2e", "#c7a24a", "#2f4f6f"], "plants": True, "ceiling_living": "RAFTER"},
    "industrial": {"label": "Industrial", "idea": "Exposed brick and concrete, black metal, dark wood and leather, Edison-style pendants.",
                   "wall": "#e4e1dc", "accent": "#8e4b36", "wood": "#4a3424", "fabric": "#5a5f66", "metal": "#1c1917", "floor": ("CONCRETE", "#a8a29e"),
                   "accents": {"BEDROOM": "BRICK", "LIVING": "BRICK", "DINING": "BRICK", "FOYER": "BRICK", "POOJA": "JAALI", "BATHROOM": "TILE", "KITCHEN": "BRICK"},
                   "curtain": "#6b6f74", "rug": "#57534e", "art": ["#1c1917", "#8e4b36", "#d6d3d1"], "plants": False},
    "boho": {"label": "Boho", "idea": "Layered textures, cane and rattan, earthy terracotta and sage, patterned rugs and plenty of plants.",
             "wall": "#f3ece1", "accent": "#c27c55", "wood": "#a0703f", "fabric": "#b5835a", "metal": "#b08d57", "floor": ("TERRAZZO", "#e6ddd0"),
             "accents": {"BEDROOM": "WALLPAPER", "LIVING": "WALLPAPER", "DINING": "PAINT", "FOYER": "WALLPAPER", "POOJA": "JAALI", "BATHROOM": "TILE", "KITCHEN": "TILE"},
             "curtain": "#e8d9c0", "rug": "#b5603c", "art": ["#c27c55", "#7d8f69", "#e2c6a7"], "plants": True},
}
WET = {"BATHROOM", "UTILITY", "KITCHEN"}
PALETTE_KEYS = ("wall", "accent", "wood", "fabric", "metal")


def kind_of(room_type: str | None) -> str:
    from app.services import layouts
    k = layouts.kind_of(room_type)
    return k or (room_type or "OTHER").upper()


def _against(o: dict, L: float, W: float) -> str:
    """Wall the object's back is against (nearest wall)."""
    d = {"S": o["y"], "N": W - (o["y"] + o["width"]), "W": o["x"], "E": L - (o["x"] + o["length"])}
    return min(d, key=d.get)


def _find(objs: list[dict], *cats: str) -> dict | None:
    cats = {c.lower() for c in cats}
    return next((o for o in objs if (o.get("category") or "").lower() in cats), None)


def _span(o: dict, wall: str) -> tuple[float, float]:
    return (o["x"], o["x"] + o["length"]) if wall in "NS" else (o["y"], o["y"] + o["width"])


def _wall_len(wall: str, L: float, W: float) -> float: return L if wall in "NS" else W


def concept(room_type: str | None, L: float, W: float, H: float, objects: list[dict], openings: list[dict], style: str) -> dict:
    if style not in STYLES: raise ValueError(f"style must be one of {', '.join(STYLES)}")
    S = STYLES[style]; kind = kind_of(room_type); wet = kind in WET; out_door = kind == "OUTDOOR"
    area = L * W / 1e6
    # feature wall: behind the bed / the TV wall / behind the console, pooja unit, crockery / the shower or vanity wall / the kitchen backsplash
    anchor = {"BEDROOM": ("bed",), "LIVING": ("tv unit",), "DINING": ("crockery", "crockery unit"), "FOYER": ("console table", "console"),
              "POOJA": ("pooja unit", "mandir"), "BATHROOM": ("shower enclosure", "vanity"), "KITCHEN": ("kitchen hob", "kitchen sink"),
              "OUTDOOR": ("outdoor chair",), "STUDY": ("study", "desk")}.get(kind, ())
    a_obj = _find(objects, *anchor) if anchor else None
    accent = None
    a_type = S["accents"].get(kind, "PAINT" if not wet else "TILE")
    if kind in ("STORE", "UTILITY") or (out_door and "OUTDOOR" not in S["accents"]): a_type = None
    if a_type:
        if a_obj: wall = _against(a_obj, L, W)
        else:
            doors = {o["wall"] for o in openings if o["kind"] == "DOOR"}
            wall = next((w for w in ("N", "E", "W", "S") if w not in doors), "N")
        wl = _wall_len(wall, L, W)
        if a_obj and kind in ("BEDROOM", "LIVING", "FOYER", "POOJA", "DINING", "STUDY"):
            s0, s1 = _span(a_obj, wall); pad = 300 if kind in ("BEDROOM", "LIVING") else 150
            x0, x1 = max(0, s0 - pad), min(wl, s1 + pad)
        else: x0, x1 = 0, wl
        h = H if a_type in ("FLUTED_WOOD", "STONE", "WALLPAPER", "BRICK", "JAALI") else min(H, 2400) if a_type == "PANELLING" else H
        if kind == "KITCHEN": h = 600                                   # backsplash band above the counter
        z0 = 900 if kind == "KITCHEN" else 0
        if kind == "POOJA": h = min(H, 2400)
        win = [o for o in openings if o["wall"] == wall]
        hole = sum(max(0, min(x1, o["offset"] + o["width"]) - max(x0, o["offset"])) * o["height"] for o in win if o["kind"] in ("WINDOW", "DOOR"))
        accent = {"wall": wall, "from": round(x0), "to": round(x1), "z0": z0, "height": round(h), "type": a_type,
                  "colour": S["wood"] if a_type == "FLUTED_WOOD" else S["accent"], "area_sqm": round(max(0, (x1 - x0) * h - hole) / 1e6, 2)}
    # false ceiling
    if wet: ceiling = {"type": "GRID" if kind == "BATHROOM" else "PLAIN"}
    elif out_door: ceiling = {"type": "RAFTER" if style == "traditional" else "PLAIN"}
    elif H < 2600 or area < 6: ceiling = {"type": "PLAIN"}
    elif kind == "LIVING" and S.get("ceiling_living"): ceiling = {"type": S["ceiling_living"]}
    elif area >= 15 and kind in ("LIVING", "DINING", "BEDROOM"): ceiling = {"type": "ISLAND", "drop": 300, "border": 900}
    else: ceiling = {"type": "COVE", "drop": 250, "border": 600}
    if ceiling["type"] in ("COVE", "ISLAND"):
        b = ceiling["border"]; ceiling["cove_rm"] = round(2 * ((L - 2 * b) + (W - 2 * b)) / 1000, 2) if ceiling["type"] == "COVE" else round(2 * ((L - 2 * b) + (W - 2 * b)) / 1000, 2)
        ceiling["gypsum_sqm"] = round((L * W - (L - 2 * b) * (W - 2 * b)) / 1e6, 2) if ceiling["type"] == "COVE" else round(((L - 2 * b) * (W - 2 * b)) / 1e6, 2)
    ceiling["label"] = CEILINGS[ceiling["type"]]
    fk, ftone = S["floor"]
    if wet: fk, ftone = "TILE", "#d6d1c8"
    if out_door: fk, ftone = ("STONE", "#b9a98a") if style in ("traditional", "boho") else ("TILE", "#c9c2b6")
    floor = {"kind": fk, "tone": ftone, "label": FLOORS[fk], "area_sqm": round(area, 2)}
    # curtains on windows (blinds in wet rooms)
    curtains = [{"id": o.get("id"), "wall": o["wall"], "offset": o["offset"], "width": o["width"], "sill": o.get("sill", 0), "height": o["height"],
                 "kind": "BLIND" if wet else "CURTAIN", "colour": "#e7e5e4" if wet else S["curtain"],
                 "rm": round((o["width"] + 300) / 1000, 2)} for o in openings if o["kind"] == "WINDOW"]
    # rug under the bed / coffee table / dining table
    rug = None
    for cats, extra in ((("coffee table", "centre table", "center table"), 500), (("dining table", "dining"), 700), (("bed",), 450)):
        t = _find(objects, *cats)
        if t:
            x0, y0 = max(100, t["x"] - extra), max(100, t["y"] - extra)
            x1, y1 = min(L - 100, t["x"] + t["length"] + extra), min(W - 100, t["y"] + t["width"] + extra)
            if cats == ("bed",): y1 = min(y1, t["y"] + t["width"] * 0.7 + extra) if _against(t, L, W) == "S" else y1
            rug = {"x": round(x0), "y": round(y0), "length": round(x1 - x0), "width": round(y1 - y0), "colour": S["rug"]}; break
    if wet or kind in ("STORE", "POOJA"): rug = None
    # art above the sofa / bed / console
    art = []
    for cats in (("sofa",), ("bed",), ("console table", "console"), ("dining table", "dining")):
        t = _find(objects, *cats)
        if not t or wet: continue
        wall = _against(t, L, W)
        if accent and accent["wall"] == wall and accent["type"] in ("FLUTED_WOOD", "STONE", "BRICK", "JAALI"): continue   # the feature wall is the art
        s0, s1 = _span(t, wall); w = min(1200, (s1 - s0) * 0.6)
        art.append({"wall": wall, "pos": round((s0 + s1) / 2 - w / 2), "width": round(w), "height": round(w * 0.6), "z": round(max(t.get("height", 800) + 250, 1350)),
                    "colours": S["art"]}); break
    # plants in free corners
    plants = []
    if S.get("plants") and not wet and kind not in ("STORE",):
        for cx, cy in ((250, 250), (L - 250, 250), (250, W - 250), (L - 250, W - 250)):
            if any(o["x"] - 200 < cx < o["x"] + o["length"] + 200 and o["y"] - 200 < cy < o["y"] + o["width"] + 200 for o in objects): continue
            if any(o["kind"] == "DOOR" and _door_near(o, cx, cy, L, W) for o in openings): continue
            plants.append({"x": round(cx), "y": round(cy)})
            if len(plants) >= (2 if area > 12 else 1): break
    # decorative lights
    lights = []
    d = _find(objects, "dining table", "dining")
    if d: lights.append({"kind": "PENDANT", "x": round(d["x"] + d["length"] / 2), "y": round(d["y"] + d["width"] / 2), "count": 3 if d["length"] >= 1500 else 1})
    b = _find(objects, "bed")
    if b and kind == "BEDROOM":
        wall = _against(b, L, W)
        for s in (-1, 1):
            if wall in "NS": lights.append({"kind": "PENDANT", "x": round(b["x"] + (b["length"] / 2 + s * (b["length"] / 2 + 250))), "y": round(b["y"] + (150 if wall == "S" else b["width"] - 150)), "count": 1, "drop": 1000})
            else: lights.append({"kind": "PENDANT", "x": round(b["x"] + (150 if wall == "W" else b["length"] - 150)), "y": round(b["y"] + (b["width"] / 2 + s * (b["width"] / 2 + 250))), "count": 1, "drop": 1000})
    if kind == "LIVING" and ceiling["type"] == "ISLAND": lights.append({"kind": "CHANDELIER", "x": round(L / 2), "y": round(W / 2), "count": 1})
    return {"style": style, "style_label": S["label"], "idea": S["idea"], "palette": {k: S[k] for k in PALETTE_KEYS}, "walls": {"colour": S["wall"]},
            "accent": accent, "ceiling": ceiling, "floor": floor, "curtains": curtains, "rug": rug, "art": art, "plants": plants, "lights": lights}


def _door_near(o: dict, cx: float, cy: float, L: float, W: float) -> bool:
    a, b = o["offset"] - 300, o["offset"] + o["width"] + 300
    return {"S": cy < 1000 and a < cx < b, "N": cy > W - 1000 and a < cx < b, "W": cx < 1000 and a < cy < b, "E": cx > L - 1000 and a < cy < b}[o["wall"]]


EDITABLE = {"accent_type": tuple(ACCENT_TYPES) + ("NONE",), "accent_wall": ("N", "E", "S", "W"), "ceiling": tuple(CEILINGS), "floor": tuple(FLOORS)}


def apply_overrides(f: dict, ov: dict, L: float, W: float, H: float) -> dict:
    """Designer's changes on top of the generated concept: feature-wall type / wall / colour, ceiling type, floor kind / tone, wall colour,
    curtain colour, rug on/off + colour, art on/off, plants on/off. Validated (unknown keys / values refused)."""
    import re
    hexc = re.compile(r"^#[0-9a-fA-F]{6}$")
    bad = [k for k in ov if k not in ("accent_type", "accent_wall", "accent_colour", "ceiling", "floor", "floor_tone", "wall_colour", "curtain_colour",
                                      "rug", "rug_colour", "art", "plants")]
    if bad: raise ValueError(f"Unknown change(s): {', '.join(bad)}")
    for k, allowed in EDITABLE.items():
        if k in ov and ov[k] not in allowed: raise ValueError(f"{k} must be one of {', '.join(allowed)}")
    for k in ("accent_colour", "floor_tone", "wall_colour", "curtain_colour", "rug_colour"):
        if k in ov and not hexc.match(str(ov[k])): raise ValueError(f"{k} must be a colour like #a1b2c3")
    for k in ("rug", "art", "plants"):
        if k in ov and not isinstance(ov[k], bool): raise ValueError(f"{k} must be true or false")
    f = {**f}
    if "wall_colour" in ov: f["walls"] = {"colour": ov["wall_colour"]}
    if ov.get("accent_type") == "NONE": f["accent"] = None
    elif any(k in ov for k in ("accent_type", "accent_wall", "accent_colour")):
        a = dict(f.get("accent") or {"wall": "N", "from": 0, "to": L, "z0": 0, "height": H, "type": "PAINT", "colour": f["palette"]["accent"]})
        if "accent_wall" in ov and ov["accent_wall"] != a["wall"]:
            a.update(wall=ov["accent_wall"], **{"from": 0, "to": _wall_len(ov["accent_wall"], L, W)})
        if "accent_type" in ov: a["type"] = ov["accent_type"]
        if "accent_colour" in ov: a["colour"] = ov["accent_colour"]
        a["area_sqm"] = round((a["to"] - a["from"]) * a["height"] / 1e6, 2); f["accent"] = a
    if "ceiling" in ov:
        c = {"type": ov["ceiling"], "label": CEILINGS[ov["ceiling"]]}
        if ov["ceiling"] in ("COVE", "ISLAND"):
            b = 600 if ov["ceiling"] == "COVE" else 900; c.update(drop=250 if ov["ceiling"] == "COVE" else 300, border=b, cove_rm=round(2 * ((L - 2 * b) + (W - 2 * b)) / 1000, 2),
                                                                 gypsum_sqm=round(((L * W - (L - 2 * b) * (W - 2 * b)) if ov["ceiling"] == "COVE" else (L - 2 * b) * (W - 2 * b)) / 1e6, 2))
        f["ceiling"] = c
    if "floor" in ov or "floor_tone" in ov:
        fl = dict(f["floor"]); fl["kind"] = ov.get("floor", fl["kind"]); fl["tone"] = ov.get("floor_tone", fl["tone"]); fl["label"] = FLOORS[fl["kind"]]; f["floor"] = fl
    if "curtain_colour" in ov: f["curtains"] = [{**c, "colour": ov["curtain_colour"]} for c in f.get("curtains", [])]
    if ov.get("rug") is False: f["rug"] = None
    if "rug_colour" in ov and f.get("rug"): f["rug"] = {**f["rug"], "colour": ov["rug_colour"]}
    if ov.get("art") is False: f["art"] = []
    if ov.get("plants") is False: f["plants"] = []
    f["overrides"] = {**(f.get("overrides") or {}), **ov}
    return f


def quantities(f: dict | None) -> dict:
    """Take-off quantities from a room's concept (keys = take-off measures; mapped to catalogue items in Estimation → Take-off)."""
    if not f: return {}
    q: dict = {}
    a = f.get("accent")
    if a and a.get("area_sqm"): q[f"accent_{a['type'].lower()}_sqm"] = a["area_sqm"]
    c = f.get("ceiling") or {}
    if c.get("cove_rm"): q["concept_cove_led_rm"] = c["cove_rm"]
    if c.get("type") == "RAFTER": q["rafter_ceiling_sqm"] = (f.get("floor") or {}).get("area_sqm", 0)
    cur = [x for x in f.get("curtains", []) if x["kind"] == "CURTAIN"]; bl = [x for x in f.get("curtains", []) if x["kind"] == "BLIND"]
    if cur: q["curtain_rm"] = round(sum(x["rm"] for x in cur), 2)
    if bl: q["blind_no"] = len(bl)
    if f.get("rug"): q["rug_no"] = 1
    if f.get("art"): q["wall_art_no"] = len(f["art"])
    if f.get("plants"): q["decor_plant_no"] = len(f["plants"])
    pend = sum(x.get("count", 1) for x in f.get("lights", []) if x["kind"] == "PENDANT"); ch = sum(1 for x in f.get("lights", []) if x["kind"] == "CHANDELIER")
    if pend: q["pendant_light_no"] = pend
    if ch: q["chandelier_no"] = ch
    fl = f.get("floor") or {}
    if fl.get("kind") and fl.get("area_sqm"): q[f"floor_{fl['kind'].lower()}_sqm"] = fl["area_sqm"]
    return q
