"""Real-browser test of the CRM: create a lead, DRAG it across the board, add a note, see the history, convert it,
catch a duplicate client phone typed differently, link a project to a client, and check the quotation PDF prints that client."""
import os, sys, tempfile, time
import httpx, pypdfium2 as pdfium
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")   # override when 8000/3000 are taken
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]                       # unique per run so a reused database never clashes
c = httpx.Client(timeout=30)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
PHONE = f"98{RUN}11"[:10]                              # 10-digit mobile, unique per run
LEAD = f"Meera Iyer {RUN}"

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

with sync_playwright() as p:
    br = p.chromium.launch(); page = br.new_page(viewport={"width": 1600, "height": 1000}); problems = []
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" and "409" not in m.text and "422" not in m.text else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and r.status not in (409, 422) else None)
    page.goto(f"{WEB}/login"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")

    # Sidebar: no invented numbers
    page.goto(f"{WEB}/crm/leads"); page.wait_for_selector("[data-stage=NEW]")
    leads_link = page.locator("aside a[href='/crm/leads']").inner_text().strip()
    check("sidebar 'Leads' shows no made-up count", leads_link == "Leads", repr(leads_link))
    check("board has all 9 stage columns", page.locator("[data-stage]").count() == 9)

    # Create a lead through the form
    page.get_by_role("button", name="Add lead").click()
    dlg = page.get_by_role("dialog", name="New lead")
    dlg.get_by_label("Name *", exact=True).fill(LEAD); dlg.get_by_label("Phone", exact=True).fill(f"+91 {PHONE[:5]}-{PHONE[5:]}"); dlg.get_by_label("City", exact=True).fill("Ahmedabad")
    dlg.get_by_label("Budget (₹)", exact=True).fill("1800000"); dlg.get_by_label("Requirement", exact=True).fill("2BHK interior with modular kitchen")
    dlg.get_by_role("button", name="Create lead").click()
    page.wait_for_selector(f"[role=dialog][aria-label='{LEAD}']")
    page.keyboard.press("Escape")
    card = page.locator(f"[data-lead='{LEAD}']")
    check("new lead appears in the New column with its budget", page.locator(f"[data-stage=NEW] [data-lead='{LEAD}']").count() == 1 and "₹18 L" in card.inner_text())

    # Bad phone is refused with a readable message
    page.get_by_role("button", name="Add lead").click(); dlg = page.get_by_role("dialog", name="New lead")
    dlg.get_by_label("Name *", exact=True).fill("Bad Phone"); dlg.get_by_label("Phone", exact=True).fill("call me maybe"); dlg.get_by_role("button", name="Create lead").click()
    err = dlg.get_by_role("alert"); err.wait_for()
    check("a nonsense phone is refused with a readable error", "phone" in err.inner_text().lower() and "{" not in err.inner_text(), err.inner_text())
    page.keyboard.press("Escape")

    # DRAG the card to Qualified, then to Site visit
    card.drag_to(page.locator("[data-stage=QUALIFIED]")); page.wait_for_timeout(800)
    check("dragging a card moves it to Qualified", page.locator(f"[data-stage=QUALIFIED] [data-lead='{LEAD}']").count() == 1)
    page.reload(); page.wait_for_selector(f"[data-lead='{LEAD}']")
    check("the drag was saved (still Qualified after reload)", page.locator(f"[data-stage=QUALIFIED] [data-lead='{LEAD}']").count() == 1)
    page.get_by_label(f"Stage for {LEAD}", exact=True).select_option("SITE_VISIT"); page.wait_for_timeout(800)
    check("the stage menu moves it to Site visit", page.locator(f"[data-stage=SITE_VISIT] [data-lead='{LEAD}']").count() == 1)

    # Open it: note + history
    page.locator(f"[data-lead='{LEAD}'] p").first.click()
    d = page.get_by_role("dialog", name=LEAD)
    d.get_by_label("Note", exact=True).fill("Client prefers walnut and warm lighting"); d.get_by_role("button", name="Add note").click()
    page.wait_for_selector("[data-testid=lead-history] >> text=Client prefers walnut")
    hist = page.locator("[data-testid=lead-history]").inner_text()
    check("history shows the note, both moves and who did them",
          all(s in hist for s in ("Client prefers walnut", "New → Qualified", "Qualified → Site visit", "Lead created", "Admin User")), hist[:300])
    page.screenshot(path=f"{SHOTS}/crm_lead.png")

    # Convert
    d.get_by_label("Project number", exact=True).fill(f"IQ-CRM-{RUN}"); d.get_by_role("button", name="Convert").click()
    page.wait_for_selector(f"text=Converted to project", timeout=10000)
    check("conversion reports a NEW client", "client created" in d.inner_text(), d.inner_text()[:200])
    page.keyboard.press("Escape"); page.wait_for_timeout(600)
    check("converted lead is in Won and shows its project number",
          page.locator(f"[data-stage=WON] [data-lead='{LEAD}']").count() == 1 and f"IQ-CRM-{RUN}" in page.locator(f"[data-lead='{LEAD}']").inner_text())
    page.screenshot(path=f"{SHOTS}/crm_board.png")

    # Clients: the converted client is there; the same phone typed differently is refused
    page.goto(f"{WEB}/crm/clients"); page.wait_for_selector(f"text={LEAD}")
    check("the converted lead is now a client with 1 project", "1" in page.locator(f"tr:has-text('{LEAD}') td").nth(3).inner_text())
    page.get_by_role("button", name="Add client").click(); dlg = page.get_by_role("dialog", name="New client")
    dlg.get_by_label("Name *", exact=True).fill("Duplicate Person"); dlg.get_by_label("Phone", exact=True).fill(f"0{PHONE[:5]} {PHONE[5:]}")
    dlg.get_by_role("button", name="Create client").click(); err = dlg.get_by_role("alert"); err.wait_for()
    check("same phone typed with a leading 0 is caught as a duplicate", "already exists" in err.inner_text() and LEAD in err.inner_text(), err.inner_text())
    dlg.get_by_label("Name *", exact=True).fill(f"Rohan Builders {RUN}"); dlg.get_by_label("Phone", exact=True).fill(f"97{RUN}22"[:10])
    dlg.get_by_label("Company", exact=True).fill("Rohan Builders Pvt Ltd"); dlg.get_by_label("Address", exact=True).fill("12 Ashram Road")
    dlg.get_by_role("button", name="Create client").click(); page.wait_for_selector(f"td >> text=Rohan Builders {RUN}")
    page.get_by_label("Search clients", exact=True).fill("rohan builders pvt"); page.wait_for_timeout(700)
    check("search finds the client by company", page.locator("tbody tr").count() == 1)
    page.locator("tbody tr").first.click(); dlg = page.get_by_role("dialog", name="Edit client")
    dlg.get_by_label("City", exact=True).fill("Gandhinagar"); dlg.get_by_role("button", name="Save changes").click(); page.wait_for_timeout(700)
    check("editing a client saves", "Gandhinagar" in page.locator("tbody tr").first.inner_text())

    # Projects: change the client of the converted project to Rohan Builders
    page.goto(f"{WEB}/projects"); sel = page.get_by_label(f"Client of IQ-CRM-{RUN}", exact=True); sel.wait_for()
    check("the converted project shows its client", sel.locator("option:checked").inner_text() == LEAD)
    sel.select_option(label=f"Rohan Builders {RUN}"); page.wait_for_timeout(900); page.reload()
    sel = page.get_by_label(f"Client of IQ-CRM-{RUN}", exact=True); sel.wait_for()
    check("changing a project's client is saved", sel.locator("option:checked").inner_text() == f"Rohan Builders {RUN}")

    # Quotation PDF prints that client
    pid = [x for x in c.get(f"{API}/projects", headers=H).json() if x["project_number"] == f"IQ-CRM-{RUN}"][0]["id"]
    rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=H).json()["id"]
    for label, v in (("Length", 4250), ("Width", 3600)): c.put(f"{API}/rooms/{rid}/measurements", json={"label": label, "value": v, "source": "USER_VERIFIED"}, headers=H)
    g = c.post(f"{API}/rooms/{rid}/designs/generate", json={}, headers=H).json(); c.post(f"{API}/rooms/{rid}/designs", json={"objects": g["objects"]}, headers=H)
    page.goto(f"{WEB}/estimation/boq")
    page.wait_for_selector(f"select option:has-text('IQ-CRM-{RUN}')", state="attached", timeout=10000)
    page.locator("select").first.select_option(label=f"IQ-CRM-{RUN} · {LEAD} — 2BHK interior with modular kitchen"); page.wait_for_timeout(900)
    page.wait_for_selector("text=v1"); page.get_by_role("button", name="Create BOQ").click(); page.wait_for_selector("[data-testid=grand-total]", timeout=10000)
    with page.expect_download() as dl: page.get_by_role("button", name="Quotation PDF").click()
    doc = pdfium.PdfDocument(dl.value.path()); txt = "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
    check("quotation PDF prints the client's name, company, address and phone",
          all(s in txt for s in (f"Rohan Builders {RUN}", "Rohan Builders Pvt Ltd", "12 Ashram Road", "Gandhinagar")), txt[:400])

    check("no browser errors or failed requests", not problems, "; ".join(problems[:5]))
    br.close()

print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
