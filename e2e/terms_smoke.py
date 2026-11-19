"""Real-browser test of M26 payment schedule + terms: edit the company default (live 100% check), a new quotation starts with it, edit the
quotation's own schedule on the BOQ screen (server amounts), the quotation PDF prints it, approval locks it, the payment tracker follows it."""
import os, sys, tempfile, time
import httpx
import pypdfium2 as pdfium
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]
c = httpx.Client(timeout=60)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
c.delete(f"{API}/settings/quote-terms", headers=H)
PN = f"IQ-TRM-{RUN}"
cl = c.post(f"{API}/clients", json={"name": f"Terms Tara {RUN}", "phone": f"93{RUN}44"[:10]}, headers=H).json()
pid = c.post(f"{API}/projects", json={"project_number": PN, "name": "Terms villa", "client_id": cl["id"]}, headers=H).json()["id"]
rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": "Master bedroom", "room_type": "BEDROOM"}, headers=H).json()["id"]
for l, v in (("Length", 4250), ("Width", 3600)): c.put(f"{API}/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=H)
ver = c.post(f"{API}/rooms/{rid}/designs", json={"objects": [dict(id="w", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)]}, headers=H).json()["version"]

def pdf_text(b): d = pdfium.PdfDocument(b); return "\n".join(d[i].get_textpage().get_text_range() for i in range(len(d)))

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

with sync_playwright() as p:
    br = p.chromium.launch(); page = br.new_page(viewport={"width": 1600, "height": 1100}); problems = []
    page.set_default_timeout(60000); page.set_default_navigation_timeout(90000)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" and "409" not in m.text and "422" not in m.text else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and r.status not in (409, 422) else None)
    page.goto(f"{WEB}/login"); page.fill("#email", "admin@interioriq.com"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")

    # company default: three milestones, live total check
    page.goto(f"{WEB}/settings/company"); d = page.get_by_test_id("default-terms"); d.wait_for()
    check("default starts as the standard 5 milestones = 100%", d.get_by_test_id("pct-total").inner_text() == "100%" and d.get_by_label("Milestone 5 name").count() == 1)
    for i in (5, 4): d.get_by_label(f"Remove milestone {i}").click()
    d.get_by_label("Milestone 1 name").fill("Booking advance"); d.get_by_label("Milestone 1 percent").fill("40")
    d.get_by_label("Milestone 2 name").fill("Before delivery"); d.get_by_label("Milestone 2 percent").fill("35")
    d.get_by_label("Milestone 3 name").fill("On handover"); d.get_by_label("Milestone 3 percent").fill("20")
    check("wrong total shown and Save disabled", d.get_by_test_id("pct-total").inner_text() == "95%" and d.get_by_role("button", name="Save default").is_disabled())
    d.get_by_label("Milestone 3 percent").fill("25")
    d.get_by_label("Terms and conditions").fill(f"Booking amount is adjusted in the final bill {RUN}.\nPrices include delivery within the city.")
    d.get_by_role("button", name="Save default").click(); page.get_by_text("Default saved").wait_for()
    sv = c.get(f"{API}/settings/quote-terms", headers=H).json()
    check("default saved on the server", [r["pct"] for r in sv["schedule"]] == ["40", "35", "25"] and len(sv["terms"]) == 2, str(sv["schedule"]))

    # new quotation starts with it; edit its own schedule on the BOQ screen
    b = c.post(f"{API}/rooms/{rid}/designs/{ver}/boq", json={"gst_enabled": False}, headers=H).json()
    page.goto(f"{WEB}/estimation/boq")
    page.wait_for_selector(f"select option:has-text('{PN}')", state="attached"); page.locator("select").first.select_option(label=f"{PN} · Terms villa"); page.wait_for_timeout(900)
    page.locator("p.font-semibold", has_text=b["quotation_no"]).first.click()
    qt = page.get_by_test_id("quote-terms"); qt.wait_for()
    check("quotation shows the default schedule with server amounts", "Booking advance" in qt.inner_text() and "40%" in qt.inner_text() and "Rs." in qt.inner_text())
    qt.get_by_role("button", name="Edit").click(); ed = qt.get_by_test_id("terms-editor")
    ed.get_by_label("Remove milestone 3").click(); ed.get_by_label("Milestone 2 name").fill("Balance on installation"); ed.get_by_label("Milestone 2 percent").fill("60")
    ed.get_by_role("button", name="Save for this quotation").click(); qt.get_by_text("Saved — the quotation PDF").wait_for()
    t = c.get(f"{API}/boqs/{b['id']}/terms", headers=H).json()
    check("quotation's own schedule saved; amounts sum to the total", [r["label"] for r in t["schedule"]] == ["Booking advance", "Balance on installation"]
          and sum(float(r["amount"]) for r in t["schedule"]) == float(b["totals"]["grand_total"]))
    pdf = pdf_text(c.get(f"{API}/boqs/{b['id']}/quotation.pdf", headers=H).content)
    check("quotation PDF prints the edited schedule and terms", "Balance on installation" in pdf and f"adjusted in the final bill {RUN}" in pdf and "Agreement signing" not in pdf)
    page.screenshot(path=f"{SHOTS}/quote_terms.png", full_page=True)

    # approval locks it; payments follow it
    c.post(f"{API}/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=H)
    page.reload(); page.wait_for_selector(f"select option:has-text('{PN}')", state="attached"); page.locator("select").first.select_option(label=f"{PN} · Terms villa")
    page.wait_for_timeout(900); page.locator("p.font-semibold", has_text=b["quotation_no"]).first.click()
    qt = page.get_by_test_id("quote-terms"); qt.wait_for(); page.wait_for_timeout(800)
    check("approved quotation: no Edit, reason shown", qt.get_by_role("button", name="Edit").count() == 0 and "approved" in qt.inner_text())
    pay = c.get(f"{API}/projects/{pid}/payments", headers=H).json()
    check("payment tracker uses the quotation's milestones", [x["stage"] for x in pay["schedule"]] == ["Booking advance", "Balance on installation"])
    check("no page errors", not problems, "; ".join(problems[:5]))
    br.close()

c.delete(f"{API}/settings/quote-terms", headers=H)
print(f"\n{'ALL PASSED' if not fails else f'{len(fails)} FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
