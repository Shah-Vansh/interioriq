"""Real-browser test of upload -> OCR -> review -> apply, including the 'OCR never beats a verified value' rule."""
import sys, tempfile, os
import httpx
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")   # override when 8000/3000 are taken
def font(sz):
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"):
        try: return ImageFont.truetype(f, sz)
        except Exception: pass
    return ImageFont.load_default()

tmp = tempfile.mkdtemp(); plan = os.path.join(tmp, "plan.png"); fake = os.path.join(tmp, "not_an_image.png")
img = Image.new("RGB", (1400, 900), "white"); d = ImageDraw.Draw(img); d.rectangle([150, 150, 1250, 750], outline="black", width=6)
for text, xy, sz in [("MASTER BEDROOM", (520, 380), 44), ("Length: 4250 mm", (480, 90), 40), ("Width: 3600 mm", (480, 200), 40), ("Ceiling height: 2750 mm", (430, 800), 34)]:
    d.text(xy, text, fill="black", font=font(sz))
img.save(plan); open(fake, "wb").write(b"this is plain text pretending to be a picture")

c = httpx.Client(timeout=30)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
pid = c.post(f"{API}/projects", json={"project_number": "IQ-DOC", "name": "Docs E2E"}, headers=H).json()["id"]
rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": "Master Bedroom", "room_type": "MASTER_BEDROOM"}, headers=H).json()["id"]
c.put(f"{API}/rooms/{rid}/measurements", json={"label": "Length", "value": 4300, "source": "USER_VERIFIED"}, headers=H)   # a person already verified Length = 4300

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

with sync_playwright() as p:
    br = p.chromium.launch(); page = br.new_page(viewport={"width": 1500, "height": 1000}); problems = []
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" and "status of 415" not in m.text else None)
    page.goto(f"{WEB}/login"); page.fill("input[type=password]", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")

    def pick_project():
        page.wait_for_selector("select option:has-text('IQ-DOC')", state="attached", timeout=10000)
        page.locator("select").first.select_option(label="IQ-DOC · Docs E2E"); page.wait_for_timeout(800)

    page.goto(f"{WEB}/survey/documents"); pick_project()
    check("sidebar highlights exactly one link", page.locator("nav a.bg-amber-50").count() == 1, str(page.locator("nav a.bg-amber-50").all_inner_texts()))
    page.set_input_files("[data-testid=file-input]", plan)
    page.wait_for_selector("tbody tr", timeout=120000)  # the review table only exists once OCR has finished (OCR speed depends on the machine)
    page.screenshot(path="/tmp/shots/doc_review.png")
    check("OCR finished and the review table appeared", True, page.locator("text=/Read by .* page/").first.inner_text())
    rows = page.locator("tbody tr"); n = rows.count()
    labels = [rows.nth(i).locator("select").input_value() for i in range(n)]
    check("labels were recognised from the text", {"Length", "Width", "Ceiling Height"} <= set(labels), str(labels))
    vals = {rows.nth(i).locator("select").input_value(): rows.nth(i).locator("input[type=number]").input_value() for i in range(n)}
    check("values read correctly", vals.get("Length") == "4250" and vals.get("Width") == "3600" and vals.get("Ceiling Height") == "2750", str(vals))
    check("rows with no label are NOT pre-ticked", all(not rows.nth(i).locator("input[type=checkbox]").is_checked() for i in range(n) if labels[i] == ""))

    page.get_by_role("button", name="Apply 3 to room").click(); page.wait_for_selector("text=/applied · /", timeout=8000)
    check("applying reports 2 applied, 1 kept", page.get_by_text("2 applied · 1 kept as-is").count() == 1)
    check("verified Length was protected, with the reason shown", page.get_by_text("Kept existing USER_VERIFIED value (4300 mm)").count() == 1)
    page.screenshot(path="/tmp/shots/doc_applied.png")

    page.goto(f"{WEB}/survey/rooms"); pick_project(); page.wait_for_selector("td:has-text('Ceiling Height')")
    row = lambda name: page.locator(f"tbody tr:has(td:text-is('{name}'))")
    check("Rooms page: Length stays 4,300 USER_VERIFIED", "4,300" in row("Length").inner_text() and "USER_VERIFIED" in row("Length").inner_text())
    check("Rooms page: Width is 3,600 from OCR", "3,600" in row("Width").inner_text() and "OCR" in row("Width").inner_text())
    check("Rooms page: Ceiling Height is 2,750 from OCR", "2,750" in row("Ceiling Height").inner_text() and "OCR" in row("Ceiling Height").inner_text())

    page.goto(f"{WEB}/survey/documents"); pick_project()
    page.set_input_files("[data-testid=file-input]", plan); page.wait_for_selector("text=/already uploaded/", timeout=8000)
    check("re-uploading the same file is detected", True)
    page.set_input_files("[data-testid=file-input]", fake); page.wait_for_selector("text=/Unsupported file type/", timeout=8000)
    check("a disguised text file is rejected with a clear message", True)
    br.close()

check("no unexpected browser errors", not problems, str(problems) if problems else "")
print("RESULT:", "ALL PASSED" if not fails else f"FAILED: {fails}"); sys.exit(1 if fails else 0)
