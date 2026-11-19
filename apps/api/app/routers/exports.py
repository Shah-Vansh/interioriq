"""M34 Accounting export: Tally XML + day-book CSV for a date range, and the ledger-name settings. Money people only."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.services import tally

router = APIRouter(tags=["Accounting export"])
WHO = ("ADMIN", "PROJECT_MANAGER")


def _kinds(kinds: str | None):
    ks = tuple(k.strip().lower() for k in (kinds or ",".join(tally.KINDS)).split(",") if k.strip())
    bad = [k for k in ks if k not in tally.KINDS]
    if bad or not ks: raise HTTPException(422, f"kinds must be some of: {', '.join(tally.KINDS)}")
    return ks


@router.get("/settings/tally")
def get_settings(db: Session = Depends(get_db), user: dict = Depends(require_roles(*WHO))):
    return {"values": tally.settings_of(db), "labels": tally.LABELS, "kinds": list(tally.KINDS)}


@router.put("/settings/tally")
def put_settings(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("ADMIN"))):
    try: tally.save(db, body, user.get("name"))
    except tally.ExportError as e: raise HTTPException(422, str(e))
    return {"values": tally.settings_of(db), "labels": tally.LABELS, "kinds": list(tally.KINDS)}


@router.get("/exports/summary")
def summary(date_from: date, date_to: date, kinds: str | None = None, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WHO))):
    try: vs = tally.vouchers(db, date_from, date_to, _kinds(kinds))
    except tally.ExportError as e: raise HTTPException(422, str(e))
    count: dict = {}
    for v in vs: count[v["type"]] = count.get(v["type"], 0) + 1
    return {"vouchers": len(vs), "by_type": count, "parties": len({v["party"] for v in vs})}


@router.get("/exports/tally.xml")
def tally_xml(date_from: date, date_to: date, kinds: str | None = None, masters: bool = True, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WHO))):
    try: body, n = tally.tally_xml(db, date_from, date_to, _kinds(kinds), masters)
    except tally.ExportError as e: raise HTTPException(422, str(e))
    return Response(body, media_type="application/xml", headers={"Content-Disposition": f'attachment; filename="tally-{date_from}-to-{date_to}.xml"', "X-Voucher-Count": str(n)})


@router.get("/exports/daybook.csv")
def daybook(date_from: date, date_to: date, kinds: str | None = None, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WHO))):
    try: body, n = tally.daybook_csv(db, date_from, date_to, _kinds(kinds))
    except tally.ExportError as e: raise HTTPException(422, str(e))
    return Response(body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="daybook-{date_from}-to-{date_to}.csv"', "X-Voucher-Count": str(n)})
