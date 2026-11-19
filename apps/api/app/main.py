import logging
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import SessionLocal, upgrade_schema
from app.core.security import hash_password
from app.models import models as m
from app.routers.api import router
from app.routers.documents import router as documents_router
from app.routers.estimation import router as estimation_router
from app.routers.crm import router as crm_router
from app.routers.catalogue import router as catalogue_router
from app.routers.operations import router as operations_router
from app.routers.insights import router as insights_router
from app.routers.admin import router as admin_router
from app.routers.portal import router as portal_router
from app.routers.drawings import router as drawings_router
from app.routers.invoices import router as invoices_router
from app.routers.notifications import router as notifications_router
from app.routers.profit import router as profit_router
from app.routers.payables import router as payables_router
from app.routers.takeoff import router as takeoff_router
from app.routers.openings import router as openings_router
from app.services.phone import PhoneError, normalize_phone

log = logging.getLogger("interioriq")

SEED_USERS = [("admin@interioriq.com", "Admin User", "SUPER_ADMIN"), ("priya@interioriq.com", "Priya Mehta", "PROJECT_MANAGER"),
              ("kiran@interioriq.com", "Kiran Shah", "INTERIOR_DESIGNER"), ("amit@interioriq.com", "Amit Rathod", "SITE_ENGINEER")]
# sku, name, category, L, W, H, price, stock[, style tags[, mounting height]]   — dev seed for an EMPTY catalogue only
SEED_FURNITURE = [
    ("BED-KNG-WLT-001", "King Bed — Walnut", "Bed", 1930, 2030, 1200, 124000, 3, "modern, luxury"),
    ("WAR-SLD-WLT-001", "6-Door Wardrobe", "Wardrobe", 2700, 600, 2200, 185000, 2, "modern, luxury"),
    ("DSK-STD-WLT-001", "Study Desk", "Study", 1200, 600, 760, 28000, 7, "modern"),
    # living / dining / kitchen / study (M21: the generator lays out every common room type from these categories)
    ("SOF-3S-GRY-001", "3-Seater Sofa — Grey Linen", "Sofa", 2100, 900, 850, 78000, 4, "modern, scandinavian"),
    ("SOF-2S-GRY-001", "2-Seater Sofa — Grey Linen", "Sofa", 1500, 850, 850, 54000, 4, "modern, scandinavian"),
    ("TVU-WLT-001", "TV Unit — Walnut", "TV Unit", 1800, 450, 550, 42000, 3, "modern"),
    ("CTB-OAK-001", "Coffee Table — Oak", "Coffee Table", 1100, 600, 420, 16500, 5, "scandinavian, minimal"),
    ("ARM-TEAL-001", "Accent Armchair — Teal", "Armchair", 800, 800, 850, 26000, 4, "modern"),
    ("DTB-6S-WLT-001", "6-Seater Dining Table — Walnut", "Dining Table", 1800, 900, 750, 68000, 3, "modern"),
    ("DTB-4S-WLT-001", "4-Seater Dining Table — Walnut", "Dining Table", 1200, 800, 750, 46000, 3, "modern"),
    ("DCH-WLT-001", "Dining Chair — Walnut", "Dining Chair", 450, 500, 900, 7500, 24, "modern"),
    ("CRK-WLT-001", "Crockery Unit — Walnut", "Crockery", 1200, 450, 1800, 52000, 2, "modern"),
    ("KBU-600-001", "Kitchen Base Unit 600", "Kitchen", 600, 600, 850, 18000, 20),
    ("KBU-900-001", "Kitchen Base Unit 900", "Kitchen", 900, 600, 850, 24000, 12),
    ("KTU-600-001", "Kitchen Tall Unit 600 (fridge / pantry)", "Kitchen", 600, 600, 2100, 38000, 4),
    ("BKS-WLT-001", "Bookshelf — Walnut", "Bookshelf", 900, 350, 1800, 22000, 4, "modern"),
    ("OCH-BLK-001", "Ergonomic Office Chair", "Office Chair", 600, 600, 1050, 14500, 6, "modern, industrial"),
    # M21b: kitchen fittings (sink / hob units, wall cabinets fixed at 1450 mm, filler panels cut to the gap) + styled / cheaper alternatives
    ("KSU-900-001", "Kitchen Sink Unit 900", "Kitchen Sink", 900, 600, 850, 32000, 6),
    ("KSU-600-001", "Kitchen Sink Unit 600", "Kitchen Sink", 600, 600, 850, 26000, 6),
    ("KHU-900-001", "Kitchen Hob Unit 900", "Kitchen Hob", 900, 600, 850, 28000, 6),
    ("KHU-600-001", "Kitchen Hob Unit 600", "Kitchen Hob", 600, 600, 850, 22000, 6),
    ("KWU-900-001", "Kitchen Wall Cabinet 900", "Kitchen Wall", 900, 350, 700, 19000, 12, None, 1450),
    ("KWU-600-001", "Kitchen Wall Cabinet 600", "Kitchen Wall", 600, 350, 700, 14000, 16, None, 1450),
    ("KFP-001", "Kitchen Filler Panel", "Kitchen Filler", 150, 600, 850, 2500, 30),
    ("BED-QN-OAK-001", "Queen Bed — Oak", "Bed", 1630, 2030, 1000, 68000, 4, "scandinavian, minimal"),
    ("WAR-2D-OAK-001", "2-Door Wardrobe — Oak", "Wardrobe", 1200, 600, 2100, 62000, 3, "scandinavian, minimal"),
    ("SOF-3S-LTH-001", "3-Seater Leather Sofa — Tan", "Sofa", 2100, 900, 850, 145000, 2, "luxury"),
    ("TVU-OAK-001", "TV Unit — Oak", "TV Unit", 1600, 400, 500, 26000, 3, "scandinavian, minimal"),
    ("DCH-OAK-001", "Dining Chair — Oak", "Dining Chair", 450, 500, 880, 4800, 24, "scandinavian, minimal")]

def seed():
    if settings.AUTO_MIGRATE:
        added = upgrade_schema()   # alembic upgrade head; a pre-Alembic interioriq.db gains missing tables/columns in place, then is stamped
        if added: log.info("Database upgraded, added columns: %s", ", ".join(added))
    db = SessionLocal()
    try:
        for c in db.query(m.Client).filter(m.Client.phone.isnot(None), m.Client.phone_norm.is_(None)):   # clients saved before phone matching existed
            try: c.phone_norm = normalize_phone(c.phone)
            except PhoneError: pass
        if not db.query(m.User).first():
            for email, name, role in SEED_USERS:   # dev-only password: change before any real use
                db.add(m.User(email=email, full_name=name, role=role, password_hash=hash_password("ChangeMe123!")))
        # catalogue rows saved before M9 have no kind/unit/active flag: they are furniture, counted in No., and on sale
        db.query(m.FurnitureItem).filter(m.FurnitureItem.kind.is_(None)).update({"kind": "FURNITURE"}, synchronize_session=False)
        db.query(m.FurnitureItem).filter(m.FurnitureItem.unit.is_(None)).update({"unit": "No."}, synchronize_session=False)
        db.query(m.FurnitureItem).filter(m.FurnitureItem.is_active.is_(None)).update({"is_active": True}, synchronize_session=False)
        db.query(m.Supplier).filter(m.Supplier.is_active.is_(None)).update({"is_active": True}, synchronize_session=False)
        if db.query(m.Boq).filter(m.Boq.quote_seq.is_(None)).first():
            from app.services.flow import backfill_quote_seq
            backfill_quote_seq(db)
        if not db.query(m.FurnitureItem).first():
            for sku, n, c, l, w, h, p, s, *more in SEED_FURNITURE:
                style, mount = (list(more) + [None, None])[:2]
                db.add(m.FurnitureItem(sku=sku, name=n, category=c, length_mm=l, width_mm=w, height_mm=h, price=p, stock=s, kind="FURNITURE", unit="No.",
                                       is_active=True, style=style, mount_mm=mount))
        # thread backend = OCR runs inside THIS process (one server): a restart mid-read leaves a document "processing" forever, and
        # waiting ones lost their background task. With Celery the workers own that: stale reads are failed by time (app/worker.py sweep).
        waiting = []
        if not jobs.celery_on():
            db.query(m.Document).filter(m.Document.status == "PROCESSING").update(
                {"status": "FAILED", "error": "Reading was interrupted by a server restart. Click Re-read to try again."}, synchronize_session=False)
            waiting = [d.id for d in db.query(m.Document.id).filter(m.Document.status == "UPLOADED")]
        db.commit()
        for doc_id in waiting: jobs.ocr(doc_id)                           # read them now
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    seed()
    from app.services import backup as bk
    bk.start_scheduler(SessionLocal)                     # one automatic backup per local day (claimed, so once across several servers)
    if settings.NOTIFY_WORKER and not jobs.celery_on():
        from app.services.notify import start_worker
        start_worker(SessionLocal)
        from app.services import reminders
        reminders.start_scheduler(SessionLocal)      # follow-up reminders (off until switched on; claims make several servers safe)
    yield

from app.routers.team import router as team_router
from app.routers.backups import router as backups_router
from app.services import access, jobs
app = FastAPI(title="InteriorIQ API", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.ALLOWED_ORIGINS, allow_origin_regex=settings.ALLOWED_ORIGIN_REGEX, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
# M22: every route passes the project-access guard (a no-op unless 'Limit staff to their projects' is on)
for _r in (router, documents_router, estimation_router, crm_router, catalogue_router, operations_router, insights_router, admin_router, portal_router, drawings_router,
           invoices_router, notifications_router, profit_router, payables_router, takeoff_router, openings_router, team_router, backups_router):
    app.include_router(_r, prefix="/api", dependencies=[Depends(access.guard)])

@app.exception_handler(IntegrityError)
async def integrity_handler(_: Request, __: IntegrityError):
    # Safety net: a unique-constraint clash (e.g. two saves racing for the same design version) is a conflict, not a crash.
    return JSONResponse(status_code=409, content={"detail": "Conflict: a record with the same unique value already exists. Retry."})
