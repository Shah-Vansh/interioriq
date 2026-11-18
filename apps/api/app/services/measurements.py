from sqlalchemy.orm import Session
from app.models import models as m
from app.services.room_model import apply_measurement

_CANON = {"length": "Length", "width": "Width", "ceiling height": "Ceiling Height", "ceiling": "Ceiling Height", "height": "Ceiling Height"}

def canonical_label(label: str) -> str:
    """'length ' / 'LENGTH' must not become a second row next to 'Length'."""
    t = " ".join(label.split())
    return _CANON.get(t.lower(), t)

def upsert_measurement(db: Session, room_id: str, label: str, value: float, unit: str, source: str, confidence: float):
    """Single write path for measurements. Returns (record, applied). Source-priority rules decide; nothing else may bypass them."""
    label = canonical_label(label)
    row = db.query(m.Measurement).filter_by(room_id=room_id, label=label).first()
    existing = None if row is None else {"source": row.source, "verified": row.verified, "value": row.value,
                                          "label": row.label, "unit": row.unit, "confidence": row.confidence}
    rec, applied = apply_measurement(existing, label, value, unit, source, confidence, verified=(source == "USER_VERIFIED"))
    if applied:
        if row is None: row = m.Measurement(room_id=room_id); db.add(row)
        for k, v in rec.items(): setattr(row, k, v)
        db.commit()
    return rec, applied
