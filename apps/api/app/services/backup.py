"""Backups that work on SQLite AND Postgres — and between them (the way to move a studio from SQLite to Postgres).

A backup is ONE zip:
  manifest.json      format, schema revision, database kind, who/when, per-table row count + SHA-256, per-file size + SHA-256
  data/<table>.jsonl every row of every table, one JSON object per line (dates ISO-8601, money as exact decimal strings)
  files/<path>       the uploads folder (STORAGE_PATH): drawings, site photos, renders …

Create reads all tables inside ONE transaction, so the snapshot is consistent. Restore verifies every checksum first, then — in ONE database
transaction — drops the schema, rebuilds it at the backup's revision (Alembic), inserts the rows and migrates to the current revision; any
error rolls everything back and the database is exactly as it was. The uploads folder is swapped in only after the database commit (the old
one is kept next to it as '<storage>.before-restore-<time>'). Backups contain client data and password hashes: admins only, keep them safe."""
import base64, hashlib, json, logging, os, re, tempfile, threading, time, zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import MetaData, inspect, select
from sqlalchemy import types as T

from app.core.config import settings

log = logging.getLogger("interioriq.backup")
FORMAT, FORMAT_VERSION = "interioriq-backup", 1
NAME_RE = re.compile(r"^(auto|manual|pre-restore|uploaded)-\d{8}-\d{6}(-\d+)?\.zip$")
API_DIR = Path(__file__).resolve().parents[2]


class BackupError(Exception):
    def __init__(self, status: int, message: str): super().__init__(message); self.status, self.message = status, message


def backup_dir() -> Path:
    p = Path(settings.BACKUP_DIR)
    if not p.is_absolute(): p = (API_DIR / p).resolve()
    p.mkdir(parents=True, exist_ok=True); return p


def storage_dir() -> Path:
    p = Path(settings.STORAGE_PATH)
    return p if p.is_absolute() else (API_DIR / p).resolve()


def _alembic_cfg():
    from alembic.config import Config
    cfg = Config(str(API_DIR / "alembic.ini")); cfg.set_main_option("script_location", str(API_DIR / "alembic")); return cfg


def head_revision() -> str:
    from alembic.script import ScriptDirectory
    return ScriptDirectory.from_config(_alembic_cfg()).get_current_head()


def known_revisions() -> set:
    from alembic.script import ScriptDirectory
    return {s.revision for s in ScriptDirectory.from_config(_alembic_cfg()).walk_revisions()}


def current_revision(conn) -> str | None:
    from alembic.runtime.migration import MigrationContext
    return MigrationContext.configure(conn).get_current_revision()


# ── value encoding (portable between SQLite and Postgres) ────────────────────
def _enc(v):
    if isinstance(v, datetime): return (v.astimezone(timezone.utc) if v.tzinfo else v).isoformat()      # always UTC in the file
    if isinstance(v, date): return v.isoformat()
    if isinstance(v, Decimal): return format(v, "f")
    if isinstance(v, (bytes, bytearray, memoryview)): return {"$b64": base64.b64encode(bytes(v)).decode()}
    return v


def _dec(v, col):
    if v is None: return None
    t = col.type
    if isinstance(v, dict) and set(v) == {"$b64"}: return base64.b64decode(v["$b64"])
    if isinstance(t, T.DateTime) and isinstance(v, str):
        d = datetime.fromisoformat(v)
        # the app stores UTC; SQLite drops the zone and Postgres answers in the server's zone — normalise both to UTC
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
    if isinstance(t, T.Date) and isinstance(v, str): return date.fromisoformat(v[:10])
    if isinstance(t, T.Numeric) and not isinstance(t, (T.Float, T.Integer)) and isinstance(v, (str, int, float)): return Decimal(str(v))
    if isinstance(t, T.Boolean) and isinstance(v, int): return bool(v)
    return v


def _sha(b: bytes) -> str: return hashlib.sha256(b).hexdigest()


# ── create ───────────────────────────────────────────────────────────────────
def unique_name(kind: str, out_dir: Path | None = None) -> str:
    out_dir = out_dir or backup_dir()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"); name = f"{kind}-{stamp}.zip"; n = 1
    while (out_dir / name).exists() or (out_dir / (name + ".part")).exists(): n += 1; name = f"{kind}-{stamp}-{n}.zip"
    return name


def create(eng=None, kind: str = "manual", include_files: bool = True, by: str | None = None, out_dir: Path | None = None) -> dict:
    from app.core.database import Base, engine
    import app.models.models  # noqa: F401
    eng = eng or engine
    out_dir = out_dir or backup_dir()
    name = unique_name(kind, out_dir); tmp = out_dir / (name + ".part")
    manifest = {"format": FORMAT, "format_version": FORMAT_VERSION, "created_at": datetime.now(timezone.utc).isoformat(), "created_by": by,
                "database": eng.dialect.name, "tables": {}, "files": {}, "include_files": include_files}
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            with eng.connect() as conn:
                if eng.dialect.name == "postgresql": conn = conn.execution_options(isolation_level="REPEATABLE READ")
                with conn.begin():                                                   # one snapshot for every table
                    rev = current_revision(conn)
                    if rev != head_revision():
                        raise BackupError(409, f"The database is at schema {rev} but the code expects {head_revision()} — run `alembic upgrade head` first")
                    manifest["schema_revision"] = rev
                    insp = inspect(conn); have = set(insp.get_table_names())
                    for table in Base.metadata.sorted_tables:
                        if table.name not in have: continue
                        cols = {c["name"] for c in insp.get_columns(table.name)}          # only what this database has (its revision may be older than the code)
                        h = hashlib.sha256(); rows = 0
                        with z.open(f"data/{table.name}.jsonl", "w") as f:
                            for row in conn.execute(select(*[c for c in table.columns if c.name in cols]).order_by(*table.primary_key.columns)):
                                line = (json.dumps({k: _enc(v) for k, v in row._mapping.items()}, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
                                f.write(line); h.update(line); rows += 1
                        manifest["tables"][table.name] = {"rows": rows, "sha256": h.hexdigest()}
            if include_files and storage_dir().exists():
                root = storage_dir()
                for p in sorted(root.rglob("*")):
                    if not p.is_file() or ".before-restore-" in str(p): continue
                    rel = p.relative_to(root).as_posix(); data = p.read_bytes()
                    z.writestr(f"files/{rel}", data); manifest["files"][rel] = {"size": len(data), "sha256": _sha(data)}
            z.writestr("manifest.json", json.dumps(manifest, indent=1))
        os.replace(tmp, out_dir / name)
    except BaseException:
        try: tmp.unlink()
        except OSError: pass
        raise
    return info(out_dir / name)


# ── inspect / verify ─────────────────────────────────────────────────────────
def _manifest(z: zipfile.ZipFile) -> dict:
    try: m = json.loads(z.read("manifest.json"))
    except KeyError: raise BackupError(422, "Not an InteriorIQ backup (no manifest.json)")
    except ValueError: raise BackupError(422, "The backup's manifest is damaged")
    if m.get("format") != FORMAT: raise BackupError(422, "Not an InteriorIQ backup")
    if m.get("format_version", 0) > FORMAT_VERSION: raise BackupError(422, "This backup was made by a newer version of InteriorIQ — update the app first")
    return m


def info(path: Path) -> dict:
    with zipfile.ZipFile(path) as z: m = _manifest(z)
    st = path.stat()
    return {"name": path.name, "kind": path.name.split("-")[0] if not path.name.startswith("pre-restore") else "pre-restore", "size_bytes": st.st_size,
            "created_at": m.get("created_at"), "created_by": m.get("created_by"), "database": m.get("database"), "schema_revision": m.get("schema_revision"),
            "tables": len(m.get("tables", {})), "rows": sum(t["rows"] for t in m.get("tables", {}).values()),
            "files": len(m.get("files", {})), "files_bytes": sum(f["size"] for f in m.get("files", {}).values()), "include_files": m.get("include_files", True)}


def verify(path: Path) -> dict:
    """Every table and file is read back and checked against the manifest's SHA-256. Returns the manifest summary + problems (empty = OK)."""
    problems = []
    try: z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError): raise BackupError(422, "The file is not a readable zip")
    with z:
        m = _manifest(z)
        if m.get("schema_revision") not in known_revisions():
            problems.append(f"Schema revision {m.get('schema_revision')} is unknown to this version of the app (made by a newer version?)")
        bad = z.testzip()
        if bad: problems.append(f"Corrupt entry in the zip: {bad}")
        for t, meta in m.get("tables", {}).items():
            try: data = z.read(f"data/{t}.jsonl")
            except KeyError: problems.append(f"Table {t} is missing"); continue
            if _sha(data) != meta["sha256"]: problems.append(f"Table {t} does not match its checksum")
            elif data.count(b"\n") != meta["rows"]: problems.append(f"Table {t}: expected {meta['rows']} rows")
        for rel, meta in m.get("files", {}).items():
            if ".." in rel.split("/") or rel.startswith("/"): problems.append(f"Unsafe file path {rel}"); continue
            try: data = z.read(f"files/{rel}")
            except KeyError: problems.append(f"File {rel} is missing"); continue
            if _sha(data) != meta["sha256"]: problems.append(f"File {rel} does not match its checksum")
    return {**info(path), "ok": not problems, "problems": problems}


# ── restore ──────────────────────────────────────────────────────────────────
def restore(path: Path, eng=None, *, safety_backup: bool = True, restore_files: bool = True, by: str | None = None) -> dict:
    from alembic import command
    from app.core.database import Base, engine
    import app.models.models  # noqa: F401
    eng = eng or engine
    v = verify(path)
    if not v["ok"]: raise BackupError(422, "The backup failed verification: " + "; ".join(v["problems"][:5]))
    safety = None
    if safety_backup:
        with eng.connect() as c: has_data = "users" in inspect(c).get_table_names()
        if has_data:
            try: safety = create(eng, kind="pre-restore", include_files=restore_files, by=by)["name"]
            except BackupError as e:
                raise BackupError(409, f"Couldn't take the safety backup before restoring ({e.message}). Nothing was changed.")
    from app.core.database import transactional
    tx = transactional(eng)
    with zipfile.ZipFile(path) as z:
        m = _manifest(z); rev = m["schema_revision"]
        with tx.begin() as conn:                                                   # ONE transaction (DDL included): all or nothing
            old = MetaData(); old.reflect(conn)
            old.drop_all(conn)                                                     # every existing table, in FK order (incl. alembic_version)
            cfg = _alembic_cfg(); cfg.attributes["connection"] = conn; cfg.attributes["added"] = []
            command.upgrade(cfg, rev)                                              # the schema exactly as the backup knew it
            shaped = MetaData(); shaped.reflect(conn)
            counts = {}
            for table in shaped.sorted_tables:
                if table.name == "alembic_version" or table.name not in m["tables"]: continue
                cols = {c.name: c for c in table.columns}
                batch, total = [], 0
                for line in z.read(f"data/{table.name}.jsonl").decode().splitlines():
                    if not line: continue
                    raw = json.loads(line)
                    batch.append({k: _dec(val, cols[k]) for k, val in raw.items() if k in cols})
                    if len(batch) >= 500: conn.execute(table.insert(), batch); total += len(batch); batch = []
                if batch: conn.execute(table.insert(), batch); total += len(batch)
                counts[table.name] = total
            command.upgrade(cfg, "head")                                           # then bring it up to this version of the app
        if tx is not eng: tx.dispose()
        eng.dispose()                                                              # pooled connections must not keep the old schema cached
        restored_files = 0
        if restore_files and m.get("include_files", True):
            root = storage_dir(); root.parent.mkdir(parents=True, exist_ok=True)
            fresh = Path(tempfile.mkdtemp(prefix="iq-restore-", dir=root.parent))
            for rel in m.get("files", {}):
                target = fresh / rel; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(f"files/{rel}")); restored_files += 1
            kept = None
            if root.exists():
                kept = root.with_name(root.name + ".before-restore-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
                os.replace(root, kept)
            os.replace(fresh, root)
    return {"restored": path.name, "schema_revision_in_backup": rev, "schema_revision_now": head_revision(), "rows": sum(counts.values()),
            "tables": counts, "files": restored_files, "safety_backup": safety}


# ── listing, rotation, daily schedule ───────────────────────────────────────
def list_backups() -> list[dict]:
    out = []
    for p in sorted(backup_dir().glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not NAME_RE.match(p.name): continue
        try: out.append(info(p))
        except (BackupError, zipfile.BadZipFile, OSError): out.append({"name": p.name, "kind": "damaged", "size_bytes": p.stat().st_size, "error": "unreadable"})
    return out


def path_of(name: str) -> Path:
    if not NAME_RE.match(name or ""): raise BackupError(404, "Backup not found")
    p = backup_dir() / name
    if not p.exists(): raise BackupError(404, "Backup not found")
    return p


def rotate(keep: int | None = None) -> list[str]:
    keep = settings.BACKUP_KEEP if keep is None else keep; gone = []
    for prefix, n in (("auto-", keep), ("pre-restore-", 5)):
        files = sorted(backup_dir().glob(prefix + "*.zip"), key=lambda p: p.name, reverse=True)
        for p in files[max(n, 0):]:
            try: p.unlink(); gone.append(p.name)
            except OSError: pass
    return gone


def local_now(): return datetime.now(timezone.utc) + timedelta(minutes=settings.COMPANY_UTC_OFFSET_MIN)


def claim_daily(db, now_local=None) -> bool:
    """True for exactly one server per local day, once it's past BACKUP_HOUR (conditional UPDATE on job_locks)."""
    from app.models import models as m
    now_local = now_local or local_now()
    if now_local.hour < settings.BACKUP_HOUR: return False
    today = now_local.date().isoformat()
    if not db.get(m.JobLock, "auto_backup"):
        try: db.add(m.JobLock(name="auto_backup", value="")); db.commit()
        except Exception: db.rollback()
    n = db.query(m.JobLock).filter(m.JobLock.name == "auto_backup", (m.JobLock.value.is_(None)) | (m.JobLock.value != today)).update(
        {"value": today, "updated_at": datetime.now(timezone.utc)}, synchronize_session=False)
    db.commit(); return n == 1


def run_daily_if_due(session_factory) -> dict | None:
    db = session_factory()
    try:
        if not claim_daily(db): return None
    finally: db.close()
    made = create(kind="auto", by="automatic daily backup"); rotate()
    log.info("Automatic backup %s (%s bytes)", made["name"], made["size_bytes"]); return made


_started = [False]


def start_scheduler(session_factory, interval: float = 600):
    if _started[0] or not settings.BACKUP_DAILY: return
    _started[0] = True
    def loop():
        time.sleep(30)
        while True:
            try: run_daily_if_due(session_factory)
            except Exception: log.exception("automatic backup failed")
            time.sleep(interval)
    threading.Thread(target=loop, name="auto-backup", daemon=True).start()
