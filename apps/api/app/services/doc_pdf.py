"""Generic business document PDF (purchase order, delivery challan, handover certificate) in the same style as the quotation."""
import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.quotation_pdf import ACCENT, GREY, INK, _fonts


def render(*, company: dict, title: str, number: str, meta: list[tuple[str, str]], parties: list[tuple[str, list[str]]],
           header: list[str], rows: list[list[str]], widths: list[float], right_cols: tuple = (), totals: list[tuple[str, str]] = (),
           paragraphs: list[str] = (), signatures: tuple[str, str] = ("Received by (signature, name, date)", "Authorised signatory")) -> bytes:
    reg, bold, latin_only = _fonts()
    def t(x) -> str:
        x = "" if x is None else str(x)
        if latin_only: x = x.encode("cp1252", "replace").decode("cp1252")
        return escape(x)
    def S(name, **k):
        return ParagraphStyle(name, fontName=k.pop("fontName", reg), fontSize=k.pop("size", 9), leading=k.pop("lead", 12), textColor=k.pop("color", INK), **k)
    body, small, h = S("b"), S("s", size=8, lead=10, color=GREY), S("h", size=10, lead=13, fontName=bold, spaceBefore=8, spaceAfter=3)
    cell, rcell, hcell = S("c", size=8.5, lead=11), S("r", size=8.5, lead=11, alignment=2), S("hc", size=8, lead=10, fontName=bold, color=colors.white)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16*mm, rightMargin=16*mm, topMargin=14*mm, bottomMargin=16*mm, title=f"{title} {number}", author=company["name"])
    story = [Table([[Paragraph(f'<font name="{bold}" size="15">{t(company["name"])}</font>', body),
                     Paragraph(f'<font name="{bold}" size="16" color="#b45309">{t(title.upper())}</font>', S("q", alignment=2))]],
                   colWidths=[100*mm, 78*mm], style=[("VALIGN", (0, 0), (-1, -1), "BOTTOM")])]
    contact = " · ".join(x for x in (company.get("address"), company.get("phone"), company.get("email"), f"GSTIN {company['gstin']}" if company.get("gstin") else "") if x)
    if contact: story.append(Paragraph(t(contact), small))
    story.append(Spacer(1, 4*mm))
    story.append(Table([[Paragraph(f"<b>{t(k)}</b>", small), Paragraph(t(v), body)] for k, v in [("Number", number)] + list(meta)],
                       colWidths=[38*mm, 140*mm], style=[("BOTTOMPADDING", (0, 0), (-1, -1), 1), ("TOPPADDING", (0, 0), (-1, -1), 1)]))
    if parties:
        cells = [[Paragraph(f"<b>{t(label)}</b><br/>" + "<br/>".join(t(x) for x in lines if x), body) for label, lines in parties]]
        story += [Spacer(1, 3*mm), Table(cells, colWidths=[178*mm / len(parties)] * len(parties),
                                         style=[("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6d3d1")), ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6d3d1")),
                                                ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)])]
    story.append(Spacer(1, 4*mm))
    data = [[Paragraph(t(x), hcell) for x in header]] + [[Paragraph(t(v), rcell if i in right_cols else cell) for i, v in enumerate(r)] for r in rows]
    for label, val in totals:
        data.append([""] * (len(header) - 2) + [Paragraph(f"<b>{t(label)}</b>", rcell), Paragraph(f"<b>{t(val)}</b>", rcell)])
    tbl = Table(data, colWidths=[w*mm for w in widths], repeatRows=1)
    tbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), ACCENT), ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#e7e5e4")),
                             ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story.append(tbl)
    for p in paragraphs: story += [Spacer(1, 2*mm), Paragraph(t(p), body)]
    story += [Spacer(1, 16*mm), Table([["", "", ""], [signatures[0], "", f"{signatures[1]} — {company['name']}"]], colWidths=[80*mm, 18*mm, 80*mm],
                                      style=[("LINEABOVE", (0, 1), (0, 1), 0.5, INK), ("LINEABOVE", (2, 1), (2, 1), 0.5, INK), ("FONTSIZE", (0, 0), (-1, -1), 8)])]
    def foot(c, d):
        c.saveState(); c.setFont(reg, 7); c.setFillColor(GREY)
        c.drawString(16*mm, 9*mm, t(f"{number} · {company['name']}")); c.drawRightString(A4[0] - 16*mm, 9*mm, f"Page {d.page}"); c.restoreState()
    doc.build(story, onFirstPage=foot, onLaterPages=foot)
    return buf.getvalue()
