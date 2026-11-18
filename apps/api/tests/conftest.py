# Runs before any test module: isolate the database AND the upload folder so tests never touch real data.
import os, tempfile
_tmp = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("STORAGE_PATH", f"{_tmp}/storage")
os.environ.setdefault("NOTIFY_WORKER", "false")
os.environ.setdefault("CELERY_BROKER_URL", f"sqla+sqlite:///{_tmp}/celery-broker.db")   # never create a broker file in the project
os.environ["SMTP_HOST"] = ""            # never send real mail from tests
