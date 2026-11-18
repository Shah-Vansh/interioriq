"""Turn OCR text lines into *candidate* measurements. Pure logic — no I/O.

Candidates are proposals only. Nothing here writes to the Room Model; a person reviews them first,
and the source-priority rules still protect verified values when they are applied.
"""
import re
from dataclasses import asdict, dataclass

MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "ft": 304.8}
MIN_MM, MAX_MM = 100.0, 30000.0

NUM = r"(\d{1,5}(?:\.\d{1,3})?)"
UNIT = r"(mm|cm|m|ft)"
PAIR = re.compile(rf"(?<![\d.]){NUM}\s*{UNIT}?\s*x\s*{NUM}\s*{UNIT}?(?![\d.])")
FT_IN = re.compile(r"(?<!\d)(\d{1,3})\s*'\s*(?:-?\s*(\d{1,2}(?:\.\d+)?)\s*(?:\"|in\b|''))?")
SINGLE = re.compile(rf"(?<![\d.]){NUM}\s*{UNIT}\b")
BARE = re.compile(r"(?<![\d.])(\d{3,5})(?![\d.])")

LABEL_RULES = [   # first match wins; door/window must beat "height"
    ("door", re.compile(r"\bdoor\b|\bdr\b")), ("window", re.compile(r"\bwindow\b|\bwin\b|\bw\d+\b")),
    ("ceiling", re.compile(r"\bceiling\b|\bclg\b|\bheight\b|\bht\b")),
    ("length", re.compile(r"\blength\b|\blen\b|\bl\s*[:=]")), ("width", re.compile(r"\bwidth\b|\bbreadth\b|\bwid\b|\bw\s*[:=]")),
]


@dataclass
class Candidate:
    label: str | None
    value_mm: float
    raw: str
    confidence: float          # 0-100, already discounted for how the value was read
    note: str | None = None
    page: int = 0
    bbox: list | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _normalise(text: str) -> str:
    t = text.lower().replace("×", "x").replace("✕", "x").replace("*", "x")
    t = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", t)        # 4,250 -> 4250
    t = re.sub(r"(?<=\d),(?=\d{1,2}(?!\d))", ".", t)      # 4,25 -> 4.25
    return t


def _kind(t: str) -> str | None:
    return next((k for k, rx in LABEL_RULES if rx.search(t)), None)


def _to_mm(v: float, unit: str) -> float: return round(v * MM[unit], 1)


def _mask(t: str, span: tuple[int, int]) -> str: return t[:span[0]] + " " * (span[1] - span[0]) + t[span[1]:]


def _finish(c: Candidate) -> Candidate | None:
    if not (MIN_MM <= c.value_mm <= MAX_MM): return None
    if c.label == "Ceiling Height" and not (2000 <= c.value_mm <= 6000):
        c.note = ((c.note + "; ") if c.note else "") + "Unusual ceiling height — verify"; c.confidence *= 0.7
    if c.label in ("Length", "Width") and c.value_mm < 500:
        c.note = ((c.note + "; ") if c.note else "") + "Unusually small — verify"; c.confidence *= 0.7
    c.confidence = round(min(c.confidence, 100.0), 1)
    return c


def parse_line(text: str, ocr_conf: float) -> list[Candidate]:
    t = _normalise(text); kind = _kind(t); out: list[Candidate] = []

    # 1) pairs: "3200 x 2400", "900x2100", "3.2m x 2.4m", "14' x 12'"
    for m in list(PAIR.finditer(t)):
        a, ua, b, ub = float(m.group(1)), m.group(2), float(m.group(3)), m.group(4)
        unit = ua or ub; note = None; f = 1.0
        if not unit:
            if a < 60 and b < 60:
                unit = "ft" if (a.is_integer() and b.is_integer()) else "m"
                note = f"No unit shown — assumed {'feet' if unit == 'ft' else 'metres'}; verify"; f = 0.6
            else: unit = "mm"; note = "No unit shown — assumed mm"; f = 0.8
        va, vb = _to_mm(a, unit), _to_mm(b, unit)
        if kind in ("door", "window"):
            names = (f"{kind.title()} Width", f"{kind.title()} Height")
        else:
            (va, vb) = (va, vb) if va >= vb else (vb, va)
            names = ("Length", "Width"); note = (note + "; " if note else "") + "Larger side taken as Length"; f *= 0.9
        for name, v in zip(names, (va, vb)):
            c = _finish(Candidate(name, v, m.group(0).strip(), ocr_conf * f, note))
            if c: out.append(c)
        t = _mask(t, m.span())

    # 2) feet-inches: 14'-0", 12'6", 14'
    for m in list(FT_IN.finditer(t)):
        mm = (int(m.group(1)) * 12 + float(m.group(2) or 0)) * 25.4
        label = {"ceiling": "Ceiling Height", "length": "Length", "width": "Width"}.get(kind)
        c = _finish(Candidate(label, round(mm, 1), m.group(0).strip(), ocr_conf * 0.95, "Converted from feet-inches"))
        if c: out.append(c)
        t = _mask(t, m.span())

    # 3) number + unit: "2750 mm", "4.25m"
    for m in list(SINGLE.finditer(t)):
        label = {"ceiling": "Ceiling Height", "length": "Length", "width": "Width"}.get(kind)
        note = "Door/window: say which dimension this is" if kind in ("door", "window") else None
        c = _finish(Candidate(label, _to_mm(float(m.group(1)), m.group(2)), m.group(0).strip(), ocr_conf, note))
        if c: out.append(c)
        t = _mask(t, m.span())

    # 4) bare numbers: only plausible room-scale values, always low confidence
    for m in BARE.finditer(t):
        v = float(m.group(1))
        if not (500 <= v <= 20000): continue
        label = {"ceiling": "Ceiling Height", "length": "Length", "width": "Width"}.get(kind)
        c = _finish(Candidate(label, v, m.group(0), ocr_conf * 0.55, "No unit shown — assumed mm"))
        if c: out.append(c)
    return out


def extract_candidates(blocks) -> list[Candidate]:
    """blocks: objects with .text .confidence .bbox .page. Deduplicates and orders (labelled, then most confident, first)."""
    best: dict[tuple, Candidate] = {}
    for b in blocks:
        for c in parse_line(b.text, b.confidence):
            c.page, c.bbox = b.page, b.bbox
            key = (c.label, round(c.value_mm))
            if key not in best or c.confidence > best[key].confidence: best[key] = c
    return sorted(best.values(), key=lambda c: (c.label is None, -c.confidence))
