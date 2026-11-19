"""M27 PDF fonts: an installed font with ₹ + Gujarati + Hindi is found automatically (Windows: Nirmala UI; Linux: FreeSans), PDFs then print
the rupee sign and Indian-script names (shaped with uharfbuzz); PDF_FONTS=builtin / no font → Helvetica + 'Rs.' and nothing crashes."""
import os
import sys

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import doc_pdf, pdf_fonts

HAS_FONT = any(os.path.exists(r) for r, _ in pdf_fonts.CANDIDATES)
GUJ_NAME, HIN_NAME = "મેહતા ઇન્ટીરીયર્સ", "शर्मा फर्नीचर"


def text(b): d = pdfium.PdfDocument(b); return "\n".join(d[i].get_textpage().get_text_range() for i in range(len(d)))


@pytest.fixture
def fonts(monkeypatch):
    def use(**kw):
        for k, v in kw.items(): monkeypatch.setattr(settings, k, v)
        pdf_fonts.get.cache_clear(); return pdf_fonts.get()
    yield use
    pdf_fonts.get.cache_clear()


def doc():
    return doc_pdf.render(company={"name": GUJ_NAME, "address": "Ahmedabad", "phone": "", "email": "", "gstin": ""}, title="Purchase Order", number="PO-1",
                          meta=[("Supplier", HIN_NAME)], parties=[], header=["#", "Item", "Amount (Rs.)"], rows=[["1", "Plywood 18mm", "1,24,000.00"]],
                          widths=[10, 120, 48], right_cols=(2,), totals=[("Total (Rs.)", "1,24,000.00")])


@pytest.mark.skipif(not HAS_FONT, reason="no Indian-script font installed on this machine")
def test_auto_font_prints_rupee_and_indian_scripts(fonts):
    f = fonts(PDF_FONT_PATH="", PDF_FONTS="auto")
    assert f["unicode"] and f["rupee"] and f["gujarati"] and f["hindi"] and f["shaping"]
    assert pdf_fonts.clean("Amount (Rs.) Rs. 1,000 for Mrs. Shah") == "Amount (₹) ₹ 1,000 for Mrs. Shah"
    t = text(doc())
    assert "₹" in t and "Rs." not in t and "Plywood 18mm" in t and "મ" in t and "श" in t       # Gujarati + Devanagari letters really in the PDF


def test_builtin_fallback_keeps_rs_and_latin_only(fonts):
    f = fonts(PDF_FONT_PATH="", PDF_FONTS="builtin")
    assert not f["unicode"] and f["regular"] == "Helvetica" and pdf_fonts.currency() == "Rs."
    t = text(doc())
    assert "Amount (Rs.)" in t and "₹" not in t and "Plywood 18mm" in t                                 # Gujarati becomes '?' instead of crashing


def test_bad_font_path_is_reported_not_fatal(fonts, tmp_path):
    bad = tmp_path / "x.ttf"; bad.write_bytes(b"not a font")
    f = fonts(PDF_FONT_PATH=str(bad))
    assert f["regular"] == "Helvetica" and "not a usable" in f["why"]
    f = fonts(PDF_FONT_PATH=str(tmp_path / "missing.ttf"))
    assert "does not exist" in f["why"]
    assert text(doc())


def test_system_page_reports_the_pdf_font(fonts):
    fonts(PDF_FONT_PATH="", PDF_FONTS="auto")
    with TestClient(app) as c:
        h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
        s = c.get("/api/admin/system", headers=h)
        if s.status_code == 404: s = c.get("/api/settings/system", headers=h)
        pf = s.json()["pdf_fonts"]
        assert set(pf) >= {"rupee", "gujarati", "hindi", "shaping", "why"}
