"""Quotation PDF (ReportLab, zero cost). Built-in Helvetica => Latin text; set PDF_FONT_PATH for other scripts.
Amounts use 'Rs.' because the built-in fonts have no rupee sign."""
import io, os
from datetime import timedelta
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import settings
from app.services.cost_engine import D, inr, split_payments

PAYMENT_SCHEDULE = [("Agreement signing", 30), ("Design approval", 20), ("Material procurement", 25), ("Installation complete", 20), ("Handover and final QC", 5)]
TERMS = ["Prices are based on the approved design and are valid until the date shown.",
         "Any change to scope, materials or dimensions after approval may change the price.",
         "Material selection is finalised at design approval.",
         "The site must be clear and accessible before installation starts.",
         "Warranty, delivery timelines and disputes are as set out in the contract signed on acceptance."]
INK, ACCENT, GREY = colors.HexColor("#1c1917"), colors.HexColor("#b45309"), colors.HexColor("#78716c")


def _fonts():
    path = settings.PDF_FONT_PATH
    if path and os.path.exists(path):
        pdfmetrics.registerFont(TTFont("IQFont", path)); return "IQFont", "IQFont", False
    return "Helvetica", "Helvetica-Bold", True


def _pct(v) -> str:
    d = D(v); return format(d.quantize(Decimal(1)) if d == d.to_integral() else d.normalize(), "f")


def render(*, quotation_no: str, issued, boq: dict, items: list[dict], project: dict, room: dict, client: dict | None, design_version: int, company: dict | None = None) -> bytes:
    C = company or {"name": settings.COMPANY_NAME, "address": settings.COMPANY_ADDRESS, "phone": settings.COMPANY_PHONE, "email": settings.COMPANY_EMAIL,
                    "gstin": settings.COMPANY_GSTIN, "quote_valid_days": settings.QUOTE_VALID_DAYS}
    reg, bold, latin_only = _fonts()
    def t(x) -> str:   # make text safe for the PDF font and for Paragraph markup
        x = "" if x is None else str(x)
        if latin_only: x = x.encode("cp1252", "replace").decode("cp1252")
        return escape(x)
    def S(name, **k):
        return ParagraphStyle(name, fontName=k.pop("fontName", reg), fontSize=k.pop("size", 9), leading=k.pop("lead", 12), textColor=k.pop("color", INK), **k)
    body, small, h2 = S("b"), S("s", size=8, lead=10, color=GREY), S("h", size=11, lead=14, fontName=bold, spaceBefore=10, spaceAfter=4)
    cell, right = S("c", size=8.5, lead=11), S("r", size=8.5, lead=11, alignment=2)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16*mm, rightMargin=16*mm, topMargin=14*mm, bottomMargin=16*mm,
                            title=f"Quotation {quotation_no}", author=C["name"])
    story = []

    head = [[Paragraph(f'<font name="{bold}" size="15">{t(C["name"])}</font>', body),
             Paragraph(f'<font name="{bold}" size="18" color="#b45309">QUOTATION</font>', S("q", alignment=2))]]
    story += [Table(head, colWidths=[110*mm, 66*mm], style=[("VALIGN", (0, 0), (-1, -1), "BOTTOM")])]
    contact = " · ".join(x for x in (C["address"], C["phone"], C["email"], f"GSTIN {C['gstin']}" if C["gstin"] else "") if x)
    if contact: story.append(Paragraph(t(contact), small))
    story.append(Spacer(1, 5*mm))

    valid_until = issued + timedelta(days=int(C["quote_valid_days"]))
    client_lines = [t(client["name"])] + [t(client[k]) for k in ("company", "address", "city", "phone", "email") if client.get(k)] if client else ["Not linked to a client yet"]
    info = [[Paragraph(f'<font name="{bold}">Quotation no.</font><br/>{t(quotation_no)}<br/><font name="{bold}">Date</font> {issued:%d %b %Y}<br/><font name="{bold}">Valid until</font> {valid_until:%d %b %Y}', body),
             Paragraph(f'<font name="{bold}">Client</font><br/>' + "<br/>".join(client_lines), body),
             Paragraph(f'<font name="{bold}">Project</font><br/>{t(project["name"])} ({t(project["project_number"])})<br/><font name="{bold}">Room</font> {t(room["name"])}<br/><font name="{bold}">Design</font> version {design_version}', body)]]
    story += [Table(info, colWidths=[58*mm, 58*mm, 60*mm], style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d6d3d1")),
                                                              ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e7e5e4")), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)])]

    story.append(Paragraph("Bill of quantities", h2))
    rows = [["#", "Item", "Qty", "Rate (Rs.)", "Labour (Rs.)", "Amount (Rs.)"]]
    for i, it in enumerate(items, 1):
        desc = f'{t(it["description"])}' + (f'<br/><font size="7" color="#78716c">{t(it["sku"])}{" · " + t(it["material"]) if it["material"] else ""}</font>' if it["sku"] or it["material"] else "")
        qty = format(D(it["qty"]).normalize(), "f")
        rows.append([str(i), Paragraph(desc, cell), Paragraph(f'{qty} {t(it["unit"])}', right), Paragraph(inr(it["rate"]), right), Paragraph(inr(it["labour"]) if D(it["labour"]) else "—", right), Paragraph(inr(it["total"]), right)])
    tbl = Table(rows, colWidths=[8*mm, 78*mm, 18*mm, 24*mm, 24*mm, 24*mm], repeatRows=1)
    tbl.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, 0), bold), ("FONTNAME", (0, 1), (-1, -1), reg), ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("BACKGROUND", (0, 0), (-1, 0), INK),
                             ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("ALIGN", (2, 0), (-1, 0), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafaf9")]), ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#e7e5e4"))]))
    story.append(tbl)

    p = boq["params"]; tt = boq["totals"]
    from app.services.boq import gst_on
    gst = gst_on(p)
    summary = [("Subtotal (materials and labour)", tt["subtotal"]), (f'Overhead ({_pct(p["overhead_pct"])}%)', tt["overhead"]), (f'Margin ({_pct(p["margin_pct"])}%)', tt["margin"]),
               ("Total before tax" if gst else "Total before discount", tt["pre_tax"]), (f'Discount ({_pct(p["discount_pct"])}%)', "-" + tt["discount"]), ("After discount", tt["after_discount"])]
    if gst: summary.append((f'GST ({_pct(p["gst_pct"])}%)', tt["gst"]))
    srows = [[Paragraph(t(a), cell), Paragraph("-" + inr(b[1:]) if str(b).startswith("-") else inr(b), right)] for a, b in summary]
    srows.append([Paragraph(f'<font name="{bold}">{"Grand total (incl. GST)" if gst else "Grand total"}</font>', cell), Paragraph(f'<font name="{bold}">Rs. {inr(tt["grand_total"])}</font>', right)])
    st = Table(srows, colWidths=[56*mm, 36*mm], hAlign="RIGHT")
    last = len(srows) - 1
    st.setStyle(TableStyle([("LINEABOVE", (0, 3), (-1, 3), 0.5, GREY), ("LINEABOVE", (0, last), (-1, last), 1, INK), ("BACKGROUND", (0, last), (-1, last), colors.HexColor("#fef3c7")),
                            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story += [Spacer(1, 4*mm), KeepTogether([st])]
    if not gst: story.append(Paragraph("GST is not charged on this quotation.", S("ng", size=8, lead=10, color=GREY, alignment=2)))

    shares = split_payments(tt["grand_total"], [pc for _, pc in PAYMENT_SCHEDULE])
    prow = [["Milestone", "%", "Amount (Rs.)"]] + [[a, str(pc), Paragraph(inr(s), right)] for (a, pc), s in zip(PAYMENT_SCHEDULE, shares)]
    pt = Table(prow, colWidths=[90*mm, 20*mm, 40*mm], hAlign="LEFT")
    pt.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), reg), ("FONTNAME", (0, 0), (-1, 0), bold), ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("LINEBELOW", (0, 0), (-1, 0), 0.5, GREY),
                            ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("ALIGN", (2, 0), (2, 0), "RIGHT")]))
    story += [Spacer(1, 6*mm), KeepTogether([Paragraph("Payment schedule", h2), pt])]
    story += [KeepTogether([Paragraph("Terms and conditions", h2)] + [Paragraph(f"{i}. {t(x)}", small) for i, x in enumerate(TERMS, 1)])]

    sig = Table([["", "", ""], ["Accepted by client (signature and date)", "", f"For {C['name']}"]], colWidths=[78*mm, 20*mm, 78*mm], rowHeights=[16*mm, None])
    sig.setStyle(TableStyle([("LINEABOVE", (0, 1), (0, 1), 0.5, GREY), ("LINEABOVE", (2, 1), (2, 1), 0.5, GREY), ("FONTNAME", (0, 0), (-1, -1), reg), ("FONTSIZE", (0, 0), (-1, -1), 8), ("TEXTCOLOR", (0, 0), (-1, -1), GREY)]))
    story += [Spacer(1, 8*mm), KeepTogether([sig])]

    def footer(c, d):
        c.saveState(); c.setFont(reg, 7.5); c.setFillColor(GREY)
        c.drawString(16*mm, 9*mm, f"{quotation_no} · {C['name']}"); c.drawRightString(A4[0] - 16*mm, 9*mm, f"Page {d.page}"); c.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
