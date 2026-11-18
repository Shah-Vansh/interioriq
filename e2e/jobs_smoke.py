"""Real-browser check of M23 on Settings → System: the database schema is at the code's Alembic head, and background jobs run on the
backend this test run started (IQ_TASK_BACKEND=thread|celery). In Celery mode, run documents_smoke.py / notifications_smoke.py after it:
their OCR and emails are then done by the separate worker process, end to end."""
import os, sys
from playwright.sync_api import sync_playwright

WEB = os.environ.get("IQ_WEB", "http://localhost:3000"); BACKEND = os.environ.get("IQ_TASK_BACKEND", "thread")
fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

with sync_playwright() as p:
    br = p.chromium.launch(); page = br.new_page(viewport={"width": 1400, "height": 1000}); page.set_default_timeout(60000); problems = []
    page.on("pageerror", lambda e: problems.append(str(e)[:150]))
    page.goto(f"{WEB}/login"); page.fill("#email", "admin@interioriq.com"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")
    page.goto(f"{WEB}/settings/system"); page.get_by_test_id("schema-status").wait_for()
    sch = page.get_by_test_id("schema-status").inner_text(); jobs = page.get_by_test_id("jobs-status").inner_text()
    check("schema: alembic, database at the code's head", "alembic" in sch and sch.count("0002") == 2 and "Run" not in sch, sch)
    check(f"jobs run on the {BACKEND} backend", ("Celery workers" in jobs) if BACKEND == "celery" else ("This API process" in jobs), jobs)
    if BACKEND == "celery": check("broker shown without secrets", "sqla+sqlite" in jobs and "***" not in jobs or "***" in jobs)
    check("no browser errors", not problems, "; ".join(problems[:3]))
    br.close()

print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
