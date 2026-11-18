"""Upload validation, safe storage and the OCR pipeline for documents."""
import hashlib, io, logging, re, unicodedata
from dataclasses import asdict
from pathlib import Path

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import models as m
from app.services import dimensions, ocr

log = logging.getLogger("documents")
MAX_BYTES = settings.MAX_UPLOAD_MB * 1024 * 1024
MAX_PDF_PAGES = 50


class UploadError(Exception):
    def __init__(self, status: int, message: str): self.status, self.message = status, message


def sniff_kind(head: bytes) -> str | None:
    """Decide the file type from its CONTENT. The extension and the client's Content-Type are ignored."""
    if head.startswith(b"%PDF-"): return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"): return "png"
    if head.startswith(b"\xff\xd8\xff"): return "jpg"
    if head[:4] in (b"II*\x00", b"MM\x00*"): return "tiff"
    return None


def clean_name(name: str | None) -> str:
    """Display-only. Drops any path, control characters and excess length; never used to build a storage path."""
    n = (name or "document").replace("\\", "/").split("/")[-1]
    n = "".join(ch for ch in unicodedata.normalize("NFKC", n) if ch.isprintable())
    return (re.sub(r"\s+", " ", n).strip() or "document")[:120]


def validate_content(data: bytes) -> str:
    if not data: raise UploadError(422, "The file is empty.")
    if len(data) > MAX_BYTES: raise UploadError(413, f"File is larger than the {settings.MAX_UPLOAD_MB} MB limit.")
    kind = sniff_kind(data[:16])
    if kind is None:
        raise UploadError(415, "Unsupported file type. Upload a PDF, PNG, JPG or TIFF (DXF import is planned).")
    try:                                                    # reject corrupt files now, not later in the background
        if kind == "pdf":
            import pypdfium2 as pdfium
            n = len(pdfium.PdfDocument(data))
            if n == 0 or n > MAX_PDF_PAGES: raise UploadError(422, f"PDF must have between 1 and {MAX_PDF_PAGES} pages.")
        else:
            from PIL import Image
            Image.MAX_IMAGE_PIXELS = 60_000_000
            with Image.open(io.BytesIO(data)) as im: im.verify()
    except UploadError: raise
    except Exception: raise UploadError(422, "The file is corrupt or could not be read.")
    return kind


def store(project_id: str, doc_id: str, kind: str, data: bytes) -> str:
    root = (Path(settings.STORAGE_PATH) / "documents").resolve()
    folder = (root / project_id).resolve()
    if root not in folder.parents: raise UploadError(400, "Invalid project.")        # defence in depth against path tricks
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{doc_id}.{kind}"                                                # server-generated name
    path.write_bytes(data)
    return str(path)


def sha256(data: bytes) -> str: return hashlib.sha256(data).hexdigest()


def safe_path(stored: str) -> Path:
    root = (Path(settings.STORAGE_PATH) / "documents").resolve(); p = Path(stored).resolve()
    if root not in p.parents: raise UploadError(404, "File not found.")
    return p


def process_document(doc_id: str) -> None:
    """Runs in a background task with its own session. Never raises: failures become status=FAILED with a plain-English reason."""
    from app.services import flow
    db = SessionLocal()
    try:
        # claim it: only one server / worker moves it from UPLOADED (waiting) to PROCESSING; everyone else finds nothing to do
        n = db.query(m.Document).filter(m.Document.id == doc_id, m.Document.status == "UPLOADED").update(
            {"status": "PROCESSING", "error": None, "processing_started_at": flow.now()}, synchronize_session=False)
        db.commit()
        if n != 1: return
        d = db.get(m.Document, doc_id)
        try:
            blocks, provider, pages = ocr.extract(d.storage_path, d.kind)
            cands = dimensions.extract_candidates(blocks)
            d.ocr_json = {"provider": provider, "pages": pages, "block_count": len(blocks),
                          "candidates": [c.to_dict() for c in cands], "blocks": [asdict(b) for b in blocks[:1500]]}
            d.status = "OCR_DONE"
        except ocr.OCRUnavailable as e:
            d.status, d.error = "FAILED", str(e)
        except Exception:
            log.exception("OCR failed for %s", doc_id)
            d.status, d.error = "FAILED", "Could not read this file (it may be corrupt, password-protected or too large)."
        db.commit()
    finally:
        db.close()
