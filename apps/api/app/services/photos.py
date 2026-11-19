"""M28 Catalogue item photos — stored under STORAGE_PATH/catalogue (so backups include them), never trusted by name or MIME:
the bytes must open as a JPEG / PNG / WebP image (Pillow), at most 10 MB and 40 megapixels. Each upload is re-encoded to two JPEGs —
a 1200 px 'full' and a 240 px 'thumb' — with EXIF stripped and rotation applied; the stored name is server-generated (<item id>-<hash>)."""
import hashlib
import io
from pathlib import Path

from app.core.config import settings

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000
FULL, THUMB = 1200, 240
FORMATS = {"JPEG", "PNG", "WEBP"}


class PhotoError(Exception):
    def __init__(self, status: int, detail: str): self.status, self.detail = status, detail


def root() -> Path:
    r = (Path(settings.STORAGE_PATH) / "catalogue").resolve(); r.mkdir(parents=True, exist_ok=True); return r


def _encode(img, size: int) -> bytes:
    from PIL import Image
    im = img.copy(); im.thumbnail((size, size), Image.LANCZOS)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA"); bg = Image.new("RGB", im.size, (255, 255, 255)); bg.paste(im, mask=im.split()[-1]); im = bg
    elif im.mode != "RGB": im = im.convert("RGB")
    out = io.BytesIO(); im.save(out, "JPEG", quality=85, optimize=True); return out.getvalue()


def save(item_id: str, data: bytes) -> str:
    """Validate + store; returns the stored base name (without -full/-thumb). Raises PhotoError(4xx) for bad input."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    if not data: raise PhotoError(422, "The file is empty")
    if len(data) > MAX_BYTES: raise PhotoError(413, "The photo is larger than 10 MB")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        probe = Image.open(io.BytesIO(data)); fmt = probe.format; probe.verify()
        if fmt not in FORMATS: raise PhotoError(415, "Upload a JPG, PNG or WebP photo")
        img = Image.open(io.BytesIO(data)); img.load()
    except PhotoError: raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise PhotoError(415, "That file is not a readable JPG, PNG or WebP photo")
    if img.width * img.height > MAX_PIXELS: raise PhotoError(413, "The photo has too many pixels (max 40 megapixels)")
    img = ImageOps.exif_transpose(img)
    name = f"{item_id}-{hashlib.sha256(data).hexdigest()[:12]}"
    r = root(); (r / f"{name}-full.jpg").write_bytes(_encode(img, FULL)); (r / f"{name}-thumb.jpg").write_bytes(_encode(img, THUMB))
    return name


def path(name: str | None, size: str = "thumb") -> Path | None:
    if not name: return None
    p = (root() / f"{name}-{'full' if size == 'full' else 'thumb'}.jpg").resolve()
    if p.parent != root() or not p.exists(): return None          # never leave the catalogue folder
    return p


def remove(name: str | None):
    if not name: return
    for s in ("full", "thumb"):
        p = path(name, s)
        if p: p.unlink(missing_ok=True)
