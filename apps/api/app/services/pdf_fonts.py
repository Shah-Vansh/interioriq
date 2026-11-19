"""M27 PDF fonts: the rupee sign and Gujarati / Hindi text in every PDF (quotation, invoice, PO, challan, handover) — zero cost, nothing bundled.

Which font: PDF_FONT_PATH (+ optional PDF_FONT_BOLD_PATH) if set; otherwise (PDF_FONTS=auto, the default) a font already installed on the
machine that has the rupee sign AND Gujarati AND Devanagari glyphs — Windows: Nirmala UI (ships with Windows 10/11); Linux: GNU FreeSans
(`apt install fonts-freefont-ttf`). If none is found (or PDF_FONTS=builtin) PDFs fall back to Helvetica: Latin text only and 'Rs.'.
Indian scripts need SHAPING (conjuncts, vowel signs before the consonant, …): ReportLab does it with the free `uharfbuzz` package; without
it Latin text and the rupee sign still print correctly but Gujarati/Hindi letters may join wrongly — Settings → System says which."""
import logging
import os
import re
import sys
from functools import lru_cache

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.core.config import settings

log = logging.getLogger("interioriq.pdf")
RUPEE, GUJ, DEV = 0x20B9, 0x0A95, 0x0915          # ₹, ક, क
CANDIDATES = [  # (regular, bold) — first one that covers ₹ + Gujarati + Devanagari wins
    (r"C:\Windows\Fonts\Nirmala.ttf", r"C:\Windows\Fonts\NirmalaB.ttf"),
    ("/usr/share/fonts/truetype/freefont/FreeSans.ttf", "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
    ("/usr/share/fonts/gnu-free/FreeSans.otf", "/usr/share/fonts/gnu-free/FreeSansBold.otf"),
    ("/usr/share/fonts/TTF/FreeSans.ttf", "/usr/share/fonts/TTF/FreeSansBold.ttf"),
    ("/Library/Fonts/FreeSans.ttf", "/Library/Fonts/FreeSansBold.ttf"),
]
RS = re.compile(r"\bRs\.(?=\s|\)|$)")


def _shaping_available() -> bool:
    try:
        import uharfbuzz  # noqa: F401
        return True
    except Exception:
        return False


def _covers(font: TTFont) -> dict:
    cmap = getattr(font.face, "charToGlyph", {}) or {}
    return {"rupee": RUPEE in cmap, "gujarati": GUJ in cmap, "hindi": DEV in cmap}


def _load(reg: str, bold: str | None) -> tuple[TTFont, TTFont] | None:
    try:
        r = TTFont("IQSans", reg)
        b = TTFont("IQSans-Bold", bold) if bold and os.path.exists(bold) else TTFont("IQSans-Bold", reg)
        return r, b
    except Exception as e:
        log.warning("PDF font %s could not be loaded: %s", reg, e); return None


@lru_cache(maxsize=1)
def get() -> dict:
    """{'regular', 'bold', 'unicode', 'rupee', 'gujarati', 'hindi', 'shaping', 'file', 'why'} — decided once per process."""
    builtin = {"regular": "Helvetica", "bold": "Helvetica-Bold", "unicode": False, "rupee": False, "gujarati": False, "hindi": False, "shaping": False, "file": None}
    if settings.PDF_FONT_PATH:
        if not os.path.exists(settings.PDF_FONT_PATH): return {**builtin, "why": f"PDF_FONT_PATH {settings.PDF_FONT_PATH} does not exist — using Helvetica"}
        pair = _load(settings.PDF_FONT_PATH, settings.PDF_FONT_BOLD_PATH or None)
        if not pair: return {**builtin, "why": f"PDF_FONT_PATH {settings.PDF_FONT_PATH} is not a usable TrueType font — using Helvetica"}
        chosen, why = (settings.PDF_FONT_PATH, pair), "set by PDF_FONT_PATH"
    elif (settings.PDF_FONTS or "auto").lower() == "builtin":
        return {**builtin, "why": "PDF_FONTS=builtin"}
    else:
        chosen = None
        for reg, bold in CANDIDATES:
            if not os.path.exists(reg): continue
            pair = _load(reg, bold)
            if pair and all(_covers(pair[0]).values()): chosen = (reg, pair); break
        if not chosen:
            hint = "Windows has Nirmala UI built in" if sys.platform.startswith("win") else "install it with: apt install fonts-freefont-ttf"
            return {**builtin, "why": f"no installed font with the rupee sign + Gujarati + Hindi was found ({hint}) — using Helvetica"}
        why = "found on this computer"
    path, (r, b) = chosen
    pdfmetrics.registerFont(r); pdfmetrics.registerFont(b)
    cov = _covers(r); shaping = _shaping_available() and (cov["gujarati"] or cov["hindi"])
    return {"regular": "IQSans", "bold": "IQSans-Bold", "unicode": True, **cov, "shaping": shaping, "file": path,
            "why": why + ("" if shaping or not (cov["gujarati"] or cov["hindi"]) else " — install 'uharfbuzz' (pip) so Gujarati/Hindi letters join correctly")}


def currency() -> str: return "₹" if get()["rupee"] else "Rs."


def clean(x) -> str:
    """Text as the chosen font can print it: Latin-1 only with Helvetica; 'Rs.' → '₹' when the font has the sign."""
    x = "" if x is None else str(x)
    f = get()
    if not f["unicode"]: return x.encode("cp1252", "replace").decode("cp1252")
    return RS.sub("₹", x) if f["rupee"] else x


def status() -> dict:
    f = get(); return {k: f[k] for k in ("unicode", "rupee", "gujarati", "hindi", "shaping", "file", "why")} | {"font": f["regular"]}
