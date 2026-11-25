"""Working drawing set — the sheets a site team builds from, in the format Indian interior studios issue (A3, feet-inches, title block):

  LIGHT DETAIL      whole-home ceiling / electrical plan: 18 W downlights, 7 W spots, profile (cove) lights, fans, AC, wall lights, bell,
                    Wi-Fi, entry arrow, legend
  <ROOM>            room plan (walls, door swings, windows, furniture labelled, A/B/C/D view markers, dimensions) + elevation of the
                    feature wall with material call-outs + bed details (side / front / plan) and bedside table details when there is a bed
  <ROOM> WARDROBE   wardrobe elevation (shutters, knobs, loft panel to the ceiling) + internal detail (shelf bays, hanging rod, drawers)
  KITCHEN           elevation of every counter run (base units labelled: shutter / plain drawers / cutlery-thali-C&S / pull-out, counter,
                    wall units, chimney, windows) + counter plan with sink and hob
  3D VIEWS          the renders saved from the 3D editor

Everything is drawn from saved data (latest design + concept, room sizes, openings, the same rules as the cutting lists) — nothing is
invented on the sheet. Dimensions print in feet-inches (default, site practice) or millimetres (company setting drawing_units)."""
import io
import math
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from app.models import models as m
from app.services import concept, cutting, documents, homeplan, mep, pdf_fonts

PW, PH = landscape(A3)
INK, GREY, RED, BLUE, MAG, CYAN = (colors.HexColor(x) for x in ("#1c1917", "#6b6b6b", "#d11a1a", "#1d4ed8", "#c026d3", "#22d3ee"))
FILL = colors.HexColor("#d9d0c3")
CALLOUT = {"FLUTED_WOOD": "fluted mdf finish with satin PU", "WALLPAPER": "designer wallpaper", "STONE": "stone cladding",
           "PANELLING": "mdf panelling with tee patti (brass strip)", "PAINT": "accent paint finish", "TILE": "feature tiles",
           "JAALI": "backlit CNC jaali panel", "BRICK": "exposed brick cladding"}
WALL_VIEW = {"N": "AB", "E": "BC", "S": "CD", "W": "DA"}


def ftin(v: float) -> str:
    inch = v / 25.4; ft = int(inch // 12); i = round(inch - ft * 12)
    if i == 12: ft, i = ft + 1, 0
    return f"{ft}'-{i}\"" if ft else f"{i}\""


class Sheet:
    def __init__(self, info: dict):
        self.info = info; self.F = pdf_fonts.get(); self.buf = io.BytesIO(); self.c = rl_canvas.Canvas(self.buf, pagesize=(PW, PH))
        self.c.setTitle(f"Working drawings — {info['project']}"); self.n = 0; self.units = info.get("units", "ftin")

    def d(self, v): return ftin(v) if self.units == "ftin" else f"{v:.0f}"

    def text(self, t, x, y, size=8, col=INK, bold=False, centre=False, right=False, angle=0, font=None):
        c = self.c; c.saveState(); c.setFillColor(col); c.setFont(font or (self.F["bold"] if bold else self.F["regular"]), size)
        s = pdf_fonts.clean(t); c.translate(x, y); c.rotate(angle)
        (c.drawCentredString if centre else c.drawRightString if right else c.drawString)(0, 0, s, shaping=self.F["shaping"]); c.restoreState()

    def page(self, title: str):
        if self.n: self.c.showPage()
        self.n += 1; self._frame(title)

    def _frame(self, title):
        c = self.c; c.setStrokeColor(INK); c.setLineWidth(0.8); c.rect(12 * mm, 10 * mm, PW - 24 * mm, PH - 20 * mm)
        y0, h = 10 * mm, 22 * mm
        cols = [12 * mm, 70 * mm, 115 * mm, 190 * mm, 255 * mm, 290 * mm, 370 * mm, PW - 12 * mm]
        c.setStrokeColor(colors.HexColor("#0e7490")); c.setLineWidth(1.4); c.rect(12 * mm, y0, PW - 24 * mm, h)
        c.setLineWidth(0.6)
        for x in cols[1:-1]: c.line(x, y0, x, y0 + h)
        c.line(cols[0], y0 + h / 2, cols[1], y0 + h / 2); c.line(cols[1], y0 + h / 2, cols[2], y0 + h / 2)
        for k in (1, 2): c.line(cols[3], y0 + h * k / 3, cols[4], y0 + h * k / 3)
        i = self.info
        self.text("INTERIOR FOR RESIDENTIAL", cols[0] + 2 * mm, y0 + h * 0.68, 7.5); self.text(i["client"].upper(), cols[0] + 2 * mm, y0 + h * 0.18, 7.5)
        self.text(f"NO :- {i['project_number']}", cols[1] + 2 * mm, y0 + h * 0.68, 7.5); self.text(f"REVISION :- {i.get('revision', '')}", cols[1] + 2 * mm, y0 + h * 0.18, 7.5)
        words = title.upper().split(); mid = (len(words) + 1) // 2 if len(" ".join(words)) > 16 else len(words)
        self.text(" ".join(words[:mid]), cols[2] + 6 * mm, y0 + (h * 0.55 if mid < len(words) else h * 0.38), 15)
        if mid < len(words): self.text(" ".join(words[mid:]), cols[2] + 6 * mm, y0 + h * 0.15, 15)
        self.text(f"DATE :-  {date.today():%d/%m/%Y}", cols[3] + 2 * mm, y0 + h * 0.74, 7); self.text(f"DESIGN BY :-  {i['designer']}", cols[3] + 2 * mm, y0 + h * 0.41, 7)
        self.text(f"Contact no :-  {i['phone']}", cols[3] + 2 * mm, y0 + h * 0.08, 7)
        self.text("Orientation :-", cols[4] + 2 * mm, y0 + h * 0.78, 7); self.north(cols[4] + 17 * mm, y0 + 8 * mm, 6 * mm)
        self.text("NOTES", cols[5] + 2 * mm, y0 + h * 0.8, 8, col=RED)
        for k, n in enumerate(["1. ALL DIMENSIONS IN FEET (') - INCHES (\")" if self.units == "ftin" else "1. ALL DIMENSIONS IN MILLIMETRES", "2. DO NOT SCALE THE DRAWING.",
                               "3. REFER STRUCTURAL DRAWING ALONGSIDE.", "4. CONTACT DESIGNER IN CASE OF ANY DISCREPANCY."]):
            self.text(n, cols[5] + 2 * mm, y0 + h * 0.6 - k * 3.6 * mm, 5.8)
        self.text(i["company"], cols[6] + 2 * mm, y0 + h * 0.55, 8, bold=True); self.text(f"Sheet {self.n}", cols[6] + 2 * mm, y0 + h * 0.2, 7, col=GREY)

    def north(self, x, y, r):
        c = self.c; c.setFillColor(INK); p = c.beginPath(); p.moveTo(x, y + r); p.lineTo(x - r * 0.35, y - r * 0.6); p.lineTo(x, y - r * 0.2); p.close(); c.drawPath(p, fill=1, stroke=0)
        self.text("N", x, y + r + 1 * mm, 7, bold=True, centre=True)

    def dim(self, x1, y1, x2, y2, label, off=5 * mm, size=6.5, col=GREY):
        """Dimension line with slash ticks (site style), text above / beside."""
        c = self.c; c.saveState(); c.setStrokeColor(col); c.setLineWidth(0.4)
        if abs(y2 - y1) < 0.01:
            y = y1 + off; c.line(x1, y1, x1, y + 1.2 * mm); c.line(x2, y2, x2, y + 1.2 * mm); c.line(x1, y, x2, y)
            for x in (x1, x2): c.setLineWidth(0.9); c.line(x - 1.1 * mm, y - 1.1 * mm, x + 1.1 * mm, y + 1.1 * mm); c.setLineWidth(0.4)
            c.restoreState(); self.text(label, (x1 + x2) / 2, y + 0.8 * mm, size, col=col, centre=True)
        else:
            x = x1 + off; c.line(x1, y1, x + 1.2 * mm, y1); c.line(x2, y2, x + 1.2 * mm, y2); c.line(x, y1, x, y2)
            for y in (y1, y2): c.setLineWidth(0.9); c.line(x - 1.1 * mm, y - 1.1 * mm, x + 1.1 * mm, y + 1.1 * mm); c.setLineWidth(0.4)
            c.restoreState(); self.text(label, x - 1 * mm, (y1 + y2) / 2, size, col=col, centre=True, angle=90)

    def leader(self, x, y, tx, ty, label, col=BLUE, size=6.5):
        c = self.c; c.saveState(); c.setStrokeColor(col); c.setLineWidth(0.5); c.line(tx, ty, x, y)
        a = math.atan2(y - ty, x - tx); p = c.beginPath(); p.moveTo(x, y)
        p.lineTo(x - 2 * mm * math.cos(a - 0.35), y - 2 * mm * math.sin(a - 0.35)); p.lineTo(x - 2 * mm * math.cos(a + 0.35), y - 2 * mm * math.sin(a + 0.35)); p.close()
        c.setFillColor(col); c.drawPath(p, fill=1, stroke=0); c.restoreState()
        lines = self.wrap(label, 22)
        for k, ln in enumerate(lines): self.text(ln, tx, ty + (len(lines) - 1 - k) * 2.6 * mm + 0.6 * mm, size, col=col, right=tx < x)

    @staticmethod
    def wrap(t, n):
        out, line = [], ""
        for w in t.split():
            if len(line) + len(w) > n and line: out.append(line.strip()); line = ""
            line += w + " "
        return out + ([line.strip()] if line.strip() else [])

    def bytes(self):
        self.c.showPage(); self.c.save(); return self.buf.getvalue()


# ── room plan ────────────────────────────────────────────────────────────────
def _poly(c, pts, fill=None, stroke=True):
    p = c.beginPath(); p.moveTo(*pts[0])
    for q in pts[1:]: p.lineTo(*q)
    p.close(); c.drawPath(p, fill=1 if fill is not None else 0, stroke=1 if stroke else 0)


def _plan(S: Sheet, L, W, objs, ops, x0, y0, bw, bh, names=True, markers=True, f=None, dims=True, shell=None):
    from shapely.geometry import Polygon
    from app.services import geometry as geo, shape as shp
    c = S.c; s = min(bw / (L + 600), bh / (W + 600)); ox, oy = x0 + (bw - L * s) / 2, y0 + (bh - W * s) / 2; t = 230 * s / 2
    P = lambda x, y: (ox + x * s, oy + y * s)
    outline = [tuple(q) for q in (shell or {}).get("outline") or [(0, 0), (L, 0), (L, W), (0, W)]]
    room = Polygon(outline); band = room.buffer(115, join_style=2).difference(room)            # 230 mm walls drawn outside the clear room
    c.setFillColor(colors.HexColor("#9c9c9c")); c.setStrokeColor(INK); c.setLineWidth(0.8)
    for g in getattr(band, "geoms", [band]):
        _poly(c, [P(*q) for q in list(g.exterior.coords)[:-1]], fill=True)
        for hole in g.interiors: c.setFillColor(colors.white); _poly(c, [P(*q) for q in list(hole.coords)[:-1]], fill=True); c.setFillColor(colors.HexColor("#9c9c9c"))
    t = 115 * s
    R = geo.Room(L, W)
    for o in ops:
        (ax, ay, bx, by), (nx, ny) = geo.opening_span(R, o); w = o["width"] * s
        gap = [P(ax, ay), P(bx, by), P(bx - nx * 115, by - ny * 115), P(ax - nx * 115, ay - ny * 115)]
        c.setFillColor(colors.white); c.setStrokeColor(colors.white); _poly(c, gap, fill=True)
        c.setStrokeColor(INK); c.setLineWidth(0.5)
        if o["kind"] == "WINDOW":
            c.setStrokeColor(BLUE)
            for k in (0.3, 0.7): c.line(*P(ax - nx * 115 * k, ay - ny * 115 * k), *P(bx - nx * 115 * k, by - ny * 115 * k))
        elif o.get("swing") == "SLIDING":
            c.setLineWidth(0.9); c.line(*P(ax - nx * 40, ay - ny * 40), *P(bx - nx * 40, by - ny * 40))
        else:
            right = o.get("swing") == "INWARD_RIGHT"
            hx, hy, ex, ey = (bx, by, ax, ay) if right else (ax, ay, bx, by)
            dn = -1 if o.get("swing") == "OUTWARD" else 1
            lx, ly = nx * dn, ny * dn                                                          # the leaf, open at 90°
            a_other = math.degrees(math.atan2(ey - hy, ex - hx)); a_leaf = math.degrees(math.atan2(ly, lx))
            st = a_other if (a_leaf - a_other) % 360 == 90 or abs((a_leaf - a_other) % 360 - 90) < 1 else a_leaf
            hxp, hyp = P(hx, hy)
            c.setDash(1.5, 1.5); c.arc(hxp - w, hyp - w, hxp + w, hyp + w, st, 90)
            c.setDash(); c.setLineWidth(0.9); c.line(hxp, hyp, hxp + lx * w, hyp + ly * w)
    for st in (shell or {}).get("structures") or []:                                       # columns hatched, beams dashed
        x, y, l, w2 = st["x"], st["y"], st["length"], st["width"]; corners = [P(x, y), P(x + l, y), P(x + l, y + w2), P(x, y + w2)]
        if st["kind"] in ("COLUMN", "PILLAR"):
            c.setFillColor(colors.HexColor("#5b5b5b")); c.setStrokeColor(INK); c.setLineWidth(0.7); _poly(c, corners, fill=True)
            c.setStrokeColor(colors.white); c.setLineWidth(0.4); c.line(*corners[0], *corners[2]); c.line(*corners[1], *corners[3])
            S.text(st["label"].upper(), corners[3][0], corners[3][1] + 1 * mm, 5, col=GREY)
        else:
            from app.services.cad import beam_underside
            c.setStrokeColor(MAG); c.setLineWidth(0.6); c.setDash(3, 2); _poly(c, corners); c.setDash()
            vert = w2 > l
            S.text(f"{st['label'].upper()} {S.d(min(l, w2))} x {S.d(st.get('depth') or 0)} (U/S {S.d(beam_underside(shell, st))})",
                   ox + (x + l * (0.5 if vert else 0.78)) * s + (w2 * s + 1.5 * mm if vert else 0), oy + (y + w2 * (0.78 if vert else 1)) * s + (0 if vert else 1.2 * mm),
                   5, col=MAG, centre=True, angle=90 if vert else 0)
    if len(outline) > 4 and dims:                                                          # each wall's length, outside the wall
        for (ax, ay), (bx, by) in zip(outline, outline[1:] + outline[:1]):
            ln = math.hypot(bx - ax, by - ay)
            if ln < 200 or (abs(ln - L) < 2 and abs(ay - by) < 1) or (abs(ln - W) < 2 and abs(ax - bx) < 1): continue   # full sides: overall dims
            ux, uy = (bx - ax) / ln, (by - ay) / ln; mx, my = (ax + bx) / 2 + uy * 520, (ay + by) / 2 - ux * 520
            ang = math.degrees(math.atan2(uy, ux))
            if ang > 90 or ang <= -90: ang += 180
            S.text(S.d(ln), *P(mx, my), 5.5, col=GREY, centre=True, angle=ang)
    a = (f or {}).get("accent")
    if a:
        p0, p1 = a["from"] * s, a["to"] * s; c.setStrokeColor(BLUE); c.setLineWidth(1.6)
        {"S": lambda: c.line(ox + p0, oy + 1.2, ox + p1, oy + 1.2), "N": lambda: c.line(ox + p0, oy + W * s - 1.2, ox + p1, oy + W * s - 1.2),
         "W": lambda: c.line(ox + 1.2, oy + p0, ox + 1.2, oy + p1), "E": lambda: c.line(ox + L * s - 1.2, oy + p0, ox + L * s - 1.2, oy + p1)}[a["wall"]]()
    for o in objs:
        up = (o.get("z") or 0) >= 1200; c.setStrokeColor(INK); c.setLineWidth(0.6); c.setFillColor(colors.HexColor("#c9c4bd") if not up else colors.white)
        if up: c.setDash(2, 1.5)
        c.rect(ox + o["x"] * s, oy + o["y"] * s, o["length"] * s, o["width"] * s, stroke=1, fill=0 if up else 1); c.setDash()
        if (o.get("category") or "").lower() == "bed":
            c.setStrokeColor(INK); c.line(ox + (o["x"] + o["length"] / 2) * s, oy + o["y"] * s, ox + (o["x"] + o["length"] / 2) * s, oy + (o["y"] + o["width"]) * s)
        if names:
            lab = (o.get("category") or o["name"]).upper(); big = o["length"] * s > 18 * mm or o["width"] * s > 18 * mm
            vert = o["width"] > o["length"] * 1.6
            S.text(lab, ox + (o["x"] + o["length"] / 2) * s + (1 * mm if vert else 0), oy + (o["y"] + o["width"] / 2) * s - 1 * mm, 6.5 if big else 5, col=RED, centre=True, angle=90 if vert else 0)
    if dims:
        S.dim(ox, oy + W * s + t, ox + L * s, oy + W * s + t, S.d(L), off=5 * mm)
        S.dim(ox - t, oy, ox - t, oy + W * s, S.d(W), off=-6 * mm)
    if markers:
        for lab, (mx, my) in zip("ABCD", ((ox - t - 4 * mm, oy + W * s + t + 2 * mm), (ox + L * s + t + 4 * mm, oy + W * s + t + 2 * mm), (ox + L * s + t + 4 * mm, oy - t - 5 * mm), (ox - t - 4 * mm, oy - t - 5 * mm))):
            S.text(f"({lab})", mx, my, 9, centre=True)
    return s, ox, oy


# ── wall elevation with the feature wall ─────────────────────────────────────
def _elevation(S: Sheet, wall, L, W, H, objs, ops, f, x0, y0, bw, bh, title, e=None):
    """e = mep.elevations() entry for this wall (M41: ceiling line, beams/columns, where the wall is). Positions there run the other way."""
    c = S.c; wl = L if wall in "NS" else W
    top = sorted([(wl - p, h) for p, h in (e or {}).get("ceiling_line") or [(0, H), (wl, H)]])
    Hm = max(h for _, h in top); s = min(bw / wl, bh / Hm); ox, oy = x0, y0
    c.setStrokeColor(INK); c.setLineWidth(1); c.setFillColor(colors.white)
    _poly(c, [(ox, oy), (ox + wl * s, oy)] + [(ox + u * s, oy + h * s) for u, h in reversed(top)])
    if e and e.get("wall_spans") and [tuple(x) for x in e["wall_spans"]] != [(0, round(wl))]:   # an L-shaped room: where this side has no wall
        have = sorted((wl - b, wl - a) for a, b in e["wall_spans"]); cur = 0
        c.setFillColor(colors.HexColor("#f3f3f3")); c.setStrokeColor(GREY); c.setDash(2, 2)
        for a, b in have + [(wl, wl)]:
            if a - cur > 10: c.rect(ox + cur * s, oy, (a - cur) * s, Hm * s, stroke=1, fill=1); S.text("(set back)", ox + (cur + a) / 2 * s, oy + Hm / 2 * s, 6, col=GREY, centre=True)
            cur = max(cur, b)
        c.setDash()
    ceil = (f or {}).get("ceiling") or {}
    if ceil.get("type") in ("COVE", "ISLAND"):
        drop = ceil.get("drop", 250); c.setFillColor(colors.HexColor("#eeeeee")); c.setStrokeColor(INK)
        _poly(c, [(ox + u * s, oy + (h - drop) * s) for u, h in top] + [(ox + u * s, oy + h * s) for u, h in reversed(top)], fill=True)
        h0 = top[0][1]
        S.leader(ox + 6 * mm, oy + (h0 - drop / 2) * s, ox - 14 * mm, oy + (h0 - drop / 2) * s + 6 * mm, "false ceiling with indirect (cove) light")
    for st in (e or {}).get("structures") or []:                                         # beams in section / columns against the wall
        u0 = wl - st["x"] - st["width"]; z = st["z"]
        col = st["kind"] in ("COLUMN", "PILLAR")
        c.setFillColor(colors.HexColor("#8f8f8f") if col else colors.HexColor("#d9c9e6")); c.setStrokeColor(INK); c.setLineWidth(0.7)
        c.rect(ox + u0 * s, oy + z * s, st["width"] * s, (Hm - z) * s if col else (min(h for _, h in top) - z) * s, stroke=1, fill=1)
        if not col: S.text(f"{st['label'].upper()} U/S {S.d(z)}", ox + (u0 + st["width"] / 2) * s, oy + z * s - 3 * mm, 5.5, col=MAG, centre=True)
    flip = wall in ("N", "W")
    # openings on this wall
    for o in ops:
        if o["wall"] != wall or o.get("angled"): continue          # inner / angled walls aren't on this side
        a = (wl - o["offset"] - o["width"]) if flip else o["offset"]
        c.setFillColor(CYAN if o["kind"] == "WINDOW" else colors.HexColor("#8b6f55")); c.setStrokeColor(INK); c.setLineWidth(1.4)
        c.rect(ox + a * s, oy + o["sill"] * s, o["width"] * s, o["height"] * s, stroke=1, fill=1)
        if o["kind"] == "DOOR": c.setFillColor(INK); c.circle(ox + (a + o["width"] - 80) * s, oy + 1000 * s, 0.8 * mm, stroke=0, fill=1)
    a = (f or {}).get("accent")
    if a and a["wall"] == wall:
        p0 = (wl - a["to"]) if flip else a["from"]; p1 = p0 + (a["to"] - a["from"]); z0 = a.get("z0", 0); h = a["height"]
        c.setFillColor(colors.HexColor("#d5d5d5")); c.setStrokeColor(INK); c.setLineWidth(0.5); c.rect(ox + p0 * s, oy + z0 * s, (p1 - p0) * s, h * s, stroke=1, fill=1)
        if a["type"] in ("FLUTED_WOOD", "JAALI", "BRICK"):
            step = 45 if a["type"] == "FLUTED_WOOD" else 120
            for u in range(int(p0 + step), int(p1), step): c.line(ox + u * s, oy + z0 * s, ox + u * s, oy + (z0 + h) * s)
        if a["type"] == "PANELLING":
            n = max(2, round((p1 - p0) / 600)); c.setStrokeColor(colors.HexColor("#c9a227")); c.setLineWidth(1.1)
            for k in range(1, n): u = p0 + (p1 - p0) * k / n; c.line(ox + u * s, oy + z0 * s, ox + u * s, oy + (z0 + h) * s)
            S.leader(ox + (p0 + (p1 - p0) / n) * s, oy + (z0 + h * 0.6) * s, ox - 14 * mm, oy + (z0 + h * 0.6) * s, "tee patti (brass strip)")
        S.leader(ox + (p0 + 60) * s, oy + (z0 + h * 0.35) * s, ox - 14 * mm, oy + (z0 + h * 0.35) * s, CALLOUT[a["type"]])
        S.dim(ox + p0 * s, oy + H * s, ox + p1 * s, oy + H * s, S.d(p1 - p0), off=4 * mm)
    # furniture standing against this wall (front view)
    def against(o):
        return {"S": o["y"] < 200, "N": W - (o["y"] + o["width"]) < 200, "W": o["x"] < 200, "E": L - (o["x"] + o["length"]) < 200}[wall]
    for o in objs:
        if not against(o): continue
        u0 = o["x"] if wall in "NS" else o["y"]; ln = o["length"] if wall in "NS" else o["width"]
        if flip: u0 = wl - u0 - ln
        z = o.get("z") or 0; hh = o.get("height", 0); cat = (o.get("category") or "").lower()
        c.setStrokeColor(INK); c.setLineWidth(0.7)
        if cat == "bed":
            c.setFillColor(colors.HexColor("#c2410c")); c.rect(ox + u0 * s, oy, ln * s, 400 * s, stroke=1, fill=1)
            c.setFillColor(colors.HexColor("#e5e5e5")); c.rect(ox + (u0 + 60) * s, oy + 400 * s, (ln - 120) * s, 150 * s, stroke=1, fill=1)
            c.setFillColor(colors.HexColor("#9ca3af")); c.rect(ox + (u0 + 40) * s, oy + 550 * s, (ln - 80) * s, (max(hh, 1000) - 550) * s, stroke=1, fill=1)
            S.text("Designer Fabric", ox + (u0 + ln / 2) * s, oy + (max(hh, 1000) * 0.8) * s, 7, centre=True)
            S.text("6\" thk. Mattress", ox + (u0 + ln / 2) * s, oy + 470 * s, 5.5, col=BLUE, centre=True)
        else:
            c.setFillColor(colors.HexColor("#e7e2da")); c.rect(ox + u0 * s, oy + z * s, ln * s, hh * s, stroke=1, fill=1)
            S.text((o.get("category") or "").upper(), ox + (u0 + ln / 2) * s, oy + (z + hh / 2) * s, 5.5, col=RED, centre=True)
    # dimension chain under the wall: openings + rest
    S.dim(ox, oy, ox + wl * s, oy, S.d(wl), off=-6 * mm)
    S.dim(ox + wl * s, oy, ox + wl * s, oy + top[-1][1] * s, S.d(top[-1][1]), off=6 * mm)
    if abs(top[0][1] - top[-1][1]) > 5: S.dim(ox, oy, ox, oy + top[0][1] * s, S.d(top[0][1]), off=-6 * mm)     # sloped: both ends
    S.text(title, ox, oy - 12 * mm, 11)


def _bed_detail(S: Sheet, bed: dict, x0, y0, bw):
    L, D, H = bed["length"], bed["width"], max(bed.get("height", 1000), 900)
    s = min(bw / (L + 600), 55 * mm / H); c = S.c
    # side elevation
    sx, sy = x0, y0 + 138 * mm
    c.setStrokeColor(INK); c.setLineWidth(0.7); c.setFillColor(colors.HexColor("#c2410c"))
    c.rect(sx, sy + 120 * s, D * s * 0.85, 280 * s, stroke=1, fill=1); c.rect(sx, sy + 120 * s, 80 * s, (H - 120) * s, stroke=1, fill=1)
    c.setFillColor(colors.HexColor("#e5e5e5")); c.rect(sx + 80 * s, sy + 400 * s, D * s * 0.85 - 80 * s, 150 * s, stroke=1, fill=1)
    for lx in (sx + 60 * s, sx + D * s * 0.85 - 60 * s): c.line(lx, sy, lx, sy + 120 * s)
    c.setStrokeColor(BLUE); c.line(sx - 5 * mm, sy, sx + D * s * 0.85 + 5 * mm, sy)
    S.dim(sx, sy, sx, sy + H * s, S.d(H), off=-6 * mm); S.dim(sx, sy, sx, sy + 400 * s, S.d(400), off=-12 * mm)
    S.text("SIDE ELEVATION", sx + D * s * 0.4, sy - 6 * mm, 8, col=MAG, centre=True)
    # front elevation
    fx, fy = x0, y0 + 72 * mm
    c.setStrokeColor(INK); c.setFillColor(colors.HexColor("#c2410c")); c.rect(fx, fy + 120 * s, L * s, 280 * s, stroke=1, fill=1)
    c.setFillColor(colors.HexColor("#9ca3af")); c.rect(fx + 30 * s, fy + 400 * s, (L - 60) * s, (H - 400) * s, stroke=1, fill=1)
    c.setFillColor(colors.HexColor("#e5e5e5")); c.rect(fx + 60 * s, fy + 400 * s, (L - 120) * s, 150 * s, stroke=1, fill=1)
    S.text("Designer Fabric", fx + L * s / 2, fy + (H * 0.78) * s, 7, centre=True); S.text("6\" thk. Mattress", fx + L * s / 2, fy + 455 * s, 5.5, col=BLUE, centre=True)
    S.leader(fx + 30 * s, fy + (H - 150) * s, fx - 6 * mm, fy + (H - 60) * s, "Fabric wing headboard")
    S.leader(fx + 30 * s, fy + 300 * s, fx - 6 * mm, fy + 300 * s + 4 * mm, "18mm ply + 10mm foam")
    S.leader(fx + 10 * s, fy + 200 * s, fx - 6 * mm, fy + 150 * s, "3 side fabric finish")
    S.dim(fx, fy, fx + L * s, fy, S.d(L), off=-5 * mm); S.dim(fx + L * s, fy, fx + L * s, fy + H * s, S.d(H), off=5 * mm)
    S.text("FRONT ELEVATION", fx + L * s / 2, fy - 11 * mm, 8, col=MAG, centre=True)
    # plan
    px, py = x0, y0
    s2 = min(bw / (L + 600), 42 * mm / D)
    c.setFillColor(colors.HexColor("#d4d4d4")); c.setStrokeColor(INK); c.rect(px, py, L * s2, D * s2, stroke=1, fill=1)
    c.line(px + L * s2 / 2, py, px + L * s2 / 2, py + D * s2); c.setStrokeColor(colors.HexColor("#c2410c")); c.setLineWidth(2); c.line(px, py + D * s2, px + L * s2, py + D * s2)
    S.dim(px, py, px + L * s2, py, S.d(L), off=-4 * mm); S.dim(px + L * s2, py, px + L * s2, py + D * s2, S.d(D), off=4 * mm)
    S.text("PLAN", px + L * s2 / 2, py - 9 * mm, 8, col=MAG, centre=True)


def _side_table(S: Sheet, o: dict, x0, y0):
    l, d, h = o["length"], o["width"], o.get("height", 500); s = 30 * mm / max(l, h); c = S.c
    c.setStrokeColor(INK); c.setFillColor(colors.HexColor("#6b7280")); c.rect(x0, y0, l * s, h * s, stroke=1, fill=1)
    c.setStrokeColor(colors.white); c.line(x0 + 2, y0 + h * s * 0.5, x0 + l * s - 2, y0 + h * s * 0.5)
    S.leader(x0 + l * s * 0.5, y0 + h * s * 0.5, x0 - 8 * mm, y0 + h * s * 0.75, "1\"x1\" groove for drawer opening")
    S.dim(x0, y0, x0 + l * s, y0, S.d(l), off=-4 * mm); S.dim(x0 + l * s, y0, x0 + l * s, y0 + h * s, S.d(h), off=4 * mm)
    S.text("FRONT ELEVATION", x0 + l * s / 2, y0 - 9 * mm, 7, col=MAG, centre=True)
    sx = x0 + l * s + 22 * mm; c.setStrokeColor(INK); c.setFillColor(colors.HexColor("#6b7280")); c.rect(sx, y0, d * s, h * s, stroke=1, fill=1)
    S.text("SIDE ELEVATION", sx + d * s / 2, y0 - 9 * mm, 7, col=MAG, centre=True)


# ── wardrobe ─────────────────────────────────────────────────────────────────
def _wardrobe(S: Sheet, o: dict, room_h: float, x0, y0, bw, bh, internal: bool, loft_label: str | None):
    L, H = o["length"] if o["length"] >= o["width"] else o["width"], o.get("height", 2100)
    D = min(o["length"], o["width"]); top = room_h if loft_label else H
    s = min(bw / L, bh / top); c = S.c; ox, oy = x0, y0
    wl = cutting.wardrobe_layout(L, D, H)
    c.setStrokeColor(INK); c.setLineWidth(1); c.rect(ox - 8 * mm, oy, L * s + 16 * mm, top * s + 4 * mm)
    if loft_label and room_h - H > 120:
        c.setFillColor(colors.white); c.rect(ox, oy + H * s, L * s, (room_h - H) * s, stroke=1, fill=1)
        for u in range(30, int(L), 40): c.setLineWidth(0.3); c.line(ox + u * s, oy + (H + 25) * s, ox + u * s, oy + room_h * s)
        c.setLineWidth(0.8)
        S.leader(ox + 10 * s, oy + (H + (room_h - H) * 0.6) * s, ox - 12 * mm, oy + (H + (room_h - H) * 0.6) * s + 5 * mm, loft_label)
        S.leader(ox + 2, oy + (H + 12) * s, ox - 12 * mm, oy + (H + 12) * s - 4 * mm, "1\" space for opening")
    c.setFillColor(colors.HexColor("#d9d0c3")); c.setStrokeColor(INK); c.setLineWidth(0.8)
    if not internal:
        dw = L / wl["doors"]
        for k in range(wl["doors"]):
            c.rect(ox + k * dw * s, oy + 60 * s, dw * s, (H - 60) * s, stroke=1, fill=1)
            kx = ox + (k * dw + (dw - 70 if k % 2 == 0 else 70)) * s
            c.setFillColor(colors.white); c.circle(kx, oy + H * 0.5 * s, 1.4 * mm, stroke=1, fill=1); c.setFillColor(colors.HexColor("#d9d0c3"))
        c.setFillColor(colors.HexColor("#b5ab9d")); c.rect(ox, oy, L * s, 60 * s, stroke=1, fill=1)
        x = ox
        for k in range(wl["doors"]): S.dim(x, oy, x + dw * s, oy, "EQ", off=-4 * mm); x += dw * s
    else:
        c.setFillColor(colors.white); c.rect(ox, oy, L * s, H * s, stroke=1, fill=1)
        c.setFillColor(colors.HexColor("#b5ab9d")); c.rect(ox, oy, L * s, 60 * s, stroke=1, fill=1)
        for p in wl["partitions"]: c.setFillColor(colors.HexColor("#d9d0c3")); c.rect(ox + p * s, oy + 60 * s, cutting.T * s, (H - 60) * s, stroke=1, fill=1)
        for b in wl["bays"]:
            bx, w = ox + b["x0"] * s, b["width"] * s
            if b["kind"] == "SHELVES":
                n = b["shelves"]
                for k in range(1, n + 1): yy = oy + (60 + (H - 60) * k / (n + 1)) * s; c.setLineWidth(1.2); c.line(bx, yy, bx + w, yy)
                c.setLineWidth(0.8); S.text(f"{n} equal shelf", bx + w / 2 + 1 * mm, oy + H * 0.35 * s, 6, col=GREY, angle=90)
                S.dim(bx, oy, bx + w, oy, "EQ", off=-4 * mm)
            else:
                rod = oy + (H - b["rod_from_top"] - 40) * s; c.setLineWidth(1.6); c.line(bx + 1 * mm, rod, bx + w - 1 * mm, rod); c.setLineWidth(0.8)
                S.text("hanging rod", bx + w - 2 * mm, rod - 4 * mm, 7, right=True, font="Courier-Bold")
                y = oy + 60 * s
                for k in range(b["drawers"]):
                    c.setStrokeColor(colors.HexColor("#06b6d4") if k == b["drawers"] - 1 else INK); c.rect(bx + 1.5 * mm, y + 1, w - 3 * mm, b["drawer_h"] * s - 2, stroke=1, fill=0)
                    c.setStrokeColor(INK); S.text("GLASS DRAWER" if k == b["drawers"] - 1 else "DRAWER", bx + w / 2, y + b["drawer_h"] * s / 2 - 1 * mm, 6.5, centre=True, font="Courier-Bold"); y += b["drawer_h"] * s
                sw = w / b["small_drawers"]
                for k in range(b["small_drawers"]): c.rect(bx + k * sw, y, sw, b["small_h"] * s, stroke=1, fill=0); S.text("D", bx + (k + 0.5) * sw, y + b["small_h"] * s / 2 - 1 * mm, 7, centre=True, font="Courier-Bold")
                c.setLineWidth(1.2); c.line(bx, y + b["small_h"] * s, bx + w, y + b["small_h"] * s); c.setLineWidth(0.8)
                S.dim(bx, oy, bx + w, oy, "EQ", off=-4 * mm)
    S.dim(ox + L * s + 8 * mm, oy, ox + L * s + 8 * mm, oy + H * s, S.d(H), off=4 * mm)
    S.dim(ox, oy - 10 * mm, ox + L * s, oy - 10 * mm, S.d(L), off=0)
    S.text("INTERNAL DETAIL" if internal else "ELEVATION", ox, oy - 20 * mm, 11)


# ── kitchen ──────────────────────────────────────────────────────────────────
def _kitchen_run(S: Sheet, wall, L, W, H, objs, ops, x0, y0, bw, bh, label):
    c = S.c; wl = L if wall in "NS" else W; flip = wall in ("N", "W")
    def against(o):
        return {"S": o["y"] < 250, "N": W - (o["y"] + o["width"]) < 250, "W": o["x"] < 250, "E": L - (o["x"] + o["length"]) < 250}[wall]
    run = [o for o in objs if against(o) and (o.get("category") or "").lower().startswith("kitchen")]
    if not any((o.get("z") or 0) < 1200 for o in run): return False
    s = min(bw / wl, bh / H); ox, oy = x0, y0
    c.setStrokeColor(INK); c.setLineWidth(1); c.rect(ox, oy, wl * s, H * s)
    def pos(o):
        u = o["x"] if wall in "NS" else o["y"]; ln = o["length"] if wall in "NS" else o["width"]
        return (wl - u - ln if flip else u), ln
    for o in ops:
        if o["wall"] != wall or o.get("angled"): continue          # inner / angled walls aren't on this side
        a = (wl - o["offset"] - o["width"]) if flip else o["offset"]
        c.setFillColor(CYAN); c.setStrokeColor(INK); c.setLineWidth(2.2); c.rect(ox + a * s, oy + o["sill"] * s, o["width"] * s, o["height"] * s, stroke=1, fill=1); c.setLineWidth(0.8)
    base = sorted([o for o in run if (o.get("z") or 0) < 1200], key=lambda o: pos(o)[0])
    counter_top = max((o.get("height", 850) for o in base if o.get("height", 850) < 1200), default=850)
    for o in base:
        u, ln = pos(o); cat = (o.get("category") or "").lower(); hh = o.get("height", 850)
        if hh >= 1800:
            c.setFillColor(FILL); c.setStrokeColor(INK); c.rect(ox + u * s, oy, ln * s, hh * s, stroke=1, fill=1); S.text("tall unit", ox + (u + ln / 2) * s, oy + hh * 0.5 * s, 7, centre=True, font="Courier"); continue
        c.setFillColor(FILL); c.rect(ox + u * s, oy + 100 * s, ln * s, (hh - 100) * s, stroke=1, fill=1)
        lab = ("shutter" if cat == "kitchen sink" else "pull-out" if ln <= 450 else "PLAIN" if ln <= 650 else "shutter")
        if cat == "kitchen hob":
            for k, t in enumerate(("Cutlery", "C&S", "thali")):
                yy = oy + (100 + (hh - 100) * (k + 1) / 3) * s; c.setLineWidth(1.6); c.line(ox + u * s, yy, ox + (u + ln) * s, yy); c.setLineWidth(0.8)
                S.text(t, ox + (u + ln / 2) * s, yy - 4.5 * mm, 7, centre=True, font="Courier")
        elif cat == "kitchen filler": S.text("filler", ox + (u + ln / 2) * s, oy + hh * 0.5 * s, 6, centre=True, angle=90)
        else:
            if lab == "PLAIN":
                for k in (1, 2): yy = oy + (100 + (hh - 100) * k / 3) * s; c.setLineWidth(1.6); c.line(ox + u * s, yy, ox + (u + ln) * s, yy); c.setLineWidth(0.8)
            elif ln > 650: c.line(ox + (u + ln / 2) * s, oy + 100 * s, ox + (u + ln / 2) * s, oy + hh * s)
            S.text(lab, ox + (u + ln / 2) * s, oy + (100 + (hh - 100) * 0.25) * s, 7, centre=True, font="Courier")
        if cat == "kitchen sink":
            c.setStrokeColor(RED); c.rect(ox + (u + 60) * s, oy + (hh - 230) * s, (ln - 120) * s, 230 * s, stroke=1, fill=0); c.setStrokeColor(INK)
        if cat == "kitchen hob":
            hx = ox + (u + ln / 2) * s; c.setFillColor(colors.white)
            p = c.beginPath(); p.moveTo(hx - 450 * s, oy + 1950 * s); p.lineTo(hx + 450 * s, oy + 1950 * s); p.lineTo(hx + 160 * s, oy + 2200 * s); p.lineTo(hx - 160 * s, oy + 2200 * s); p.close(); c.drawPath(p, fill=1, stroke=1)
            for k in range(1, 6): yy = oy + (1950 + k * 40) * s; c.setLineWidth(0.3); c.line(hx - (450 - k * 55) * s, yy, hx + (450 - k * 55) * s, yy)
            c.setLineWidth(0.8); c.setDash(2, 1.5); c.rect(hx - 110 * s, oy + 2200 * s, 220 * s, (H - 2200) * s, stroke=1, fill=0); c.setDash()
    if base:
        u0 = min(pos(o)[0] for o in base if o.get("height", 850) < 1200); u1 = max(pos(o)[0] + pos(o)[1] for o in base if o.get("height", 850) < 1200)
        c.setFillColor(colors.HexColor("#b3b3b3")); c.rect(ox + u0 * s, oy + counter_top * s, (u1 - u0) * s, 40 * s, stroke=1, fill=1)
        c.setFillColor(INK)
        for k in range(int((u1 - u0) / 35)): c.circle(ox + (u0 + 15 + k * 35) * s, oy + (counter_top + 8 + (k * 7) % 25) * s, 0.25, stroke=0, fill=1)
        c.setLineWidth(1.6); c.line(ox + u0 * s, oy + (counter_top + 40) * s, ox + u1 * s, oy + (counter_top + 40) * s); c.setLineWidth(0.8)
        x = None
        for o in base:
            u, ln = pos(o); S.dim(ox + u * s, oy, ox + (u + ln) * s, oy, S.d(ln), off=-5 * mm)
    walls_u = [o for o in run if (o.get("z") or 0) >= 1200]
    for o in walls_u:
        u, ln = pos(o); z = o.get("z", 1450); hh = o.get("height", 700)
        c.setFillColor(FILL); c.setStrokeColor(INK); c.rect(ox + u * s, oy + z * s, ln * s, hh * s, stroke=1, fill=1)
        if ln > 650: c.line(ox + (u + ln / 2) * s, oy + z * s, ox + (u + ln / 2) * s, oy + (z + hh) * s)
        S.dim(ox + u * s, oy + (z + hh) * s, ox + (u + ln) * s, oy + (z + hh) * s, S.d(ln), off=4 * mm)
    if walls_u:
        z = min(o.get("z", 1450) for o in walls_u)
        S.dim(ox + wl * s + 6 * mm, oy + (counter_top + 40) * s, ox + wl * s + 6 * mm, oy + z * s, S.d(z - counter_top - 40), off=4 * mm)
    S.dim(ox + wl * s + 6 * mm, oy, ox + wl * s + 6 * mm, oy + (counter_top + 40) * s, S.d(counter_top + 40), off=12 * mm)
    S.text(label, ox, oy - 14 * mm, 11)
    # counter plan below
    py = oy - 48 * mm; dep = 600
    if base:
        c.setStrokeColor(INK); c.setFillColor(colors.white); c.rect(ox + u0 * s, py, (u1 - u0) * s, dep * s, stroke=1, fill=1)
        c.setLineWidth(0.3); c.line(ox + u0 * s, py, ox + u1 * s, py + dep * s); c.line(ox + u0 * s, py + dep * s, ox + u1 * s, py); c.setLineWidth(0.8)
        for o in base:
            u, ln = pos(o); cat = (o.get("category") or "").lower()
            if cat == "kitchen sink":
                c.setFillColor(colors.HexColor("#9ca3af")); c.rect(ox + (u + 80) * s, py + 80 * s, (ln - 160) * s, (dep - 180) * s, stroke=1, fill=1)
                c.setFillColor(BLUE); c.circle(ox + (u + ln / 2) * s, py + dep * 0.45 * s, 0.9 * mm, stroke=0, fill=1)
            if cat == "kitchen hob":
                for k in range(4): c.setFillColor(colors.white); c.circle(ox + (u + ln * (0.3 + 0.4 * (k % 2))) * s, py + dep * (0.3 + 0.4 * (k // 2)) * s, 2.2 * mm, stroke=1, fill=1)
        S.dim(ox + u1 * s, py, ox + u1 * s, py + dep * s, S.d(dep), off=5 * mm)
        S.text("COUNTER PLAN", ox, py - 7 * mm, 9)
    return True


# ── light detail (whole home) ────────────────────────────────────────────────
def _sym(S: Sheet, kind, x, y, r=1.6 * mm):
    c = S.c; c.saveState()
    if kind == "7W": c.setStrokeColor(RED); c.setFillColor(RED); c.circle(x, y, r * 0.6, stroke=1, fill=0); [c.line(x - r, y + d, x + r, y - d) for d in (-r, 0, r)]
    elif kind == "18W":
        c.setStrokeColor(BLUE); c.circle(x, y, r * 0.55, stroke=1, fill=0)
        for k in range(8): a = k * math.pi / 4; c.line(x + math.cos(a) * r * 0.55, y + math.sin(a) * r * 0.55, x + math.cos(a) * r, y + math.sin(a) * r)
    elif kind == "FAN":
        c.setStrokeColor(BLUE); c.circle(x, y, r * 2.6, stroke=1, fill=0)
        for k in range(3): a = math.pi / 2 + k * 2 * math.pi / 3; c.line(x, y, x + math.cos(a) * r * 2.6, y + math.sin(a) * r * 2.6)
    elif kind == "AC": c.setStrokeColor(MAG); c.rect(x - r * 2.5, y - r * 0.6, r * 5, r * 1.2, stroke=1, fill=0); c.line(x - r * 2.5, y, x + r * 2.5, y)
    elif kind == "WALL": c.setStrokeColor(MAG); p = c.beginPath(); p.moveTo(x - r, y); p.lineTo(x + r * 0.6, y + r * 0.8); p.lineTo(x + r * 0.6, y - r * 0.8); p.close(); c.drawPath(p, stroke=1, fill=0)
    elif kind == "BELL": c.setFillColor(RED); c.rect(x - r * 0.8, y - r * 0.5, r * 1.6, r, stroke=0, fill=1); c.circle(x, y + r * 0.6, r * 0.4, stroke=0, fill=1)
    elif kind == "WIFI":
        c.setStrokeColor(BLUE)
        for k in (0.5, 1.0, 1.5): c.arc(x - r * k, y - r * k, x + r * k, y + r * k, 30, 120)
        c.setFillColor(BLUE); c.circle(x, y, 0.4 * mm, stroke=0, fill=1)
    elif kind == "PROFILE": c.setStrokeColor(RED); c.setLineWidth(1.2); c.line(x - r * 2, y, x + r * 2, y)
    c.restoreState()


def _light_detail(S: Sheet, rows: list, latest: dict, fins: dict, room_openings, shells=None):
    placed = [r for r in rows if r["placed"] and r["L"] and latest.get(r["id"])]
    if not placed: return False
    S.page("light detail"); c = S.c
    x0, y0 = min(r["x"] for r in placed) - 300, min(r["y"] for r in placed) - 300
    x1, y1 = max(r["x"] + r["L"] for r in placed) + 300, max(r["y"] + r["W"] for r in placed) + 300
    bw, bh = PW - 100 * mm, PH - 72 * mm; s = min(bw / (x1 - x0), bh / (y1 - y0)); ox, oy = 18 * mm, 48 * mm   # room for outward door swings
    entry = None
    for r in placed:
        des = latest[r["id"]]; objs = des.design_json.get("objects", []); f = fins.get(r["id"]) or {}
        rx, ry = ox + (r["x"] - x0) * s, oy + (r["y"] - y0) * s; ops = room_openings(r["id"])
        sh = (shells or {}).get(r["id"])
        _plan(S, r["L"], r["W"], [], ops, rx - 300 * s, ry - 300 * s, (r["L"] + 600) * s, (r["W"] + 600) * s, names=False, markers=False, dims=False, shell=sh)
        for o in objs:
            c.setStrokeColor(colors.HexColor("#cfcfcf")); c.setLineWidth(0.4); c.rect(rx + o["x"] * s, ry + o["y"] * s, o["length"] * s, o["width"] * s)
        S.text(r["name"].upper(), rx + r["L"] * s / 2, ry + r["W"] * s / 2 + 3 * mm, 7, centre=True)
        ce = mep.ceiling(r["L"], r["W"], r["H"], objs, sh)
        for lt in ce["lights"]: _sym(S, "18W" if lt["type"] == "DOWNLIGHT" else "7W", rx + lt["x"] * s, ry + lt["y"] * s)
        if ce.get("fan") and (r["room_type"] or "").upper() not in ("BATHROOM", "WASH_AREA", "UTILITY", "POOJA", "STORE"): _sym(S, "FAN", rx + ce["fan"]["x"] * s, ry + ce["fan"]["y"] * s)
        cv = f.get("ceiling") or {}
        if cv.get("type") in ("COVE", "ISLAND"):
            b = cv.get("border", 600); c.setStrokeColor(RED); c.setLineWidth(1)
            if sh and len(sh["outline"]) > 4:                                           # odd room: the profile light follows the walls
                from shapely.geometry import Polygon
                ring = Polygon(sh["outline"]).buffer(-b, join_style=2)
                for g in getattr(ring, "geoms", [ring]):
                    if not g.is_empty: _poly(c, [(rx + x * s, ry + y * s) for x, y in list(g.exterior.coords)[:-1]])
            else:
                for (a1, b1, a2, b2) in ((b, b, r["L"] - b, b), (b, r["W"] - b, r["L"] - b, r["W"] - b)): c.line(rx + a1 * s, ry + b1 * s, rx + a2 * s, ry + b2 * s)
        for lt in f.get("lights", []):
            if lt["kind"] == "PENDANT" and lt.get("drop"): _sym(S, "WALL", rx + lt["x"] * s, ry + lt["y"] * s)
            else:
                for k in range(lt.get("count", 1)): _sym(S, "7W", rx + (lt["x"] + (k - (lt.get("count", 1) - 1) / 2) * 500) * s, ry + lt["y"] * s)
        el = mep.electrical(r["L"], r["W"], r["H"], objs, ops)
        for p in el["points"]:
            if p["type"] == "AC": _sym(S, "AC", rx + p["x"] * s, ry + (p["y"] - (150 if p["y"] > r["W"] / 2 else -150)) * s)
        if (r["room_type"] or "").upper() == "LIVING": _sym(S, "WIFI", rx + 300 * s, ry + r["W"] / 2 * s)
        if entry is None and homeplan.ZONE.get((r["room_type"] or "").upper(), 2) == 0:
            d = next((o for o in ops if o["kind"] == "DOOR"), None)
            if d:
                ex = {"S": (d["offset"] + d["width"] / 2, -600), "N": (d["offset"] + d["width"] / 2, r["W"] + 600), "W": (-600, d["offset"] + d["width"] / 2), "E": (r["L"] + 600, d["offset"] + d["width"] / 2)}[d["wall"]]
                entry = (rx + ex[0] * s, ry + ex[1] * s); _sym(S, "BELL", rx + (d["offset"] - 200) * s if d["wall"] in "NS" else rx + ex[0] * s, ry + ex[1] * s if d["wall"] in "NS" else ry + (d["offset"] - 200) * s)
    if entry:
        S.text("ENTRY", entry[0], entry[1] + 4 * mm, 11, col=colors.HexColor("#b91c1c"), bold=True, centre=True)
        c.setFillColor(colors.HexColor("#b91c1c")); p = c.beginPath(); p.moveTo(entry[0] - 2 * mm, entry[1] + 2 * mm); p.lineTo(entry[0] + 2 * mm, entry[1] + 2 * mm); p.lineTo(entry[0], entry[1] - 3 * mm); p.close(); c.drawPath(p, fill=1, stroke=0)
    lx, ly = PW - 62 * mm, 120 * mm
    S.text("LEGEND", lx, ly + 7 * mm, 9, bold=True)
    for k, (kind, lab) in enumerate((("7W", "7 W"), ("18W", "18 W"), ("WIFI", "WIFI"), ("AC", "A.C"), ("PROFILE", "profile light"), ("FAN", "fan"), ("BELL", "bell"), ("WALL", "wall light"))):
        yy = ly - k * 8 * mm; c.setStrokeColor(INK); c.setLineWidth(0.5); c.rect(lx, yy - 4 * mm, 14 * mm, 8 * mm); c.rect(lx + 14 * mm, yy - 4 * mm, 22 * mm, 8 * mm)
        if kind == "FAN": c.saveState(); _sym(S, kind, lx + 7 * mm, yy, 1.0 * mm); c.restoreState()
        else: _sym(S, kind, lx + 7 * mm, yy)
        S.text(lab, lx + 16 * mm, yy - 1 * mm, 7)
    return True


def build(db, pid: str, room_id: str | None = None, units: str | None = None) -> bytes:
    from app.routers.api import room_openings
    from app.services import company as companylib
    p = db.get(m.Project, pid); cl = db.get(m.Client, p.client_id) if p.client_id else None; comp = companylib.get(db)
    units_row = db.get(m.CompanySetting, "drawing_units"); units = units or (units_row.value if units_row and units_row.value in ("ftin", "mm") else "ftin")
    S = Sheet({"project": f"{p.project_number} {p.name}", "project_number": p.project_number, "client": (cl.name if cl else p.name),
               "designer": comp.get("name") or "-", "phone": comp.get("phone") or "-", "company": comp.get("name") or "", "units": units})
    rows = homeplan.boxes(db, pid)
    if room_id: rows = [r for r in rows if r["id"] == room_id]
    latest = {r["id"]: db.query(m.Design).filter_by(room_id=r["id"]).order_by(m.Design.version.desc()).first() for r in rows}
    fins = {k: (v.design_json.get("finishes") if v else None) for k, v in latest.items()}
    from app.routers.api import room_shape
    shells = {r["id"]: room_shape(db, r["id"]) for r in rows}
    if not room_id: _light_detail(S, rows, latest, fins, lambda rid: room_openings(db, rid), shells)
    renders: dict = {}
    for doc in db.query(m.Document).filter_by(project_id=pid, category="RENDER").order_by(m.Document.created_at.desc()):
        if doc.room_id: renders.setdefault(doc.room_id, []).append(doc)
    for r in rows:
        des = latest[r["id"]]
        if not des or not r["L"]: continue
        objs = des.design_json.get("objects", []); f = fins[r["id"]]; ops = room_openings(db, r["id"]); L, W, H = r["L"], r["W"], r["H"]
        kind = (r["room_type"] or "").upper()
        if kind == "KITCHEN":
            S.page(f"{r['name']} plan")
            _plan(S, L, W, objs, ops, 40 * mm, 46 * mm, 300 * mm, 200 * mm, f=f, shell=shells.get(r["id"]))
            def has_run(w):
                return any((o.get("category") or "").lower().startswith("kitchen") and (o.get("z") or 0) < 1200 and
                           {"S": o["y"] < 250, "N": W - (o["y"] + o["width"]) < 250, "W": o["x"] < 250, "E": L - (o["x"] + o["length"]) < 250}[w] for o in objs)
            runs = [w for w in ("N", "E", "S", "W") if has_run(w)]
            for k in range(0, len(runs), 2):
                S.page(f"{r['name']}")
                for j, wall in enumerate(runs[k:k + 2]):
                    _kitchen_run(S, wall, L, W, H, objs, ops, 30 * mm + j * 190 * mm, 95 * mm, 170 * mm, 120 * mm, f"ELEVATION {WALL_VIEW[wall]}")
            if not runs: S.text("No kitchen units in this design yet.", 30 * mm, PH / 2, 12)
        else:
            S.page(r["name"])
            _plan(S, L, W, objs, ops, 24 * mm, 56 * mm, 165 * mm, 98 * mm, f=f, shell=shells.get(r["id"]))            # room left below the plan for an outward door swing
            S.text(r["name"].upper(), 24 * mm + 82 * mm, 56 * mm + 49 * mm, 10, centre=True)
            feat = (f or {}).get("accent")
            wall = feat["wall"] if feat else None
            if not wall:
                bed = next((o for o in objs if (o.get("category") or "").lower() == "bed"), None)
                if bed: wall = concept._against(bed, L, W)
            if wall:
                ev = next((x for x in mep.elevations(L, W, H, objs, ops, shells.get(r["id"])) if x["wall"][0] == wall), None)
                _elevation(S, wall, L, W, H, objs, ops, f, 62 * mm, PH - 112 * mm, 128 * mm, 76 * mm, f"ELEVATION {WALL_VIEW[wall]}", ev)
            bed = next((o for o in objs if (o.get("category") or "").lower() == "bed"), None)
            if bed:
                bl = bed if concept._against(bed, L, W) in "NS" else {**bed, "length": bed["width"], "width": bed["length"]}
                _bed_detail(S, bl, 245 * mm, 45 * mm, 120 * mm)
                st = next((o for o in objs if (o.get("category") or "").lower() in ("bedside table", "nightstand", "side table")), None)
                if st: _side_table(S, st, 215 * mm, PH - 60 * mm)
            for i, wo in enumerate([o for o in objs if (o.get("category") or "").lower() == "wardrobe"]):
                S.page(f"{r['name']} wardrobe" + (f" {i + 1}" if i else ""))
                loft = "fluted mdf finish with WALL colour" if f and (f.get("style") in ("modern", "luxury", "industrial")) else "loft shutters / panel to ceiling"
                _wardrobe(S, wo, H, 62 * mm, 75 * mm, 140 * mm, 150 * mm, False, loft)
                _wardrobe(S, wo, H, 250 * mm, 75 * mm, 140 * mm, 150 * mm, True, loft)
        imgs = renders.get(r["id"], [])[:4]
        if imgs:
            S.page(f"{r['name']} views")
            for k, doc in enumerate(imgs):
                try:
                    ir = ImageReader(str(documents.safe_path(doc.storage_path))); iw, ih = ir.getSize()
                    bw2, bh2 = (PW - 60 * mm) / 2, (PH - 70 * mm) / 2; x = 20 * mm + (k % 2) * (bw2 + 10 * mm); y = 38 * mm + (1 - k // 2) * (bh2 + 6 * mm)
                    S.c.drawImage(ir, x, y, bw2, bh2, preserveAspectRatio=True)
                except Exception: pass
    if S.n == 0: S.page("No drawings yet"); S.text("Save designs (and apply a style) first, then download the drawing set again.", 30 * mm, PH / 2, 12)
    return S.bytes()
