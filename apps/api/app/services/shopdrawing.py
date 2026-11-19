"""Shop drawings for in-house units (wardrobes, kitchen base/wall/tall/sink/hob units, TV units, vanities, utility cabinets …) — PDF (A3)
and DXF, from the SAME rules as the cutting list (services/cutting.py: 18 mm carcass, 8 mm back, a partition every ~900 mm, shelves every
~450 mm, shutters ~450 mm), so what the workshop draws and what it orders always agree.

Sheet contents: front elevation with shutters (door splits, handles, plinth for floor units, overall + door dimensions), internal elevation
(shutters off: partitions, shelves, clear bay widths and shelf pitch), plan section and side section (depth, back panel, shelf set-back),
cutting list + boards + edge band, title block. Kitchen rules on top: floor units get a 100 mm plinth; sink units have no shelf and a
'sink cut-out' note; hob units are drawn as a 3-drawer stack; wall units get handles at the bottom; tall units get a mid fixed shelf.
It is a production drawing from the outer size — the workshop still checks site dimensions (stated on the sheet)."""
import io
import math
from datetime import date

import ezdxf
from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas

from app.services import cutting, pdf_fonts

T, BACK_T, SET_BACK, PLINTH, GAP = cutting.T, cutting.BACK_T, 20, cutting.PLINTH, 3


def layout(category: str | None, L: float, D: float, H: float) -> dict:
    """Geometry of one unit, in mm from its bottom-left front corner — the SAME counts as cutting.panels(L, D, H, category)."""
    k = cutting.unit_kind(category, H)
    kind = k or ("tall" if H >= 1800 else "unit")
    plinth = cutting.PLINTH if k in ("base", "sink", "hob") else 0
    CH = H - plinth
    bays = max(1, math.ceil(L / 900)); parts = bays - 1
    bay_w = (L - 2 * T - parts * T) / bays
    shelves = 0 if k in ("sink", "hob") else 1 if CH < 900 else max(1, round(CH / 450) - 1)
    doors = max(1, round(L / 450))
    xs, x = [], T                                   # partition x positions (left face)
    for i in range(parts): x += bay_w; xs.append(x); x += T
    inner_h = CH - 2 * T
    shelf_y = [plinth + T + inner_h * (n + 1) / (shelves + 1) for n in range(shelves)]
    drawers = cutting.DRAWERS if k == "hob" else 0
    notes = []
    if k == "sink": notes.append("Sink unit: no shelf; cut-out in the counter to the sink template; keep the back open for plumbing.")
    if k == "hob": notes.append("Hob unit: 3-drawer stack (heavy-duty runners); hob cut-out in the counter; 16A point behind.")
    if k == "wall": notes.append("Wall unit: hang on a wall rail; handles / profile at the bottom edge.")
    if kind == "tall": notes.append("Tall unit: fix to the wall at the top (anti-tip).")
    if plinth: notes.append(f"Floor unit on a {cutting.PLINTH} mm plinth / legs; counter top by others (40 mm, 20 mm front overhang).")
    return {"L": L, "D": D, "H": H, "plinth": plinth, "bays": bays, "partitions": xs, "bay_w": bay_w, "shelves_per_bay": len(shelf_y), "shelf_y": shelf_y,
            "doors": 0 if drawers else doors, "door_w": L / doors - GAP, "drawers": drawers, "kind": kind, "notes": notes}


# ── PDF ──────────────────────────────────────────────────────────────────────
def _dim(c, x1, y1, x2, y2, text, off=6 * mm, vertical=False, size=7):
    c.saveState(); c.setStrokeColor(colors.HexColor("#b45309")); c.setFillColor(colors.HexColor("#b45309")); c.setLineWidth(0.4)
    if vertical:
        xo = x1 - off; c.line(x1, y1, xo - 1.5 * mm, y1); c.line(x2, y2, xo - 1.5 * mm, y2); c.line(xo, y1, xo, y2)
        for y in (y1, y2): c.line(xo - 1 * mm, y - 1 * mm, xo + 1 * mm, y + 1 * mm)
        c.setFont(pdf_fonts.get()["regular"], size); c.translate(xo - 1.5 * mm, (y1 + y2) / 2); c.rotate(90); c.drawCentredString(0, 0, text)
    else:
        yo = y1 - off; c.line(x1, y1, x1, yo - 1.5 * mm); c.line(x2, y2, x2, yo - 1.5 * mm); c.line(x1, yo, x2, yo)
        for x in (x1, x2): c.line(x - 1 * mm, yo - 1 * mm, x + 1 * mm, yo + 1 * mm)
        c.setFont(pdf_fonts.get()["regular"], size); c.drawCentredString((x1 + x2) / 2, yo - 3 * mm, text)
    c.restoreState()


def _f(v) -> str: return f"{v:.0f}"


def pdf(*, title: str, wo_number: str, project: str, unit_no: int, sku: str | None, material: str | None, category: str | None, cut: dict, company: str) -> bytes:
    L, D, H = cut["size"]["length"], cut["size"]["depth"], cut["size"]["height"]
    g = layout(category, L, D, H); F = pdf_fonts.get(); reg, bold = F["regular"], F["bold"]
    buf = io.BytesIO(); W_, H_ = landscape(A3); c = rl_canvas.Canvas(buf, pagesize=(W_, H_)); c.setTitle(f"Shop drawing {wo_number}")
    ink, grey = colors.HexColor("#1c1917"), colors.HexColor("#78716c")
    margin = 12 * mm; c.setStrokeColor(ink); c.setLineWidth(1); c.rect(margin, margin, W_ - 2 * margin, H_ - 2 * margin)
    # drawing zones: front (top-left), internal (top-right), plan (bottom-left), side (bottom-middle), cut list (right column)
    col_w = 128 * mm                                                   # right column: cutting list, notes, title block
    avail_w = W_ - 2 * margin - col_w - 10 * mm
    s = min((avail_w - 25 * mm - 45 * mm) / (2 * L), 105 * mm / H, 60 * mm / max(D, 1))   # one scale for the elevations and the plan
    scale_txt = f"1:{max(1, round(1 / (s / mm)))}"
    def T_(t, x, y, size=8, font=None, col=ink, centre=False):
        c.setFont(font or reg, size); c.setFillColor(col); txt = pdf_fonts.clean(t)
        (c.drawCentredString if centre else c.drawString)(x, y, txt, shaping=F["shaping"])
    def box(x, y, w, h, fill=None, lw=0.8, dash=None):
        c.saveState(); c.setLineWidth(lw); c.setStrokeColor(ink)
        if dash: c.setDash(*dash)
        if fill: c.setFillColor(fill); c.rect(x, y, w, h, stroke=1, fill=1)
        else: c.rect(x, y, w, h, stroke=1, fill=0)
        c.restoreState()

    # 1. front elevation with shutters
    ox, oy = margin + 25 * mm, H_ - margin - 22 * mm - H * s
    T_("FRONT ELEVATION (shutters)", ox, H_ - margin - 10 * mm, 10, bold)
    if g["plinth"]: box(ox + 20 * s, oy, (L - 40) * s, g["plinth"] * s, fill=colors.HexColor("#e7e5e4"))
    box(ox, oy + g["plinth"] * s, L * s, (H - g["plinth"]) * s, lw=1.2)
    if g["drawers"]:
        dh = (H - g["plinth"]) / g["drawers"]
        for k in range(g["drawers"]):
            y = oy + (g["plinth"] + k * dh) * s; box(ox + 1.5 * s, y + 1.5 * s, (L - 3) * s, (dh - 3) * s, fill=colors.HexColor("#fafaf9"))
            c.setLineWidth(1.5); c.line(ox + (L / 2 - 80) * s, y + (dh - 60) * s, ox + (L / 2 + 80) * s, y + (dh - 60) * s)
        _dim(c, ox + L * s + 14 * mm, oy + g["plinth"] * s, ox + L * s + 14 * mm, oy + (g["plinth"] + dh) * s, f"drawer {_f(dh - GAP)}", off=-4 * mm, vertical=True)
    else:
        for k in range(g["doors"]):
            x = ox + k * (L / g["doors"]) * s
            box(x + GAP / 2 * s, oy + (g["plinth"] + GAP / 2) * s, g["door_w"] * s, (H - g["plinth"] - GAP) * s, fill=colors.HexColor("#fafaf9"))
            hx = x + ((L / g["doors"]) - 50 if k % 2 == 0 else 50) * s          # handles at the meeting edges
            hy0 = oy + (g["plinth"] + (60 if g["kind"] == "wall" else (H - g["plinth"]) / 2 - 80 if g["kind"] in ("tall", "unit") else H - 160)) * s
            c.setLineWidth(1.8); c.line(hx, hy0, hx, hy0 + 160 * s if g["kind"] != "wall" else hy0 + 100 * s)
        if g["doors"] > 1: _dim(c, ox, oy, ox + (L / g["doors"]) * s, oy, f"shutter {_f(g['door_w'])}", off=4 * mm)
    _dim(c, ox, oy, ox + L * s, oy, f"{_f(L)} overall width", off=12 * mm)
    _dim(c, ox, oy, ox, oy + H * s, f"{_f(H)} overall height", off=8 * mm, vertical=True)
    if g["plinth"]: _dim(c, ox + L * s + 6 * mm, oy, ox + L * s + 6 * mm, oy + g["plinth"] * s, f"plinth {PLINTH}", off=-2 * mm, vertical=True, size=6)

    # 2. internal elevation (shutters off)
    ix, iy = ox + L * s + 40 * mm, oy
    T_("INTERNAL ELEVATION (shutters removed)", ix, H_ - margin - 10 * mm, 10, bold)
    if g["plinth"]: box(ix + 20 * s, iy, (L - 40) * s, g["plinth"] * s, fill=colors.HexColor("#e7e5e4"))
    y0 = iy + g["plinth"] * s
    box(ix, y0, T * s, (H - g["plinth"]) * s, fill=colors.HexColor("#d6d3d1")); box(ix + (L - T) * s, y0, T * s, (H - g["plinth"]) * s, fill=colors.HexColor("#d6d3d1"))
    box(ix, y0, L * s, T * s, fill=colors.HexColor("#d6d3d1")); box(ix, y0 + (H - g["plinth"] - T) * s, L * s, T * s, fill=colors.HexColor("#d6d3d1"))
    box(ix, y0, L * s, (H - g["plinth"]) * s, lw=1.2)
    for px in g["partitions"]: box(ix + px * s, y0 + T * s, T * s, (H - g["plinth"] - 2 * T) * s, fill=colors.HexColor("#d6d3d1"))
    edges = [T] + [px + T for px in g["partitions"]]
    for bx in edges:
        for sy in g["shelf_y"]: box(ix + bx * s, iy + sy * s, g["bay_w"] * s, T * s, fill=colors.HexColor("#e7e5e4"), lw=0.5)
    if g["drawers"]:
        dh = (H - g["plinth"]) / g["drawers"]
        for k in range(1, g["drawers"]): c.setDash(3, 2); c.line(ix + T * s, y0 + k * dh * s, ix + (L - T) * s, y0 + k * dh * s); c.setDash()
        T_("3 drawer boxes on full-extension runners", ix + 4 * mm, y0 + (H - g["plinth"]) * s / 2, 7, col=grey)
    _dim(c, ix + T * s, iy, ix + (T + g["bay_w"]) * s, iy, f"clear bay {_f(g['bay_w'])}", off=6 * mm)
    if g["shelf_y"]:
        pitch = (g["shelf_y"][1] - g["shelf_y"][0]) if len(g["shelf_y"]) > 1 else g["shelf_y"][0] - g["plinth"] - T
        _dim(c, ix, iy + g["shelf_y"][0] * s, ix, iy + (g["shelf_y"][0] + pitch) * s if len(g["shelf_y"]) > 1 else iy + (g["plinth"] + T) * s,
             f"shelf pitch {_f(pitch)}", off=6 * mm, vertical=True, size=6)
    T_(f"{g['bays']} bay(s) · {len(g['partitions'])} partition(s) · {g['shelves_per_bay']} shelf/shelves per bay · {T} mm carcass, {BACK_T} mm back", ix, iy - 20 * mm, 7, col=grey)

    # 3. plan section + 4. side section (same scale)
    py = margin + 30 * mm
    T_("PLAN SECTION", ox, py + D * s + 6 * mm, 10, bold)
    box(ox, py, L * s, D * s, lw=1.2)
    box(ox, py + (D - BACK_T) * s, L * s, BACK_T * s, fill=colors.HexColor("#a8a29e"), lw=0.4)
    box(ox, py, T * s, (D - BACK_T) * s, fill=colors.HexColor("#d6d3d1"), lw=0.4); box(ox + (L - T) * s, py, T * s, (D - BACK_T) * s, fill=colors.HexColor("#d6d3d1"), lw=0.4)
    for px in g["partitions"]: box(ox + px * s, py, T * s, (D - BACK_T) * s, fill=colors.HexColor("#d6d3d1"), lw=0.4)
    if g["doors"]:
        for k in range(g["doors"]): box(ox + (k * L / g["doors"] + GAP / 2) * s, py - T * s, g["door_w"] * s, T * s, fill=colors.HexColor("#fafaf9"), lw=0.4)
    _dim(c, ox, py, ox, py + D * s, f"{_f(D)} depth", off=8 * mm, vertical=True)
    sx = ix
    hs = min(s, 70 * mm / H)
    T_("SIDE SECTION", sx, py + H * hs + 6 * mm, 10, bold)
    box(sx, py, D * hs, H * hs, lw=1.2)
    box(sx + (D - BACK_T) * hs, py + g["plinth"] * hs, BACK_T * hs, (H - g["plinth"]) * hs, fill=colors.HexColor("#a8a29e"), lw=0.3)
    for sy in g["shelf_y"]: box(sx + SET_BACK * hs, py + sy * hs, (D - BACK_T - SET_BACK) * hs, T * hs, fill=colors.HexColor("#e7e5e4"), lw=0.3)
    T_(f"shelves set back {SET_BACK} mm", sx + D * hs + 3 * mm, py + 4 * mm, 6, col=grey)

    # 5. cutting list (right column)
    cx = W_ - margin - col_w + 2 * mm; cy = H_ - margin - 12 * mm
    c.setLineWidth(0.6); c.setStrokeColor(ink); c.line(cx - 4 * mm, margin, cx - 4 * mm, H_ - margin)
    T_("CUTTING LIST", cx, cy, 10, bold); cy -= 6 * mm
    for hx, txt in ((0, "Part"), (52, "L × W (mm)"), (88, "Qty"), (100, "Thk"), (110, "Edge m")): T_(txt, cx + hx * mm, cy, 7, bold)
    cy -= 2 * mm; c.setLineWidth(0.4); c.line(cx, cy, cx + 118 * mm, cy); cy -= 4.5 * mm
    for p in cut["panels"]:
        for hx, txt in ((0, p["name"]), (52, f"{p['length']} × {p['width']}"), (88, str(p["qty"])), (100, str(p["thickness"])), (110, f"{p['edge_m']:g}")):
            T_(txt, cx + hx * mm, cy, 7)
        cy -= 4.5 * mm
    cy -= 2 * mm
    for th, sh in cut["sheets"].items(): T_(f"{sh['board']}: {sh['sheets']} sheet(s) 2440×1220, {sh['utilisation_pct']}% used", cx, cy, 7); cy -= 4.5 * mm
    T_(f"Edge band: {cut['edge_band_m']} m", cx, cy, 7); cy -= 8 * mm
    T_("NOTES", cx, cy, 9, bold); cy -= 5 * mm
    for n in g["notes"] + ["All dimensions in mm. Check site sizes, levels and service points before cutting.", "Drawn from the outer size by the cutting-list rules."]:
        words, line = n.split(), ""
        for w in words:
            if len(line) + len(w) > 70: T_(line, cx, cy, 7); cy -= 4 * mm; line = ""
            line += w + " "
        T_(line, cx, cy, 7); cy -= 5 * mm

    # 6. title block
    tb_y = margin + 2 * mm
    c.setLineWidth(0.8); c.line(cx - 4 * mm, margin + 34 * mm, W_ - margin, margin + 34 * mm)
    T_(company, cx, tb_y + 26 * mm, 10, bold)
    T_(f"{title}", cx, tb_y + 20 * mm, 9, bold)
    T_(f"Work order {wo_number} · unit {unit_no} · {project}", cx, tb_y + 15 * mm, 7)
    T_(f"SKU {sku or '-'} · {material or 'material as specified'} · size {_f(L)} × {_f(D)} × {_f(H)} mm", cx, tb_y + 10.5 * mm, 7)
    T_(f"Scale {scale_txt} on A3 · {date.today().isoformat()} · SHOP DRAWING", cx, tb_y + 6 * mm, 7, col=grey)
    c.showPage(); c.save(); return buf.getvalue()


# ── DXF ──────────────────────────────────────────────────────────────────────
def dxf(*, title: str, category: str | None, cut: dict) -> bytes:
    L, D, H = cut["size"]["length"], cut["size"]["depth"], cut["size"]["height"]
    g = layout(category, L, D, H)
    doc = ezdxf.new("R2010", setup=True); doc.units = ezdxf.units.MM; msp = doc.modelspace()
    for n, col in (("CARCASS", 7), ("SHUTTERS", 3), ("SHELVES", 8), ("DIMENSIONS", 1), ("TEXT", 2)): doc.layers.add(n, color=col)
    def rect(x, y, w, h, layer): msp.add_lwpolyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], close=True, dxfattribs={"layer": layer})
    def dim(p1, p2, base, angle=0): msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle="EZDXF", dxfattribs={"layer": "DIMENSIONS"}).render()
    # front with shutters at (0,0); internal at (L+600, 0); plan at (0, -D-600); side at (L+600, -H-600)
    rect(0, g["plinth"], L, H - g["plinth"], "CARCASS")
    if g["drawers"]:
        dh = (H - g["plinth"]) / g["drawers"]
        for k in range(g["drawers"]): rect(1.5, g["plinth"] + k * dh + 1.5, L - 3, dh - 3, "SHUTTERS")
    else:
        for k in range(g["doors"]): rect(k * L / g["doors"] + GAP / 2, g["plinth"] + GAP / 2, g["door_w"], H - g["plinth"] - GAP, "SHUTTERS")
    if g["plinth"]: rect(20, 0, L - 40, g["plinth"], "CARCASS")
    dim((0, 0), (L, 0), (0, -250)); dim((0, 0), (0, H), (-250, 0), 90)
    ox = L + 600
    rect(ox, g["plinth"], L, H - g["plinth"], "CARCASS")
    for px in g["partitions"]: rect(ox + px, g["plinth"] + T, T, H - g["plinth"] - 2 * T, "CARCASS")
    for bx in [T] + [px + T for px in g["partitions"]]:
        for sy in g["shelf_y"]: rect(ox + bx, sy, g["bay_w"], T, "SHELVES")
    dim((ox + T, 0), (ox + T + g["bay_w"], 0), (0, -250))
    py = -D - 600
    rect(0, py, L, D, "CARCASS"); rect(0, py + D - BACK_T, L, BACK_T, "CARCASS")
    for px in g["partitions"]: rect(px, py, T, D - BACK_T, "CARCASS")
    dim((0, py), (0, py + D), (-250, 0), 90)
    sx, sy0 = L + 600, -H - 600
    rect(sx, sy0, D, H, "CARCASS"); rect(sx + D - BACK_T, sy0 + g["plinth"], BACK_T, H - g["plinth"], "CARCASS")
    for sy in g["shelf_y"]: rect(sx + SET_BACK, sy0 + sy, D - BACK_T - SET_BACK, T, "SHELVES")
    msp.add_text(pdf_fonts.clean(title).encode("ascii", "replace").decode(), dxfattribs={"layer": "TEXT", "height": 60, "insert": (0, H + 200)})
    out = io.StringIO(); doc.write(out); return out.getvalue().encode("utf-8")
