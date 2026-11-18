from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import settings

_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate(eng=None) -> list[str]:
    """Bring the database to the latest schema with Alembic (`alembic upgrade head`) on this engine.
    Works for a fresh database, one created by an older InteriorIQ before Alembic (the baseline revision fills in missing tables/columns
    without touching data, then stamps it), and one already under Alembic (just the new revisions). Returns "table.column" names added to a
    pre-Alembic database (empty otherwise)."""
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    eng = eng or engine
    here = Path(__file__).resolve().parents[2]                 # apps/api
    cfg = Config(str(here / "alembic.ini")); cfg.set_main_option("script_location", str(here / "alembic"))
    cfg.attributes["added"] = []
    with eng.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    return list(cfg.attributes["added"])


def upgrade_schema(eng=None) -> list[str]:
    """Kept for callers/tests from before Alembic: same as migrate()."""
    return migrate(eng)
