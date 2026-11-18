"""Real-browser test of M22 per-project staff permissions: an admin turns on 'Limit staff to their projects' in Settings → Company,
adds a designer to one project's team on the project page; the designer (own browser session) sees only that project, gets a clear
message on the other one's URL, and loses it when removed. The switch is turned off again at the end (other suites expect it off)."""
import os, sys, tempfile, time
import httpx
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]
c = httpx.Client(timeout=60)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
A = c.post(f"{API}/projects", json={"project_number": f"IQ-TEAM-A-{RUN}", "name": "Team villa"}, headers=H).json()
B = c.post(f"{API}/projects", json={"project_number": f"IQ-TEAM-B-{RUN}", "name": "Other flat"}, headers=H).json()

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

def login(page, email):
    page.goto(f"{WEB}/login"); page.fill("#email", email); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")

try:
    with sync_playwright() as p:
        br = p.chromium.launch(); problems = []
        admin = br.new_context(viewport={"width": 1500, "height": 1000}).new_page(); admin.set_default_timeout(60000)
        admin.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
        login(admin, "admin@interioriq.com")

        admin.goto(f"{WEB}/projects/{A['id']}"); admin.get_by_test_id("project-team").wait_for()
        check("team card: everyone can open projects while the switch is off", "All staff can open every project" in admin.get_by_test_id("project-team").inner_text())
        check("the creator is on the team", admin.locator("[data-member='Admin User']").count() == 1)

        admin.goto(f"{WEB}/settings/company"); sw = admin.get_by_role("switch", name="Limit staff to their projects (staff see only projects whose team they're on)"); sw.wait_for()
        if sw.get_attribute("aria-checked") != "true": sw.click()
        admin.get_by_role("button", name="Save").click(); admin.wait_for_selector("text=Saved")
        check("switch turned on in Settings → Company", c.get(f"{API}/settings/company", headers=H).json()["values"]["limit_staff_to_projects"] is True)

        admin.goto(f"{WEB}/projects/{A['id']}"); team = admin.get_by_test_id("project-team"); team.wait_for()
        admin.wait_for_selector("text=Access is limited")
        team.get_by_label("Add team member").select_option(label="Kiran Shah — interior designer"); team.get_by_role("button", name="Add").click()
        admin.wait_for_selector("[data-member='Kiran Shah']")
        check("designer added to project A's team", True)
        admin.screenshot(path=f"{SHOTS}/team_card.png", full_page=True)

        des = br.new_context(viewport={"width": 1500, "height": 1000}).new_page(); des.set_default_timeout(60000)
        des.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
        login(des, "kiran@interioriq.com")
        des.goto(f"{WEB}/projects"); des.wait_for_selector(f"text=IQ-TEAM-A-{RUN}")
        check("designer's project list shows A but not B", des.locator(f"text=IQ-TEAM-B-{RUN}").count() == 0)
        des.goto(f"{WEB}/projects/{B['id']}"); des.wait_for_selector("text=not on this project's team")
        check("opening B's URL explains why it's refused", True)
        des.screenshot(path=f"{SHOTS}/team_refused.png", full_page=True)

        admin.get_by_role("button", name="Remove Kiran Shah").click(); admin.wait_for_selector("[data-member='Kiran Shah']", state="detached")
        des.goto(f"{WEB}/projects"); des.wait_for_timeout(2500)
        check("removed → A disappears from the designer's list", des.locator(f"text=IQ-TEAM-A-{RUN}").count() == 0)
        tl = c.get(f"{API}/projects/{A['id']}/timeline", headers=H).json()
        check("team changes are on the project timeline", any("Kiran Shah (interior designer) added" in e["text"] for e in tl) and any("Kiran Shah removed" in e["text"] for e in tl))
        check("no browser errors", not problems, "; ".join(problems[:5]))
        br.close()
finally:
    c.put(f"{API}/settings/company", json={"limit_staff_to_projects": False}, headers=H)

print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
