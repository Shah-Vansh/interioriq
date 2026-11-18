"""Project lifecycle + timeline. Every operational action writes an append-only ProjectEvent; advance() moves the project status FORWARD only."""
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import models as m


def now(): return m._now()


def event(db: Session, project_id: str, kind: str, text: str, user: dict | None, ref_type: str | None = None, ref_id: str | None = None):
    db.add(m.ProjectEvent(project_id=project_id, kind=kind, text=text, ref_type=ref_type, ref_id=ref_id,
                          user_id=(user or {}).get("sub"), user_name=(user or {}).get("name")))


def stage_index(status: str | None) -> int:
    try: return m.PROJECT_STAGES.index(status or "LEAD")
    except ValueError: return 0


def advance(db: Session, project: m.Project, to: str, user: dict | None, why: str):
    """Move forward to `to` if the project is behind it; never backwards. Logs the change."""
    if stage_index(to) > stage_index(project.status):
        old = project.status or "LEAD"; project.status = to
        project.progress = round(100 * stage_index(to) / (len(m.PROJECT_STAGES) - 1))
        if to == "COMPLETED": project.completed_at = now()
        event(db, project.id, "STATUS", f"Status {old} → {to}: {why}", user)


def next_number(db: Session, model, column, prefix: str, width: int = 2) -> str:
    """PREFIX-01, PREFIX-02 … per project prefix (max+1, so a cancelled document never frees its number)."""
    rows = [r[0] for r in db.query(column).filter(column.like(prefix + "-%"))]
    nums = [int(x.rsplit("-", 1)[1]) for x in rows if x.rsplit("-", 1)[1].isdigit()]
    return f"{prefix}-{(max(nums) + 1 if nums else 1):0{width}d}"


def project_of_boq(db: Session, boq: m.Boq) -> m.Project:
    return db.get(m.Project, db.get(m.Room, boq.room_id).project_id)


def boq_status(b: m.Boq) -> str: return b.status or "DRAFT"


def quote_no(project_number: str, b: m.Boq) -> str:
    """QT-<project>-NN, numbered across the whole project (two rooms never share a number)."""
    return f"QT-{project_number}-{(b.quote_seq or b.version):02d}"


def next_quote_seq(db: Session, project_id: str) -> int:
    rooms = [r.id for r in db.query(m.Room.id).filter_by(project_id=project_id)]
    return (db.query(func.max(m.Boq.quote_seq)).filter(m.Boq.room_id.in_(rooms)).scalar() or 0) + 1


def backfill_quote_seq(db: Session):
    """BOQs saved before quote_seq existed get numbers in creation order per project (single-room projects keep their old numbers)."""
    for p in db.query(m.Project):
        rooms = [r.id for r in db.query(m.Room.id).filter_by(project_id=p.id)]
        if not rooms: continue
        boqs = db.query(m.Boq).filter(m.Boq.room_id.in_(rooms)).order_by(m.Boq.created_at).all()
        n = max([b.quote_seq or 0 for b in boqs] + [0])
        for b in boqs:
            if b.quote_seq is None: n += 1; b.quote_seq = n
