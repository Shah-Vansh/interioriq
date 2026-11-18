"""OCR engines behind one interface. Order: PaddleOCR -> RapidOCR (PaddleOCR models via ONNX) -> Tesseract.
Every engine returns LINE-level blocks with confidence on a 0-100 scale, so the parser never cares which engine ran."""
import importlib.util
import logging
import threading
from dataclasses import dataclass

from PIL import Image

from app.core.config import settings

log = logging.getLogger("ocr")
MAX_SIDE_PX = 4000
MAX_PAGES = 10


@dataclass
class Block:
    text: str
    confidence: float          # 0-100
    bbox: list                 # [x1, y1, x2, y2] in source-image pixels
    page: int = 0


class OCRUnavailable(Exception):
    pass


def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


class RapidOCRProvider:
    name = "rapidocr"; _engine = None; _lock = threading.Lock()
    def available(self): return _has("rapidocr_onnxruntime")
    def read(self, img: Image.Image) -> list[Block]:
        import numpy as np
        with self._lock:
            if type(self)._engine is None:
                from rapidocr_onnxruntime import RapidOCR
                type(self)._engine = RapidOCR()
            res, _ = type(self)._engine(np.array(img.convert("RGB")))
        out = []
        for box, text, conf in res or []:
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            out.append(Block(text.strip(), float(conf) * 100, [min(xs), min(ys), max(xs), max(ys)]))
        return [b for b in out if b.text]


class PaddleOCRProvider:
    name = "paddleocr"; _engine = None; _lock = threading.Lock()
    def available(self): return _has("paddleocr")
    def read(self, img: Image.Image) -> list[Block]:
        import numpy as np
        with self._lock:
            if type(self)._engine is None:
                from paddleocr import PaddleOCR
                type(self)._engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
            res = type(self)._engine.ocr(np.array(img.convert("RGB")), cls=True)
        out = []
        for line in (res[0] if res and res[0] else []):
            box, (text, conf) = line
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            out.append(Block(text.strip(), float(conf) * 100, [min(xs), min(ys), max(xs), max(ys)]))
        return [b for b in out if b.text]


class TesseractProvider:
    name = "tesseract"
    def available(self):
        if not _has("pytesseract"): return False
        import shutil; return shutil.which("tesseract") is not None
    def read(self, img: Image.Image) -> list[Block]:
        import pytesseract
        d = pytesseract.image_to_data(img.convert("RGB"), output_type=pytesseract.Output.DICT, config="--psm 11")   # sparse text suits plans
        lines: dict[tuple, list] = {}
        for i, w in enumerate(d["text"]):
            if w.strip() and float(d["conf"][i]) >= 0:
                lines.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(i)
        out = []
        for idx in lines.values():                              # words -> lines, so "4250" + "mm" read as "4250 mm"
            idx.sort(key=lambda i: d["left"][i])
            x1 = min(d["left"][i] for i in idx); y1 = min(d["top"][i] for i in idx)
            x2 = max(d["left"][i] + d["width"][i] for i in idx); y2 = max(d["top"][i] + d["height"][i] for i in idx)
            conf = sum(float(d["conf"][i]) for i in idx) / len(idx)
            out.append(Block(" ".join(d["text"][i].strip() for i in idx), conf, [x1, y1, x2, y2]))
        return out


ALL = [PaddleOCRProvider(), RapidOCRProvider(), TesseractProvider()]


def get_providers() -> list:
    wanted = settings.OCR_PROVIDER.lower()
    avail = [p for p in ALL if p.available()]
    return avail if wanted == "auto" else [p for p in avail if p.name == wanted]


def _prepare(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    if max(img.size) > MAX_SIDE_PX: img.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    return img


def load_pages(path: str, kind: str) -> list[Image.Image]:
    """Rasterise a file into at most MAX_PAGES page images."""
    Image.MAX_IMAGE_PIXELS = 60_000_000                         # refuse decompression bombs
    if kind == "pdf":
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(path); pages = []
        for i in range(min(len(pdf), MAX_PAGES)):
            page = pdf[i]; w, h = page.get_size()
            pages.append(page.render(scale=min(2.5, MAX_SIDE_PX / max(w, h))).to_pil())
        return pages
    from PIL import ImageSequence
    with Image.open(path) as im:
        return [_prepare(f.copy()) for _, f in zip(range(MAX_PAGES), ImageSequence.Iterator(im))]


def _pdf_text_layer(path: str) -> list[Block]:
    """CAD-exported PDFs carry their text exactly; prefer it over recognising pixels."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path); out = []
    for i in range(min(len(pdf), MAX_PAGES)):
        txt = pdf[i].get_textpage().get_text_range()
        out += [Block(line.strip(), 99.0, [0, 0, 0, 0], i) for line in txt.replace("\r", "\n").split("\n") if line.strip()]
    return out


def extract(path: str, kind: str) -> tuple[list[Block], str, int]:
    """Returns (blocks, provider name, page count). Raises OCRUnavailable when nothing can read the file."""
    if kind == "pdf":
        layer = _pdf_text_layer(path)
        if sum(len(b.text) for b in layer) >= 30:
            return layer, "pdf-text-layer", len({b.page for b in layer})
    providers = get_providers()
    if not providers:
        raise OCRUnavailable("No OCR engine is installed. Run: pip install rapidocr-onnxruntime   (or install Tesseract + pytesseract)")
    pages = load_pages(path, kind); last = None
    for prov in providers:
        try:
            blocks = []
            for n, img in enumerate(pages):
                for b in prov.read(_prepare(img)): b.page = n; blocks.append(b)
            return blocks, prov.name, len(pages)
        except Exception as e:                                   # fall back to the next engine
            log.warning("OCR engine %s failed: %s", prov.name, e); last = e
    raise OCRUnavailable(f"Every OCR engine failed (last error: {type(last).__name__}).")
