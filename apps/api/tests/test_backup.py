"""M24 backups: create / verify / restore (DB + uploads), all-or-nothing restore, tamper detection, older-revision backups, daily claim +
rotation, CLI, admin API (roles, upload, download, traversal) — and SQLite ⇄ Postgres moves when IQ_TEST_PG_URL points at a scratch database."""
import json, os, subprocess, sys, zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import migrate
from app.main import app
from app.models import models as m
from app.services import backup as bk

API_DIR = Path(__file__).resolve().parents[1]
PG = os.environ.get("IQ_TEST_PG_URL")


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    st, bd = tmp_path / "storage", tmp_path / "backups"; (st / "projects" / "p1").mkdir(parents=True)
    (st / "projects" / "p1" / "plan.pdf").write_bytes(b"%PDF-1.4 plan")
    monkeypatch.setattr(settings, "STORAGE_PATH", str(st)); monkeypatch.setattr(settings, "BACKUP_DIR", str(bd))
    return st, bd


def db_with_data(url):
    eng = create_engine(url); migrate(eng)
    with Session(eng) as s:
        s.add(m.User(id="u1", email="a@x.com", full_name="Asha", role="ADMIN", password_hash="h", is_active=True))
        s.add(m.Client(id="c1", name="Client One", phone="98765 43210"))
        s.add(m.Project(id="p1", project_number="IQ-B-1", name="Villa", client_id="c1", status="DESIGN", budget=Decimal("1234567.89"), progress=40,
                        target_date=datetime(2027, 1, 15, 6, 30, tzinfo=timezone.utc)))
        s.add(m.FurnitureItem(id="f1", sku="BK-1", name="Bed — Oak", category="Bed", price=Decimal("68000.50"), stock=3, kind="FURNITURE", is_active=False,
                              length_mm=1630, width_mm=2030, height_mm=1000, style="minimal"))
        s.add(m.CompanySetting(key="name", value={"nested": [1, "two"]}, updated_by="t"))
        s.commit()
    return eng


def snapshot(eng):
    with Session(eng) as s:
        p = s.get(m.Project, "p1"); f = s.get(m.FurnitureItem, "f1"); c = s.get(m.CompanySetting, "name")
        td = p.target_date if p.target_date.tzinfo else p.target_date.replace(tzinfo=timezone.utc)
        return {"budget": Decimal(p.budget), "td": td, "price": Decimal(f.price), "active": f.is_active, "style": f.style, "json": c.value,
                "users": s.query(m.User).count(), "projects": s.query(m.Project).count()}


def test_round_trip_restores_database_and_files_and_keeps_a_safety_copy(tmp_path, dirs):
    st, bd = dirs
    eng = db_with_data(f"sqlite:///{tmp_path / 'a.db'}"); before = snapshot(eng)
    made = bk.create(eng, by="test")
    assert made["kind"] == "manual" and made["files"] == 1 and made["schema_revision"] == bk.head_revision() and made["rows"] >= 5
    assert bk.verify(bd / made["name"])["ok"]
    with Session(eng) as s:                                                  # life goes on after the backup…
        s.add(m.Project(id="p2", project_number="IQ-B-2", name="Later")); s.get(m.Project, "p1").name = "Changed"; s.commit()
    (st / "projects" / "p1" / "later.png").write_bytes(b"later")
    res = bk.restore(bd / made["name"], eng, by="test")
    assert res["rows"] == made["rows"] and res["files"] == 1 and res["safety_backup"].startswith("pre-restore-")
    assert snapshot(eng) == before
    with Session(eng) as s: assert s.get(m.Project, "p2") is None and s.get(m.Project, "p1").name == "Villa"
    assert sorted(p.name for p in st.rglob("*") if p.is_file()) == ["plan.pdf"]
    kept = [p for p in st.parent.iterdir() if ".before-restore-" in p.name]; assert kept and (kept[0] / "projects/p1/later.png").exists()
    safety = bk.verify(bd / res["safety_backup"]); assert safety["ok"] and safety["rows"] == made["rows"] + 1     # the state just before
    eng.dispose()


def test_a_tampered_backup_is_refused_and_nothing_changes(tmp_path, dirs):
    _, bd = dirs
    eng = db_with_data(f"sqlite:///{tmp_path / 'b.db'}"); made = bk.create(eng); src = bd / made["name"]
    bad = bd / "manual-20990101-000000.zip"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(bad, "w") as zout:
        for it in zin.infolist():
            data = zin.read(it.filename)
            if it.filename == "data/projects.jsonl": data = data.replace(b"Villa", b"Villb")
            zout.writestr(it, data)
    v = bk.verify(bad); assert not v["ok"] and "projects does not match" in v["problems"][0]
    with pytest.raises(bk.BackupError) as e: bk.restore(bad, eng)
    assert e.value.status == 422
    with Session(eng) as s: assert s.get(m.Project, "p1").name == "Villa"
    with pytest.raises(bk.BackupError): bk.verify(Path(__file__))                                    # not even a zip
    eng.dispose()


def test_a_failing_restore_rolls_back_completely(tmp_path, dirs, monkeypatch):
    _, bd = dirs
    eng = db_with_data(f"sqlite:///{tmp_path / 'c.db'}"); made = bk.create(eng)
    with Session(eng) as s: s.add(m.Project(id="p9", project_number="IQ-B-9", name="Keep me")); s.commit()
    real = bk._dec
    def boom(v, col):
        if col.name == "project_number": raise RuntimeError("disk on fire")
        return real(v, col)
    monkeypatch.setattr(bk, "_dec", boom)
    with pytest.raises(RuntimeError): bk.restore(bd / made["name"], eng, safety_backup=False, restore_files=False)
    with Session(eng) as s: assert s.get(m.Project, "p9").name == "Keep me" and s.query(m.User).count() == 1
    with eng.connect() as c: assert bk.current_revision(c) == bk.head_revision()
    eng.dispose()


def test_a_backup_from_an_older_schema_is_restored_and_migrated(tmp_path, dirs, monkeypatch):
    from alembic import command
    _, bd = dirs
    old = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    cfg = bk._alembic_cfg()
    with old.begin() as c: cfg.attributes["connection"] = c; command.upgrade(cfg, "0002")
    with old.begin() as c: c.exec_driver_sql("INSERT INTO clients (id, name) VALUES ('c9', 'From 0002')")
    monkeypatch.setattr(bk, "head_revision", lambda: "0002")
    made = bk.create(old, include_files=False); assert made["schema_revision"] == "0002"
    monkeypatch.undo()
    monkeypatch.setattr(settings, "BACKUP_DIR", str(bd))
    new = create_engine(f"sqlite:///{tmp_path / 'new.db'}")
    res = bk.restore(bd / made["name"], new, restore_files=False)
    assert res["schema_revision_in_backup"] == "0002" and res["schema_revision_now"] == bk.head_revision()
    assert "job_locks" in inspect(new).get_table_names()
    with Session(new) as s: assert s.get(m.Client, "c9").name == "From 0002"
    old.dispose(); new.dispose()


def test_daily_claim_happens_once_per_local_day_and_rotation_keeps_n(tmp_path, dirs, monkeypatch):
    _, bd = dirs
    eng = db_with_data(f"sqlite:///{tmp_path / 'd.db'}")
    noon = datetime(2026, 11, 19, 12, 0); early = datetime(2026, 11, 20, 1, 0)
    with Session(eng) as s:
        assert bk.claim_daily(s, noon) is True and bk.claim_daily(s, noon) is False                  # second server, same day
        assert bk.claim_daily(s, early) is False                                                     # before BACKUP_HOUR
        assert bk.claim_daily(s, early.replace(hour=3)) is True                                      # next day
    bd.mkdir(parents=True, exist_ok=True)
    for i in range(5): (bd / f"auto-2026111{i}-020000.zip").write_bytes(b"x")
    (bd / "manual-20261101-100000.zip").write_bytes(b"x")
    gone = bk.rotate(keep=2)
    assert sorted(p.name for p in bd.glob("*.zip")) == ["auto-20261113-020000.zip", "auto-20261114-020000.zip", "manual-20261101-100000.zip"] and len(gone) == 3
    eng.dispose()


def test_command_line(tmp_path, dirs):
    st, bd = dirs
    url = f"sqlite:///{tmp_path / 'cli.db'}"; db_with_data(url).dispose()
    env = {**os.environ, "DATABASE_URL": url, "STORAGE_PATH": str(st), "BACKUP_DIR": str(bd), "PYTHONIOENCODING": "utf-8"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "app.backup", *a], cwd=API_DIR, env=env, capture_output=True, text=True, timeout=180)
    r = run("create", "--out", str(tmp_path / "move")); assert r.returncode == 0, r.stderr
    path = r.stdout.strip().splitlines()[-1]; assert path.endswith(".zip") and Path(path).exists()
    assert run("verify", path).returncode == 0
    assert run("restore", path).returncode == 1                                                     # needs --yes
    r = run("restore", path, "--yes", "--no-safety-backup"); assert r.returncode == 0 and '"rows"' in r.stdout, r.stderr
    assert run("verify", __file__).returncode == 2


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c: yield c


def hdr(c, e="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": e, "password": "ChangeMe123!"}).json()["access_token"]}


def test_admin_api(client, tmp_path):
    h = hdr(client)
    r = client.post("/api/backups", json={"include_files": False}, headers=h); assert r.status_code == 201, r.text
    name = r.json()["name"]
    lst = client.get("/api/backups", headers=h).json()
    assert name in [b["name"] for b in lst["backups"]] and lst["daily"]["enabled"] is False and lst["database"] in ("sqlite", "postgresql")
    assert client.post(f"/api/backups/{name}/verify", headers=h).json()["ok"] is True
    z = client.get(f"/api/backups/{name}/download", headers=h); assert z.status_code == 200 and z.content[:2] == b"PK"
    for bad in ("..%2F..%2Fsecret.zip", "nope.zip", "manual-1.zip"):
        assert client.get(f"/api/backups/{bad}/download", headers=h).status_code == 404
    up = client.post("/api/backups/upload", files={"file": ("b.zip", z.content, "application/zip")}, headers=h).json()
    assert up["name"].startswith("uploaded-") and up["ok"] is True
    assert client.post("/api/backups/upload", files={"file": ("x.zip", b"not a zip", "application/zip")}, headers=h).status_code == 422
    assert client.post(f"/api/backups/{name}/restore", json={"confirm": "yes"}, headers=h).status_code == 422
    r = client.post(f"/api/backups/{name}/restore", json={"confirm": "RESTORE", "restore_files": False}, headers=h).json()
    assert r["rows"] > 0 and r["safety_backup"].startswith("pre-restore-")
    assert client.get("/api/projects", headers=hdr(client)).status_code == 200                          # the app keeps working (and logins still work)
    assert client.post(f"/api/backups/{up['name']}/delete", json={"confirm": "x"}, headers=h).status_code == 422
    assert client.post(f"/api/backups/{up['name']}/delete", json={"confirm": up["name"]}, headers=h).status_code == 200
    from app.core.database import SessionLocal
    db = SessionLocal()
    from app.core.security import hash_password
    if not db.query(m.User).filter_by(email="pm24@test.com").first():
        db.add(m.User(email="pm24@test.com", full_name="PM", role="PROJECT_MANAGER", password_hash=hash_password("ChangeMe123!"))); db.commit()
    db.close()
    assert client.get("/api/backups", headers=hdr(client, "pm24@test.com")).status_code == 403


@pytest.mark.skipif(not PG, reason="set IQ_TEST_PG_URL to a scratch Postgres database to test SQLite ⇄ Postgres moves")
def test_sqlite_to_postgres_and_back(tmp_path, dirs):
    _, bd = dirs
    lite = db_with_data(f"sqlite:///{tmp_path / 'lite.db'}"); before = snapshot(lite)
    made = bk.create(lite)
    pg = create_engine(PG)
    res = bk.restore(bd / made["name"], pg)                                    # into Postgres (empty or not — it is replaced)
    assert res["rows"] == made["rows"] and snapshot(pg) == before
    with pg.connect() as c: assert bk.current_revision(c) == bk.head_revision()
    back = bk.create(pg)
    lite2 = create_engine(f"sqlite:///{tmp_path / 'lite2.db'}")
    bk.restore(bd / back["name"], lite2, safety_backup=False)
    assert snapshot(lite2) == before
    lite.dispose(); pg.dispose(); lite2.dispose()
