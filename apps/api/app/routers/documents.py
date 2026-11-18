from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models import models as m
from app.services import jobs
from app.services import documents as docs
from app.services.measurements import upsert_measurement

router = APIRouter(tags=["Documents"])
WRITE = ("ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "INTERIOR_DESIGNER")
NO_OCR = ("SITE_PHOTO", "RENDER")
READ = WRITE + ("ESTIMATOR", "PROCUREMENT_MANAGER", "INVENTORY_MANAGER", "MANUFACTURING_MANAGER", "INSTALLATION_MANAGER", "QC_MANAGER", "SALES")  # not CLIENT
MEDIA = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "tiff": "image/tiff"}


def _summary(d: m.Document) -> dict:
    o = d.ocr_json or {}
    return {"id": d.id, "project_id": d.project_id, "room_id": d.room_id, "name": d.original_name, "kind": d.kind, "size_bytes": d.size_bytes,
            "category": d.category, "status": d.status, "error": d.error, "provider": o.get("provider"),
            "candidate_count": len(o.get("candidates", [])), "created_at": d.created_at.isoformat() if d.created_at else None}


def _get(db: Session, doc_id: str) -> m.Document:
    d = db.get(m.Document, doc_id)
    if not d: raise HTTPException(404, "Document not found")
    return d


@router.post("/projects/{pid}/documents", status_code=201)
async def upload(pid: str, bg: BackgroundTasks, file: UploadFile = File(...), room_id: str | None = Form(None),
                 category: str = Form("FLOOR_PLAN"), db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    if not db.get(m.Project, pid): raise HTTPException(404, "Project not found")
    if room_id:
        room = db.get(m.Room, room_id)
        if not room or room.project_id != pid: raise HTTPException(422, "That room does not belong to this project")
    data = await file.read(docs.MAX_BYTES + 1)                       # never buffer more than the limit + 1 byte
    try:
        kind = docs.validate_content(data)
    except docs.UploadError as e:
        raise HTTPException(e.status, e.message)
    digest = docs.sha256(data)
    dup = db.query(m.Document).filter_by(project_id=pid, sha256=digest).first()
    if dup:
        return {**_summary(dup), "duplicate": True}                  # same bytes already uploaded: reuse, don't store twice
    category = (category or "FLOOR_PLAN").strip().upper()[:30]
    photo = category in NO_OCR
    if photo and kind not in ("png", "jpg"): raise HTTPException(422, "Site photos and renders must be PNG or JPG images")
    d = m.Document(project_id=pid, room_id=room_id, original_name=docs.clean_name(file.filename), kind=kind, size_bytes=len(data),
                   sha256=digest, storage_path="", category=category, uploaded_by=user["sub"], status="STORED" if photo else "UPLOADED")
    db.add(d); db.flush()
    try:
        d.storage_path = docs.store(pid, d.id, kind, data); db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "This file was just uploaded by someone else.")
    except docs.UploadError as e:
        db.rollback(); raise HTTPException(e.status, e.message)
    if not photo: jobs.ocr(d.id, bg)                                # photos/renders are just stored, never OCR'd
    return {**_summary(d), "duplicate": False}


@router.get("/projects/{pid}/documents")
def list_documents(pid: str, category: str | None = None, exclude_media: bool = False, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    """category=SITE_PHOTO / RENDER / … filters; exclude_media=true hides photos and renders (the OCR documents screen)."""
    rows = db.query(m.Document).filter_by(project_id=pid)
    if category: rows = rows.filter(m.Document.category == category.upper())
    if exclude_media: rows = rows.filter(m.Document.category.notin_(NO_OCR))
    rows = rows.order_by(m.Document.created_at.desc())
    return [_summary(d) for d in rows]


@router.get("/documents/{doc_id}")
def get_document(doc_id: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    d = _get(db, doc_id); o = d.ocr_json or {}
    return {**_summary(d), "pages": o.get("pages"), "candidates": o.get("candidates", [])}


@router.get("/documents/{doc_id}/file")
def get_file(doc_id: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    d = _get(db, doc_id)
    try: path = docs.safe_path(d.storage_path)
    except docs.UploadError: raise HTTPException(404, "File not found")
    if not path.exists(): raise HTTPException(404, "File missing from storage")
    return FileResponse(path, media_type=MEDIA[d.kind], headers={"X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"})


@router.post("/documents/{doc_id}/ocr", status_code=202)
def rerun_ocr(doc_id: str, bg: BackgroundTasks, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    d = _get(db, doc_id)
    if d.status == "PROCESSING" and not jobs.is_stale(d): raise HTTPException(409, "Already processing")
    if d.status == "STORED": raise HTTPException(409, "Photos and renders aren't read")
    d.status, d.error = "UPLOADED", None; db.commit(); jobs.ocr(d.id, bg)        # UPLOADED = waiting for a reader
    return _summary(d)


class ApplyItem(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    value_mm: float = Field(gt=0, le=50000)
    confidence: float = Field(default=0, ge=0, le=100)

class ApplyBody(BaseModel):
    room_id: str
    items: list[ApplyItem] = Field(min_length=1, max_length=50)


@router.post("/documents/{doc_id}/apply")
def apply_candidates(doc_id: str, b: ApplyBody, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    """Writes reviewed OCR values into the Room Model with source=OCR. The priority rules decide; verified values are never overwritten."""
    d = _get(db, doc_id); room = db.get(m.Room, b.room_id)
    if not room or room.project_id != d.project_id: raise HTTPException(422, "That room does not belong to this document's project")
    results = []
    for it in b.items:
        rec, applied = upsert_measurement(db, room.id, it.label, it.value_mm, "mm", "OCR", it.confidence)
        results.append({"label": rec["label"], "applied": applied, "current": rec,
                        "reason": None if applied else f"Kept existing {rec['source']} value ({rec['value']:g} {rec['unit']}) — it has equal or higher priority"})
    return {"results": results, "applied": sum(r["applied"] for r in results), "rejected": sum(not r["applied"] for r in results)}
