"""Real-browser test of M24 Settings → Backups: back up now (with files), verify the checksums, then — after a new project is created —
restore with the typed confirmation; the project made after the backup is gone, a safety backup of the state just before exists, and the
app keeps working. RUN LAST: it rolls the test database back. The runner points STORAGE_PATH / BACKUP_DIR at throwaway folders."""
import os, sys, time
import httpx
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")
RUN = str(int(time.time()))[-6:]
c = httpx.Client(timeout=120)
tok = lambda: c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]
H = {"Authorization": "Bearer " + tok()}
before = c.post(f"{API}/projects", json={"project_number": f"IQ-BK-A-{RUN}", "name": "Before the backup"}, headers=H).json()

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

with sync_playwright() as p:
    br = p.chromium.launch(); page = br.new_page(viewport={"width": 1500, "height": 1000}); page.set_default_timeout(120000); problems = []
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 500 else None)
    page.goto(f"{WEB}/login"); page.fill("#email", "admin@interioriq.com"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")
    page.goto(f"{WEB}/settings/backups"); page.get_by_test_id("daily-status").wait_for()
    check("daily backup status shown (off in this test run)", "Off" in page.get_by_test_id("daily-status").inner_text())
    n0 = page.locator("[data-backup]").count()
    page.get_by_role("button", name="Back up now").click(); page.wait_for_selector("text=Backup created")
    page.wait_for_function(f"() => document.querySelectorAll('[data-backup]').length > {n0}")
    row = page.locator("[data-backup^='manual-']").first; name = row.get_attribute("data-backup")
    check("backup listed with rows and schema", "rows" in row.inner_text() and "schema" in row.inner_text(), row.inner_text()[:120])
    row.get_by_role("button", name=f"Verify {name}").click(); page.get_by_test_id("verify-result").wait_for()
    check("verify: every table and file matches its checksum", "match their checksums" in page.get_by_test_id("verify-result").inner_text())

    after = c.post(f"{API}/projects", json={"project_number": f"IQ-BK-B-{RUN}", "name": "Made after the backup"}, headers=H).json()
    row.get_by_role("button", name=f"Restore {name}").click(); dlg = page.get_by_role("dialog", name="Restore backup"); dlg.wait_for()
    check("restore asks for the typed confirmation", dlg.get_by_role("button", name="Restore now").is_disabled())
    dlg.get_by_label("Confirm restore").fill("RESTORE"); dlg.get_by_role("button", name="Restore now").click()
    page.get_by_test_id("restore-done").wait_for()
    done = page.get_by_test_id("restore-done").inner_text()
    check("restored, with a safety backup of the state just before", "pre-restore-" in done, done[:200])
    page.screenshot(path=os.path.join(os.environ.get("SHOTS", "."), "backups.png"), full_page=True)
    H2 = {"Authorization": "Bearer " + tok()}
    nums = {x["project_number"] for x in c.get(f"{API}/projects", headers=H2).json()}
    check("the project made before the backup is there, the one made after is gone", before["project_number"] in nums and after["project_number"] not in nums)
    page.goto(f"{WEB}/projects"); page.wait_for_selector(f"text=IQ-BK-A-{RUN}")
    check("the app keeps working after the restore", page.locator(f"text=IQ-BK-B-{RUN}").count() == 0)
    page.goto(f"{WEB}/settings/backups"); page.wait_for_selector("[data-backup^='pre-restore-']")
    check("the safety backup is listed", page.locator("[data-backup^='pre-restore-']").count() >= 1)
    check("no browser errors or server errors", not problems, "; ".join(problems[:5]))
    br.close()

print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
