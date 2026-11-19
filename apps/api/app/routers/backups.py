"""M24 Settings → Backups (admins only): list, create, download, verify, upload, restore, delete."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_roles
from app.models import models as m
from app.services import backup as bk

router = APIRouter(tags=["Backups"])
ADMINS = ("ADMIN",)                     # SUPER_ADMIN always passes require_roles
MAX_UPLOAD = 2 * 1024 ** 3


def _fail(e: bk.BackupError): raise HTTPException(e.status, e.message)


@router.get("/backups")
def list_backups(db: Session = Depends(get_db), user: dict = Depends(require_roles(*ADMINS))):
    last = db.get(m.JobLock, "auto_backup")
    return {"backups": bk.list_backups(), "dir": str(bk.backup_dir()), "database": db.get_bind().dialect.name,
            "daily": {"enabled": settings.BACKUP_DAILY, "after_hour": settings.BACKUP_HOUR, "keep": settings.BACKUP_KEEP, "last_day": last.value if last else None}}


class CreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_files: bool = True


@router.post("/backups", status_code=201)
def create(b: CreateIn = CreateIn(), user: dict = Depends(require_roles(*ADMINS))):
    try: return bk.create(kind="manual", include_files=b.include_files, by=user.get("name"))
    except bk.BackupError as e: _fail(e)


@router.get("/backups/{name}/download")
def download(name: str, user: dict = Depends(require_roles(*ADMINS))):
    try: p = bk.path_of(name)
    except bk.BackupError as e: _fail(e)
    return FileResponse(p, media_type="application/zip", filename=name, headers={"X-Content-Type-Options": "nosniff"})


@router.post("/backups/{name}/verify")
def verify(name: str, user: dict = Depends(require_roles(*ADMINS))):
    try: return bk.verify(bk.path_of(name))
    except bk.BackupError as e: _fail(e)


@router.post("/backups/upload", status_code=201)
async def upload(file: UploadFile = File(...), user: dict = Depends(require_roles(*ADMINS))):
    name = bk.unique_name("uploaded"); dest = bk.backup_dir() / name; size = 0
    with open(dest, "xb") as f:                                            # never overwrite an existing backup
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD: f.close(); dest.unlink(missing_ok=True); raise HTTPException(413, "Backup is larger than 2 GB")
            f.write(chunk)
    try: return bk.verify(dest)
    except bk.BackupError as e: dest.unlink(missing_ok=True); _fail(e)


class RestoreIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str
    restore_files: bool = True


@router.post("/backups/{name}/restore")
def restore(name: str, b: RestoreIn, user: dict = Depends(require_roles(*ADMINS))):
    if b.confirm != "RESTORE": raise HTTPException(422, "Type RESTORE to confirm — this replaces all current data")
    try: return bk.restore(bk.path_of(name), restore_files=b.restore_files, by=user.get("name"))
    except bk.BackupError as e: _fail(e)


class DeleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str


@router.post("/backups/{name}/delete")
def delete(name: str, b: DeleteIn, user: dict = Depends(require_roles(*ADMINS))):
    if b.confirm != name: raise HTTPException(422, "Type the backup's file name to confirm deleting it")
    try: bk.path_of(name).unlink()
    except bk.BackupError as e: _fail(e)
    return {"deleted": name}
