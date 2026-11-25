"""Design presentation PDF — what an interior designer hands the client: cover, design concept (style idea, palette, materials), the home
plan, then one page per room (plan with the feature wall marked, finish schedule, feature-wall elevation, furniture list, the 3D views
saved for that room). Built only from saved data (latest design version + its concept, room sizes, openings, renders); no prices.
Landscape A4, ReportLab, fonts from pdf_fonts (₹ / Gujarati / Hindi when available)."""
import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from app.models import models as m
from app.services import concept, documents, homeplan, pdf_fonts

INK, GREY, ACCENT = colors.HexColor("#1c1917"), colors.HexColor("#78716c"), colors.HexColor("#b45309")
PW, PH = landscape(A4)
MARGIN = 14 * mm


def _hex(c: str | None, fallback="#d6d3d1"):
    try: return colors.HexColor(c or fallback)
    except Exception: return colors.HexColor(fallback)


class Doc:
    def __init__(self, company: str, project: str):
        self.F = pdf_fonts.get(); self.buf = io.BytesIO(); self.c = rl_canvas.Canvas(self.buf, pagesize=(PW, PH)); self.company, self.project = company, project
        self.c.setTitle(f"Design presentation — {project}"); self.page = 0

    def text(self, t, x, y, size=9, bold=False, col=INK, centre=False, right=False):
        c = self.c; c.setFont(self.F["bold"] if bold else self.F["regular"], size); c.setFillColor(col); s = pdf_fonts.clean(t)
        fn = c.drawCentredString if centre else c.drawRightString if right else c.drawString
        fn(x, y, s, shaping=self.F["shaping"])

    def para(self, t, x, y, width_chars=95, size=9, lead=12, col=INK) -> float:
        line = ""
        for w in str(t).split():
            if len(line) + len(w) > width_chars: self.text(line, x, y, size, col=col); y -= lead; line = ""
            line += w + " "
        if line: self.text(line, x, y, size, col=col); y -= lead
        return y

    def new_page(self, title: str | None = None):
        if self.page: self._footer(); self.c.showPage()
        self.page += 1
        if title:
            self.text(title, MARGIN, PH - MARGIN - 6 * mm, 18, bold=True)
            self.c.setStrokeColor(ACCENT); self.c.setLineWidth(1.4); self.c.line(MARGIN, PH - MARGIN - 9 * mm, MARGIN + 60 * mm, PH - MARGIN - 9 * mm)

    def _footer(self):
        self.text(f"{self.company} · {self.project} · design presentation", MARGIN, 7 * mm, 7, col=GREY)
        self.text(f"{self.page}", PW - MARGIN, 7 * mm, 7, col=GREY, right=True)

    def swatch(self, x, y, colour, label, sub=None, w=22 * mm):
        c = self.c; c.setFillColor(_hex(colour)); c.setStrokeColor(colors.HexColor("#d6d3d1")); c.roundRect(x, y, w, 14 * mm, 2 * mm, stroke=1, fill=1)
        self.text(label, x, y - 4 * mm, 7.5, bold=True); self.text(sub or (colour or ""), x, y - 7.5 * mm, 6.5, col=GREY)

    def bytes(self) -> bytes:
        self._footer(); self.c.showPage(); self.c.save(); return self.buf.getvalue()


def _room_plan(d: Doc, r: dict, objs: list, ops: list, f: dict | None, x0, y0, w, h, names=True):
    """Room drawn into the box (x0, y0, w, h): walls, furniture, openings, rug, feature wall in its colour."""
    c = d.c; L, W = r["L"], r["W"]; s = min(w / L, h / W); ox, oy = x0 + (w - L * s) / 2, y0 + (h - W * s) / 2
    c.setFillColor(_hex((f or {}).get("floor", {}).get("tone"), "#f5f1ea")); c.setFillAlpha(0.35); c.rect(ox, oy, L * s, W * s, stroke=0, fill=1); c.setFillAlpha(1)
    if f and f.get("rug"):
        g = f["rug"]; c.setFillColor(_hex(g["colour"])); c.setFillAlpha(0.35); c.rect(ox + g["x"] * s, oy + g["y"] * s, g["length"] * s, g["width"] * s, stroke=0, fill=1); c.setFillAlpha(1)
    outline = (r.get("shell") or {}).get("outline")
    if outline and len(outline) > 4:                                       # M41: L-shaped / angled room
        p = c.beginPath(); p.moveTo(ox + outline[0][0] * s, oy + outline[0][1] * s)
        for x, y in outline[1:]: p.lineTo(ox + x * s, oy + y * s)
        p.close(); c.setStrokeColor(INK); c.setLineWidth(2.2); c.drawPath(p, stroke=1, fill=0)
    else: c.setStrokeColor(INK); c.setLineWidth(2.2); c.rect(ox, oy, L * s, W * s, stroke=1, fill=0)
    for st in (r.get("shell") or {}).get("structures") or []:
        col = st["kind"] in ("COLUMN", "PILLAR"); c.setLineWidth(0.6); c.setStrokeColor(colors.HexColor("#57534e"))
        c.setFillColor(colors.HexColor("#78716c")); c.setDash() if col else c.setDash(3, 2)
        c.rect(ox + st["x"] * s, oy + st["y"] * s, st["length"] * s, st["width"] * s, stroke=1, fill=1 if col else 0); c.setDash()
    for o in ops:
        a, wd = o["offset"] * s, o["width"] * s
        seg = ((ox + o["x0"] * s, oy + o["y0"] * s, ox + o["x1"] * s, oy + o["y1"] * s) if "x0" in o else
               {"S": (ox + a, oy, ox + a + wd, oy), "N": (ox + a, oy + W * s, ox + a + wd, oy + W * s), "W": (ox, oy + a, ox, oy + a + wd), "E": (ox + L * s, oy + a, ox + L * s, oy + a + wd)}[o["wall"]])
        c.setStrokeColor(colors.white); c.setLineWidth(3); c.line(*seg)
        c.setStrokeColor(colors.HexColor("#0ea5e9") if o["kind"] == "WINDOW" else ACCENT); c.setLineWidth(1.2); c.line(*seg)
    a = (f or {}).get("accent")
    if a:
        p0, p1 = a["from"] * s, a["to"] * s
        seg = {"S": (ox + p0, oy + 2, ox + p1, oy + 2), "N": (ox + p0, oy + W * s - 2, ox + p1, oy + W * s - 2), "W": (ox + 2, oy + p0, ox + 2, oy + p1), "E": (ox + L * s - 2, oy + p0, ox + L * s - 2, oy + p1)}[a["wall"]]
        c.setStrokeColor(_hex(a["colour"])); c.setLineWidth(5); c.line(*seg)
    c.setLineWidth(0.6)
    for o in objs:
        up = (o.get("z") or 0) >= 1200
        c.setStrokeColor(colors.HexColor("#92400e")); c.setFillColor(colors.HexColor("#bae6fd" if up else "#fde68a")); c.setDash(2, 2) if up else c.setDash()
        c.rect(ox + o["x"] * s, oy + o["y"] * s, o["length"] * s, o["width"] * s, stroke=1, fill=1); c.setDash()
        if names and o["length"] * s > 14 * mm:
            d.text(o["name"][:28], ox + (o["x"] + o["length"] / 2) * s, oy + (o["y"] + o["width"] / 2) * s - 1.2 * mm, 5.5, centre=True, col=INK)
    return s


def build(db, pid: str, company: str) -> bytes:
    from app.routers.api import room_openings
    p = db.get(m.Project, pid); client = db.get(m.Client, p.client_id) if p.client_id else None
    from app.routers.api import room_shape
    rooms = homeplan.boxes(db, pid)
    for r in rooms: r["shell"] = room_shape(db, r["id"])
    latest = {r["id"]: db.query(m.Design).filter_by(room_id=r["id"]).order_by(m.Design.version.desc()).first() for r in rooms}
    fins = {k: (v.design_json.get("finishes") if v else None) for k, v in latest.items()}
    any_f = next((f for f in fins.values() if f), None)
    style = concept.STYLES.get(any_f["style"]) if any_f else None
    d = Doc(company, f"{p.project_number} {p.name}")

    # cover
    d.new_page(); c = d.c
    c.setFillColor(colors.HexColor("#faf7f2")); c.rect(0, 0, PW, PH, stroke=0, fill=1)
    if any_f:
        pal = any_f.get("palette", {})
        for i, k in enumerate(("wall", "accent", "wood", "fabric", "metal")):
            c.setFillColor(_hex(pal.get(k))); c.rect(PW - 95 * mm + i * 16 * mm, 0, 16 * mm, PH, stroke=0, fill=1)
    d.text(company, MARGIN + 6 * mm, PH - 40 * mm, 12, col=GREY)
    d.text("Interior design proposal", MARGIN + 6 * mm, PH - 62 * mm, 30, bold=True)
    d.text(p.name, MARGIN + 6 * mm, PH - 78 * mm, 18)
    if client: d.text(f"For {client.name}" + (f", {client.city}" if client.city else ""), MARGIN + 6 * mm, PH - 88 * mm, 12, col=GREY)
    if style: d.text(f"{style['label']} style", MARGIN + 6 * mm, PH - 108 * mm, 16, bold=True, col=ACCENT)
    d.text(f"{p.project_number} · {date.today():%d %B %Y} · {sum(1 for r in rooms if latest[r['id']])} rooms", MARGIN + 6 * mm, 30 * mm, 9, col=GREY)

    # concept
    if style and any_f:
        d.new_page("Design concept")
        y = d.para(style["idea"], MARGIN, PH - 40 * mm, 110, 11, 15)
        d.text("Palette", MARGIN, y - 8 * mm, 11, bold=True)
        pal = any_f.get("palette", {}); names = {"wall": "Walls", "accent": "Accent", "wood": "Wood", "fabric": "Fabrics", "metal": "Metal"}
        for i, k in enumerate(("wall", "accent", "wood", "fabric", "metal")): d.swatch(MARGIN + i * 30 * mm, y - 30 * mm, pal.get(k), names[k])
        used = lambda key, table: sorted({table[f[key]["type" if key != "floor" else "kind"]] for f in fins.values() if f and f.get(key)})
        yy = y - 52 * mm
        for title, items in (("Feature walls", used("accent", concept.ACCENT_TYPES)), ("Ceilings", used("ceiling", concept.CEILINGS)), ("Flooring", used("floor", concept.FLOORS))):
            d.text(title, MARGIN, yy, 10, bold=True); yy -= 5 * mm
            for it in items: d.text(f"• {it}", MARGIN + 4 * mm, yy, 9); yy -= 4.5 * mm
            yy -= 3 * mm
        d.text("Every room follows this style guide; each room's page lists its own finishes.", MARGIN, 22 * mm, 8, col=GREY)

    # home plan
    placed = [r for r in rooms if r["placed"] and r["L"]]
    if placed:
        d.new_page("Home plan")
        x0, y0 = min(r["x"] for r in placed), min(r["y"] for r in placed)
        x1, y1 = max(r["x"] + r["L"] for r in placed), max(r["y"] + r["W"] for r in placed)
        bw, bh = PW - 2 * MARGIN, PH - 2 * MARGIN - 22 * mm; s = min(bw / (x1 - x0), bh / (y1 - y0)); ox, oy = MARGIN + (bw - (x1 - x0) * s) / 2, MARGIN + 6 * mm
        for r in placed:
            objs = latest[r["id"]].design_json.get("objects", []) if latest[r["id"]] else []
            _room_plan(d, r, objs, room_openings(db, r["id"]), fins[r["id"]], ox + (r["x"] - x0) * s, oy + (r["y"] - y0) * s, r["L"] * s, r["W"] * s, names=False)
            d.text(r["name"], ox + (r["x"] - x0 + r["L"] / 2) * s, oy + (r["y"] - y0 + r["W"] / 2) * s, 8, bold=True, centre=True)
            d.text(f"{r['L']:.0f} × {r['W']:.0f}", ox + (r["x"] - x0 + r["L"] / 2) * s, oy + (r["y"] - y0 + r["W"] / 2) * s - 3.5 * mm, 6.5, centre=True, col=GREY)
        d.text("N ↑", PW - MARGIN - 10 * mm, PH - MARGIN - 6 * mm, 12, bold=True)

    # rooms
    renders = {}
    for doc in db.query(m.Document).filter_by(project_id=pid, category="RENDER").order_by(m.Document.created_at.desc()):
        if doc.room_id: renders.setdefault(doc.room_id, []).append(doc)
    for r in rooms:
        des = latest[r["id"]]
        if not des or not r["L"]: continue
        f = fins[r["id"]]; objs = des.design_json.get("objects", []); ops = room_openings(db, r["id"])
        d.new_page(r["name"])
        d.text(f"{r['room_type'].replace('_', ' ').title()} · {r['L']:.0f} × {r['W']:.0f} mm, ceiling {r['H']:.0f} mm · design v{des.version}", MARGIN, PH - MARGIN - 15 * mm, 9, col=GREY)
        _room_plan(d, r, objs, ops, f, MARGIN, 62 * mm, 120 * mm, 105 * mm)
        # finish schedule
        x, y = MARGIN + 132 * mm, PH - MARGIN - 26 * mm
        d.text("Finish schedule", x, y, 11, bold=True); y -= 7 * mm
        def row(label, value, colour=None):
            nonlocal y
            d.text(label, x, y, 8, bold=True, col=GREY)
            if colour: c.setFillColor(_hex(colour)); c.setStrokeColor(colors.HexColor("#d6d3d1")); c.rect(x + 30 * mm, y - 1 * mm, 4 * mm, 4 * mm, stroke=1, fill=1)
            d.para(value, x + (36 if colour else 30) * mm, y, 62, 8.5, 10.5); y -= 6.5 * mm if len(value) < 62 else 11 * mm
        if f:
            row("Walls", "Paint", f["walls"]["colour"])
            if f.get("accent"):
                a = f["accent"]; row("Feature wall", f"{concept.ACCENT_TYPES[a['type']]} on the {dict(N='north', E='east', S='south', W='west')[a['wall']]} wall, {(a['to'] - a['from']) / 1000:.2f} × {a['height'] / 1000:.2f} m", a["colour"])
            row("Ceiling", f["ceiling"]["label"] + (f", {f['ceiling']['drop']} mm drop" if f["ceiling"].get("drop") else ""))
            row("Flooring", f["floor"]["label"], f["floor"]["tone"])
            if f.get("curtains"): row("Windows", f"{'Blinds' if f['curtains'][0]['kind'] == 'BLIND' else 'Curtains'} on {len(f['curtains'])} window(s)", f["curtains"][0]["colour"])
            if f.get("rug"): row("Rug", f"{f['rug']['length'] / 1000:.1f} × {f['rug']['width'] / 1000:.1f} m", f["rug"]["colour"])
            if f.get("art"): row("Wall art", f"{len(f['art'])} piece(s), {f['art'][0]['width']} mm wide")
            if f.get("plants"): row("Plants", f"{len(f['plants'])} in the corners")
            lt = [x2 for x2 in f.get("lights", [])]
            if lt: row("Lighting", ", ".join(f"{x2.get('count', 1)} × {x2['kind'].lower()}" for x2 in lt) + ("; cove LED" if f['ceiling'].get('cove_rm') else ""))
        else: row("Design", "No design concept applied yet (Design Studio → Home design).")
        # furniture list
        y -= 3 * mm; d.text("Furniture", x, y, 11, bold=True); y -= 6 * mm
        for o in objs[:14]:
            d.text(f"• {o['name']}", x, y, 8); d.text(f"{o['length']:.0f} × {o['width']:.0f} × {o.get('height', 0):.0f} mm", x + 75 * mm, y, 7.5, col=GREY); y -= 4.6 * mm
        if len(objs) > 14: d.text(f"… and {len(objs) - 14} more", x, y, 7.5, col=GREY)
        # feature wall elevation
        if f and f.get("accent"):
            a = f["accent"]; wl = r["L"] if a["wall"] in "NS" else r["W"]; ex, ey, ew, eh = MARGIN, 14 * mm, 120 * mm, 40 * mm
            s = min(ew / wl, eh / r["H"]); c.setStrokeColor(INK); c.setLineWidth(1); c.rect(ex, ey, wl * s, r["H"] * s, stroke=1, fill=0)
            c.setFillColor(_hex(a["colour"])); c.setFillAlpha(0.6); c.rect(ex + a["from"] * s, ey + a.get("z0", 0) * s, (a["to"] - a["from"]) * s, a["height"] * s, stroke=0, fill=1); c.setFillAlpha(1)
            def against(o):
                return {"S": o["y"] < 150, "N": r["W"] - (o["y"] + o["width"]) < 150, "W": o["x"] < 150, "E": r["L"] - (o["x"] + o["length"]) < 150}[a["wall"]]
            for o in objs:
                if not against(o): continue
                u = o["x"] if a["wall"] in "NS" else o["y"]; ln = o["length"] if a["wall"] in "NS" else o["width"]
                c.setFillColor(colors.HexColor("#fde68a")); c.setStrokeColor(colors.HexColor("#92400e")); c.rect(ex + u * s, ey + (o.get("z") or 0) * s, ln * s, o.get("height", 0) * s, stroke=1, fill=1)
            d.text(f"Feature wall elevation — {concept.ACCENT_TYPES[a['type']]}", ex, ey + eh + 3 * mm, 8.5, bold=True)
        # renders
        imgs = renders.get(r["id"], [])[:2]
        for i, doc in enumerate(imgs):
            try:
                ir = ImageReader(str(documents.safe_path(doc.storage_path))); iw, ih = ir.getSize()
                bw2 = 66 * mm; bh2 = bw2 * ih / iw
                c.drawImage(ir, PW - MARGIN - bw2 - i * (bw2 + 4 * mm), 14 * mm, bw2, min(bh2, 46 * mm), preserveAspectRatio=True, anchor="sw")
            except Exception: pass
        if imgs: d.text("3D views", PW - MARGIN - 66 * mm, 14 * mm + 49 * mm, 8.5, bold=True)
    if not any(latest.values()):
        d.new_page("No designs yet"); d.para("Generate layouts and apply a style in Design Studio → Home design, then download this presentation again.", MARGIN, PH - 45 * mm)
    return d.bytes()
