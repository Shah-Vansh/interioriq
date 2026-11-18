"""Settings (company profile, users, roles, system status, AI engines) and CRM contacts."""
import importlib.util
import os
import platform
import re
import shutil
import sys

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, inspect, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import engine, get_db
from app.core.security import hash_password, require_roles
from app.models import models as m
from app.routers import catalogue as r_cat, crm as r_crm, documents as r_docs, estimation as r_est, operations as r_ops
from app.services import company as companylib
from app.services.catalogue import normalize_gstin
from app.services.phone import PhoneError, normalize_phone

router = APIRouter(tags=["Settings"])
ADMINS = ("ADMIN",)                        # SUPER_ADMIN always passes require_roles
STAFF = tuple(r for r in m.ROLES if r not in ("CLIENT", "SUPER_ADMIN"))


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Company ───────────────────────────────────────────────────────────────────
@router.get("/settings/company")
def get_company(db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    vals = companylib.get(db)
    return {"values": vals, "fields": [{"key": k, "label": lbl, "type": "bool" if k in companylib.BOOL_KEYS else "int" if k in companylib.INT_KEYS else "text"} for k, (lbl, _, _) in companylib.FIELDS.items()]}


@router.put("/settings/company")
def put_company(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles(*ADMINS))):
    unknown = [k for k in body if k not in companylib.FIELDS]
    if unknown: raise HTTPException(422, f"Unknown setting(s): {', '.join(unknown)}")
    clean = {}
    for k, v in body.items():
        if k in companylib.BOOL_KEYS:
            if isinstance(v, bool): clean[k] = v
            elif str(v).strip().lower() in ("true", "1", "yes", "on"): clean[k] = True
            elif str(v).strip().lower() in ("false", "0", "no", "off", ""): clean[k] = False
            else: raise HTTPException(422, f"{companylib.FIELDS[k][0]} must be on or off")
            continue
        if k in companylib.INT_KEYS:
            lo, hi = companylib.INT_KEYS[k]
            try: iv = int(str(v).strip())
            except ValueError: raise HTTPException(422, f"{companylib.FIELDS[k][0]} must be a whole number")
            if not lo <= iv <= hi: raise HTTPException(422, f"{companylib.FIELDS[k][0]} must be between {lo} and {hi}")
            clean[k] = iv
        else:
            sv = str(v or "").strip(); mx = companylib.FIELDS[k][2]
            if mx and len(sv) > mx: raise HTTPException(422, f"{companylib.FIELDS[k][0]} is too long (max {mx})")
            if k == "name" and not sv: raise HTTPException(422, "Company name cannot be empty")
            if k == "gstin" and sv:
                try: sv = normalize_gstin(sv)
                except ValueError as e: raise HTTPException(422, f"GSTIN: {e}")
            if k == "phone" and sv:
                try: normalize_phone(sv)
                except PhoneError as e: raise HTTPException(422, f"Phone: {e}")
            if "_sku" in k and sv: sv = sv.upper()
            if k == "all_projects_roles":
                roles = [r.strip().upper() for r in sv.split(",") if r.strip()]
                bad = [r for r in roles if r not in m.ROLES or r == "CLIENT"]
                if bad: raise HTTPException(422, f"Unknown role(s): {', '.join(bad)}. Use: {', '.join(r for r in m.ROLES if r != 'CLIENT')}")
                sv = ", ".join(dict.fromkeys(roles))
            if k == "invoice_prefix":
                sv = sv.upper()
                if not re.match(r"^[A-Z0-9]{1,10}$", sv): raise HTTPException(422, "Invoice prefix: 1-10 letters or digits (e.g. INV)")
            clean[k] = sv
    for k, v in clean.items():
        row = db.get(m.CompanySetting, k)
        if row: row.value, row.updated_by = v, user.get("name")
        else: db.add(m.CompanySetting(key=k, value=v, updated_by=user.get("name")))
    db.commit(); return get_company(db, user)


# ── Users ─────────────────────────────────────────────────────────────────────
def _user_out(u: m.User, clients: dict) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active is not False, "phone": u.phone,
            "client_id": u.client_id, "client_name": clients.get(u.client_id), "created_at": u.created_at.isoformat() if u.created_at else None}


def _pw(v: str) -> str:
    if len(v) < 8 or not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v): raise ValueError("Password needs at least 8 characters with letters and digits")
    return v


class UserIn(_In):
    email: str = Field(min_length=3, max_length=160)
    full_name: str = Field(min_length=1, max_length=120)
    role: str
    password: str
    phone: str | None = None
    client_id: str | None = None

    @field_validator("email")
    @classmethod
    def _e(cls, v):
        v = v.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v): raise ValueError("Not a valid email address")
        return v

    @field_validator("role")
    @classmethod
    def _r(cls, v):
        if v not in m.ROLES: raise ValueError(f"role must be one of {', '.join(m.ROLES)}")
        return v

    @field_validator("password")
    @classmethod
    def _p(cls, v): return _pw(v)


class UserPatch(_In):
    full_name: str | None = Field(None, min_length=1, max_length=120)
    role: str | None = None
    is_active: bool | None = None
    phone: str | None = None
    client_id: str | None = None
    password: str | None = None

    @field_validator("role")
    @classmethod
    def _r(cls, v):
        if v is not None and v not in m.ROLES: raise ValueError(f"role must be one of {', '.join(m.ROLES)}")
        return v

    @field_validator("password")
    @classmethod
    def _p(cls, v): return v if v is None else _pw(v)


@router.get("/users")
def list_users(db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    clients = {c.id: c.name for c in db.query(m.Client)}
    return [_user_out(u, clients) for u in db.query(m.User).order_by(m.User.full_name)]


@router.post("/users", status_code=201)
def create_user(b: UserIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*ADMINS))):
    if b.role == "SUPER_ADMIN" and user.get("role") != "SUPER_ADMIN": raise HTTPException(403, "Only a super admin can create another super admin")
    if db.query(m.User).filter(func.lower(m.User.email) == b.email).first(): raise HTTPException(409, f"A user with email {b.email} already exists")
    if b.role == "CLIENT":
        if not b.client_id or not db.get(m.Client, b.client_id): raise HTTPException(422, "A client login must be linked to a client (pick one)")
    elif b.client_id: raise HTTPException(422, "Only CLIENT users are linked to a client")
    u = m.User(email=b.email, full_name=b.full_name.strip(), role=b.role, password_hash=hash_password(b.password), phone=b.phone, client_id=b.client_id, is_active=True)
    db.add(u); db.commit()
    return _user_out(u, {c.id: c.name for c in db.query(m.Client)})


@router.patch("/users/{uid}")
def patch_user(uid: str, b: UserPatch, db: Session = Depends(get_db), user: dict = Depends(require_roles(*ADMINS))):
    u = db.get(m.User, uid)
    if not u: raise HTTPException(404, "User not found")
    d = b.model_dump(exclude_unset=True)
    me = uid == user.get("sub")
    if me and (d.get("is_active") is False or ("role" in d and d["role"] != u.role)): raise HTTPException(409, "You can't deactivate yourself or change your own role")
    if (u.role == "SUPER_ADMIN" or d.get("role") == "SUPER_ADMIN") and user.get("role") != "SUPER_ADMIN": raise HTTPException(403, "Only a super admin can change a super admin")
    if u.role == "SUPER_ADMIN" and (d.get("is_active") is False or d.get("role", "SUPER_ADMIN") != "SUPER_ADMIN"):
        others = db.query(m.User).filter(m.User.role == "SUPER_ADMIN", m.User.is_active.isnot(False), m.User.id != uid).count()
        if not others: raise HTTPException(409, "This is the last active super admin")
    role = d.get("role", u.role); cid = d.get("client_id", u.client_id)
    if role == "CLIENT" and (not cid or not db.get(m.Client, cid)): raise HTTPException(422, "A client login must be linked to a client")
    if role != "CLIENT": d["client_id"] = None
    for k in ("full_name", "is_active", "role"):
        if k in d and d[k] is None: raise HTTPException(422, f"{k} cannot be empty")
    if "password" in d:
        u.password_hash = hash_password(d.pop("password"))
    for k, v in d.items(): setattr(u, k, v)
    db.commit()
    return _user_out(u, {c.id: c.name for c in db.query(m.Client)})


# ── Roles matrix (generated from the actual route guards, so it can't drift) ─
def _caps():
    return [
        ("CRM: leads & clients — edit", r_crm.WRITE), ("CRM: leads & clients — view", r_crm.READ),
        ("Survey documents & OCR — upload", r_docs.WRITE), ("Survey documents — view", r_docs.READ),
        ("BOQ / quotation — create", r_est.WRITE), ("BOQ / quotation — view", r_est.READ),
        ("Quotation status (send / approve / reject)", r_ops.Q_WRITE), ("Record payments", r_ops.PAY), ("Issue / cancel invoices", ("ADMIN", "PROJECT_MANAGER", "SALES")),
        ("Email / WhatsApp quotations", ("ADMIN", "PROJECT_MANAGER", "SALES", "ESTIMATOR")), ("Email / WhatsApp purchase orders", ("ADMIN", "PROJECT_MANAGER", "PROCUREMENT_MANAGER")),
        ("Notification settings & templates", ("ADMIN",)), ("See purchase costs & margins (catalogue)", ("ADMIN", "PROJECT_MANAGER", "PROCUREMENT_MANAGER", "ESTIMATOR")),
        ("Project profitability", ("ADMIN", "PROJECT_MANAGER")), ("Record project expenses", ("ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "PROCUREMENT_MANAGER")),
        ("Record supplier bills / see payables", ("ADMIN", "PROJECT_MANAGER", "PROCUREMENT_MANAGER")), ("Pay suppliers", ("ADMIN", "PROJECT_MANAGER")), ("Edit take-off rules", ("ADMIN", "PROJECT_MANAGER", "ESTIMATOR")),
        ("Catalogue items, prices, suppliers — edit", r_cat.WRITE), ("Stock in / out", r_cat.STOCK), ("Catalogue — view", r_cat.READ),
        ("Purchase orders — create / issue / cancel", r_ops.PROC), ("Receive goods against a PO", r_ops.RECEIVE),
        ("Manufacturing work orders", r_ops.MFG), ("Delivery notes", r_ops.DELIV), ("Installation tasks", r_ops.INSTALL),
        ("QC inspection", r_ops.QC), ("Fix snags", r_ops.SNAG_FIX), ("Handover", r_ops.HANDOVER),
        ("Company settings & users", ADMINS), ("Client portal (own projects only)", ("CLIENT",)),
    ]


@router.get("/settings/roles")
def roles(user: dict = Depends(require_roles(*STAFF))):
    caps = _caps()
    return {"roles": m.ROLES, "capabilities": [{"name": n, "roles": ["SUPER_ADMIN"] + [r for r in m.ROLES if r in rs] if n != "Client portal (own projects only)" else ["CLIENT"]}
                                               for n, rs in caps]}


# ── System status + AI engines ────────────────────────────────────────────────
def _ollama():
    try:
        r = httpx.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=1.5)
        return {"reachable": r.status_code == 200, "models": [x.get("name") for x in r.json().get("models", [])] if r.status_code == 200 else []}
    except Exception:
        return {"reachable": False, "models": []}


@router.get("/settings/system")
def system(db: Session = Depends(get_db), user: dict = Depends(require_roles(*ADMINS))):
    url = settings.DATABASE_URL; kind = url.split(":", 1)[0]
    size = None
    if kind == "sqlite":
        path = url.replace("sqlite:///", "", 1)
        size = os.path.getsize(path) if os.path.exists(path) else None
    tables = inspect(engine).get_table_names()
    counts = {t: db.execute(__import__("sqlalchemy").text(f'SELECT COUNT(*) FROM "{t}"')).scalar() for t in sorted(tables)}
    store = os.path.abspath(settings.STORAGE_PATH)
    try:
        os.makedirs(store, exist_ok=True); probe = os.path.join(store, ".write_test")
        open(probe, "w").close(); os.remove(probe); writable = True
    except OSError: writable = False
    has = lambda mod: importlib.util.find_spec(mod) is not None
    sch, job = _schema(), _jobs(db)
    return {"python": sys.version.split()[0], "platform": platform.platform(), "database": {"kind": kind, "size_bytes": size, "tables": len(tables), "rows": counts},
            "storage": {"path": store, "writable": writable},
            "ocr": {"pdf_text_layer": has("pypdfium2"), "paddleocr": has("paddleocr"), "rapidocr": has("rapidocr_onnxruntime"),
                    "tesseract": has("pytesseract") and shutil.which("tesseract") is not None},
            "pdf": has("reportlab"), "dxf": has("ezdxf"), "ollama": _ollama(), "token_minutes": settings.TOKEN_MINUTES,
            "schema": sch, "jobs": job,
            "warnings": [w for w in ("SECRET_KEY is the development default — set SECRET_KEY in .env before real use" if settings.SECRET_KEY == "dev-secret-change-me" else "",
                                     "Upload folder is not writable" if not writable else "",
                                     f"Database schema is at {sch['revision']} but the code expects {sch['head']} — run: cd apps/api && alembic upgrade head" if not sch["up_to_date"] else "",
                                     "TASK_BACKEND=celery but CELERY_BROKER_URL is empty (using ./celery-broker.db)" if job["backend"] == "celery" and not settings.CELERY_BROKER_URL else "") if w]}


def _schema() -> dict:
    """Current Alembic revision of the database vs the newest revision in the code."""
    from pathlib import Path
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    here = Path(__file__).resolve().parents[2]
    cfg = Config(str(here / "alembic.ini")); cfg.set_main_option("script_location", str(here / "alembic"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    with engine.connect() as c: cur = MigrationContext.configure(c).get_current_revision()
    return {"revision": cur, "head": head, "up_to_date": cur == head, "tool": "alembic"}


def _jobs(db: Session) -> dict:
    from app.services import jobs
    broker = (settings.CELERY_BROKER_URL or "sqla+sqlite:///./celery-broker.db") if jobs.celery_on() else None
    if broker: broker = re.sub(r"://([^:/@]+):([^@]+)@", r"://:***@", broker)          # never show a broker password
    return {"backend": jobs.backend(), "broker": broker,
            "queued_emails": db.query(m.Message).filter_by(channel="EMAIL", status="QUEUED").count(),
            "sending_emails": db.query(m.Message).filter_by(status="SENDING").count(),
            "waiting_documents": db.query(m.Document).filter_by(status="UPLOADED").count(),
            "reading_documents": db.query(m.Document).filter_by(status="PROCESSING").count()}


@router.get("/settings/ai")
def ai(user: dict = Depends(require_roles(*STAFF))):
    o = _ollama(); has = lambda mod: importlib.util.find_spec(mod) is not None
    ocr = [n for n, ok in (("PaddleOCR", has("paddleocr")), ("RapidOCR", has("rapidocr_onnxruntime")), ("Tesseract", has("pytesseract") and shutil.which("tesseract") is not None)) if ok]
    return {"ollama": {"url": settings.OLLAMA_BASE_URL, "model": settings.OLLAMA_LLM_MODEL, **o, "model_installed": any((x or "").startswith(settings.OLLAMA_LLM_MODEL.split(":")[0]) for x in o["models"])},
            "features": [
                {"name": "Design brief understanding (AI Designer prompt)", "engine": "Local LLM via Ollama" if o["reachable"] else "Rule-based parser (Ollama not running)",
                 "note": "Only reads style/budget/priorities from the prompt. Never does geometry or money."},
                {"name": "Furniture layout", "engine": "Deterministic rules + Shapely validation", "note": "The browser never decides geometry; the server validates every layout."},
                {"name": "Drawing / document OCR", "engine": ", ".join(["PDF text layer"] + ocr), "note": "Values land as source=OCR and never overwrite verified measurements."},
                {"name": "Cutting lists & board nesting", "engine": "Deterministic rules", "note": "Estimate from the outer size; workshop confirms."},
                {"name": "AI Project Manager alerts", "engine": "Deterministic risk rules", "note": "Every alert names the rule and the evidence."},
                {"name": "Photo-real renders", "engine": "Not installed (Blender is optional and not bundled)", "note": "3D editor snapshots are saved as renders instead."},
            ],
            "how_to_enable_llm": f"Install Ollama (free), run `ollama pull {settings.OLLAMA_LLM_MODEL}`, keep it running; set OLLAMA_BASE_URL / OLLAMA_LLM_MODEL in apps/api/.env to change it."}


# ── CRM contacts ──────────────────────────────────────────────────────────────
class ContactIn(_In):
    client_id: str
    name: str = Field(min_length=1, max_length=120)
    relation: str | None = Field(None, max_length=60)
    phone: str | None = None
    email: str | None = Field(None, max_length=160)
    notes: str | None = Field(None, max_length=1000)

    @field_validator("phone")
    @classmethod
    def _ph(cls, v):
        if v is None or not v.strip(): return None
        try: normalize_phone(v)
        except PhoneError as e: raise ValueError(str(e))
        return v.strip()

    @field_validator("email")
    @classmethod
    def _em(cls, v):
        if v is None or not v.strip(): return None
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v.strip()): raise ValueError("Not a valid email address")
        return v.strip()


class ContactPatch(ContactIn):
    client_id: str | None = None
    name: str | None = Field(None, min_length=1, max_length=120)


def _c_out(c: m.Contact, clients: dict) -> dict:
    return {"id": c.id, "client_id": c.client_id, "client_name": clients.get(c.client_id), "name": c.name, "relation": c.relation, "phone": c.phone,
            "email": c.email, "notes": c.notes, "created_at": c.created_at.isoformat() if c.created_at else None}


@router.get("/contacts")
def list_contacts(q: str | None = None, client_id: str | None = None, db: Session = Depends(get_db), user: dict = Depends(require_roles(*r_crm.READ))):
    qry = db.query(m.Contact)
    if client_id: qry = qry.filter_by(client_id=client_id)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"; conds = [func.lower(m.Contact.name).like(like), func.lower(m.Contact.relation).like(like), func.lower(m.Contact.email).like(like)]
        try:
            if (pn := normalize_phone(q)): conds.append(m.Contact.phone_norm == pn)
        except PhoneError: pass
        qry = qry.filter(or_(*conds))
    clients = {c.id: c.name for c in db.query(m.Client)}
    return [_c_out(c, clients) for c in qry.order_by(m.Contact.name)]


@router.post("/contacts", status_code=201)
def create_contact(b: ContactIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*r_crm.WRITE))):
    if not db.get(m.Client, b.client_id): raise HTTPException(404, "Client not found")
    c = m.Contact(**b.model_dump(), phone_norm=normalize_phone(b.phone) if b.phone else None); db.add(c); db.commit()
    return _c_out(c, {x.id: x.name for x in db.query(m.Client)})


@router.patch("/contacts/{cid}")
def patch_contact(cid: str, b: ContactPatch, db: Session = Depends(get_db), user: dict = Depends(require_roles(*r_crm.WRITE))):
    c = db.get(m.Contact, cid)
    if not c: raise HTTPException(404, "Contact not found")
    d = b.model_dump(exclude_unset=True)
    if "name" in d and not d["name"]: raise HTTPException(422, "name cannot be empty")
    if d.get("client_id") and not db.get(m.Client, d["client_id"]): raise HTTPException(404, "Client not found")
    if "client_id" in d and not d["client_id"]: d.pop("client_id")
    for k, v in d.items(): setattr(c, k, v)
    if "phone" in d: c.phone_norm = normalize_phone(c.phone) if c.phone else None
    db.commit(); return _c_out(c, {x.id: x.name for x in db.query(m.Client)})


@router.delete("/contacts/{cid}", status_code=204)
def delete_contact(cid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*r_crm.WRITE))):
    c = db.get(m.Contact, cid)
    if not c: raise HTTPException(404, "Contact not found")
    db.delete(c); db.commit()
