"""Real-browser test of M20 lead ownership + follow-ups: 'no next step' badge + filter, schedule a site visit from the lead drawer, change the
owner, mark it done with an outcome + stage move + next call, CRM → Follow-ups lists it, moving a lead to Lost asks why (cancel rolls back),
archive/restore, dashboard card."""
import os, sys, tempfile, time
import httpx
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]
c = httpx.Client(timeout=30)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
A, B = f"Follow Asha {RUN}", f"Lost Bhavin {RUN}"
c.post(f"{API}/leads", json={"name": A, "phone": f"98{RUN}11", "requirement": "3BHK full interior"}, headers=H).raise_for_status()
c.post(f"{API}/leads", json={"name": B, "phone": f"97{RUN}22"}, headers=H).raise_for_status()

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

with sync_playwright() as p:
    br = p.chromium.launch(); page = br.new_page(viewport={"width": 1700, "height": 1000}); problems = []
    page.set_default_timeout(60000); page.set_default_navigation_timeout(90000)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" and "409" not in m.text and "422" not in m.text else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and r.status not in (409, 422) else None)
    page.goto(f"{WEB}/login"); page.fill("#email", "admin@interioriq.com"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")
    card = lambda n: page.locator(f"[data-lead='{n}']")

    page.goto(f"{WEB}/crm/leads"); card(A).wait_for()
    check("new lead is owned by its creator and shows 'No next step'", card(A).locator("[data-fu=NONE]").count() == 1 and card(A).locator("span[title='Owner: Admin User']").count() == 1)
    page.get_by_label("Follow-up filter").select_option("NONE"); page.wait_for_timeout(1200)
    check("'No next step' filter lists it", card(A).count() == 1)
    page.get_by_label("Follow-up filter").select_option(""); page.wait_for_timeout(800)

    # schedule a site visit from the drawer
    card(A).locator("p", has_text=A).click(); fu = page.get_by_test_id("lead-followups"); fu.wait_for()
    fu.get_by_label("Follow-up type").select_option("VISIT"); fu.get_by_label("Follow-up note").fill("Measure the flat")
    fu.get_by_role("button", name="Schedule follow-up").click(); fu.locator("[data-followup=VISIT]").wait_for()
    check("site visit scheduled in the drawer", "Measure the flat" in fu.get_by_test_id("open-followups").inner_text())
    fu.get_by_label("Lead owner").select_option(label="Priya Mehta"); page.wait_for_selector("[data-testid=lead-history] >> text=Assigned to Priya Mehta")
    check("owner changed and logged in history", fu.get_by_label("Lead owner").evaluate("e => e.options[e.selectedIndex].text") == "Priya Mehta")
    check("open follow-up moved to the new owner", "Priya Mehta" in fu.get_by_test_id("open-followups").inner_text())

    # done → outcome, move stage, book the next call
    fu.get_by_role("button", name="Done Site visit").click(); dlg = page.get_by_role("dialog", name="Follow-up done"); dlg.wait_for()
    dlg.get_by_label("Outcome").fill("Measured; client wants a design by Friday"); dlg.get_by_label("Move lead to").select_option("SITE_VISIT")
    dlg.get_by_label("Next follow-up type").select_option("CALL"); dlg.get_by_role("button", name="Save").click(); dlg.wait_for(state="detached")
    fu.locator("[data-followup=CALL]").wait_for()
    check("next call booked; visit closed with its outcome", fu.locator("[data-followup=VISIT]").count() == 0 and "1 earlier follow-up" in fu.inner_text())
    check("history records the outcome", "Visit done: Measured" in page.get_by_test_id("lead-history").inner_text())
    page.screenshot(path=f"{SHOTS}/lead_followups.png", full_page=True)
    page.keyboard.press("Escape"); page.get_by_label("Close").first.click() if page.get_by_test_id("lead-followups").count() else None
    page.wait_for_timeout(800)
    check("card moved to Site visit with an upcoming follow-up badge", page.locator(f"[data-stage=SITE_VISIT] [data-lead='{A}']").count() == 1
          and card(A).locator("[data-fu=UPCOMING], [data-fu=TODAY]").count() == 1)

    # Lost asks why; cancel keeps the stage
    sel = page.get_by_label(f"Stage for {B}"); sel.select_option("LOST"); ld = page.get_by_role("dialog", name="Mark lost"); ld.wait_for()
    ld.get_by_role("button", name="Cancel").click(); ld.wait_for(state="detached")
    check("cancelling the Lost dialog leaves the lead where it was", page.locator(f"[data-stage=NEW] [data-lead='{B}']").count() == 1 and sel.input_value() == "NEW")
    sel.select_option("LOST"); ld.wait_for(); ld.get_by_role("radio", name="Budget too high").click(); ld.get_by_label("Lost details").fill("Went with a carpenter")
    ld.get_by_role("button", name="Mark lost").click(); ld.wait_for(state="detached"); page.wait_for_timeout(600)
    check("lead lost with its reason on the card", page.locator(f"[data-stage=LOST] [data-lead='{B}']").count() == 1 and "Budget too high — Went with a carpenter" in card(B).inner_text())

    # archive + restore
    card(B).locator("p", has_text=B).click(); page.get_by_role("button", name="Archive this lead").click(); page.wait_for_selector("button:has-text('Restore from archive')")
    page.get_by_label("Close").first.click(); page.wait_for_timeout(1200)
    check("archived lead hidden from the board", card(B).count() == 0)
    page.get_by_label("Show archived").check(); card(B).wait_for()
    check("'Show archived' brings it back", card(B).count() == 1)

    # CRM → Follow-ups (whole team, upcoming)
    page.goto(f"{WEB}/crm/followups"); page.get_by_label("Whose follow-ups").select_option("team")
    page.wait_for_timeout(1500); page.get_by_role("tab", name="Upcoming").click()
    row = page.locator(f"[data-followup-row='{A}']", has_text="Priya Mehta"); row.wait_for()
    check("Follow-ups page lists the booked call with the owner", "Priya Mehta" in row.inner_text() and "Call" in row.inner_text())
    page.get_by_label("Whose follow-ups").select_option("mine"); page.wait_for_timeout(1500)
    check("'Mine' hides Priya's call from the admin", page.locator(f"[data-followup-row='{A}']").count() == 0)
    page.screenshot(path=f"{SHOTS}/followups_page.png", full_page=True)

    page.goto(f"{WEB}/dashboard"); page.wait_for_selector("text=My follow-ups due")
    check("dashboard shows the follow-ups card", page.locator("text=My follow-ups due").count() == 1)
    check("no browser errors or failed requests", not problems, "; ".join(problems[:5]))
    br.close()

print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
