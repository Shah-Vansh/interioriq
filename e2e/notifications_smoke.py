"""Real-browser test of notifications with a REAL SMTP conversation: a tiny local mail server (127.0.0.1:2525, started here) receives what the
API's background worker sends. Covers: settings status + test email, emailing a quotation with its PDF (and marking it sent), WhatsApp click-to-chat
link, editable templates, an automatic payment receipt, a refused recipient that ends FAILED with the server's reason, and the project's Messages log.
The API must be started with SMTP_HOST=127.0.0.1 SMTP_PORT=2525 SMTP_SECURITY=none (e2e/run.sh does this)."""
import email, os, socketserver, sys, tempfile, threading, time
from email import policy
import httpx
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")   # override when 8000/3000 are taken
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]
INBOX: list = []


class SMTPHandler(socketserver.StreamRequestHandler):
    """Just enough SMTP (RFC 5321) for smtplib: EHLO, MAIL, RCPT (refuses *@fail.test with 550), DATA, RSET, NOOP, QUIT."""
    def w(self, s): self.wfile.write((s + "\r\n").encode())
    def handle(self):
        self.w("220 iq-test-smtp ready"); rcpts, sender = [], None
        while True:
            line = self.rfile.readline()
            if not line: return
            cmd = line.decode("utf-8", "replace").strip(); up = cmd.upper()
            if up.startswith(("EHLO", "HELO")): self.w("250-iq-test-smtp"); self.w("250-8BITMIME"); self.w("250 SMTPUTF8")
            elif up.startswith("MAIL FROM"): sender, rcpts = cmd, []; self.w("250 OK")
            elif up.startswith("RCPT TO"):
                if "fail.test" in cmd.lower(): self.w("550 5.1.1 No such user here")
                else: rcpts.append(cmd); self.w("250 OK")
            elif up == "DATA":
                self.w("354 End data with <CR><LF>.<CR><LF>"); data = b""
                while True:
                    l = self.rfile.readline()
                    if l in (b".\r\n", b".\n", b""): break
                    data += l[1:] if l.startswith(b"..") else l
                INBOX.append(email.message_from_bytes(data, policy=policy.default)); self.w("250 OK queued")
            elif up in ("RSET", "NOOP"): self.w("250 OK")
            elif up == "QUIT": self.w("221 Bye"); return
            else: self.w("502 Not implemented")


socketserver.ThreadingTCPServer.allow_reuse_address = True
smtp = socketserver.ThreadingTCPServer(("127.0.0.1", 2525), SMTPHandler); threading.Thread(target=smtp.serve_forever, daemon=True).start()

def wait_mail(pred, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        hit = next((x for x in INBOX if pred(x)), None)
        if hit: return hit
        time.sleep(0.5)
    return None

c = httpx.Client(timeout=30)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
PN = f"IQ-MSG-{RUN}"; CLIENT = f"Ananya Rao {RUN}"; CMAIL = f"ananya{RUN}@client.test"
cl = c.post(f"{API}/clients", json={"name": CLIENT, "phone": f"95{RUN}66"[:10], "email": CMAIL}, headers=H).json()
pid = c.post(f"{API}/projects", json={"project_number": PN, "name": "Rao villa", "client_id": cl["id"]}, headers=H).json()["id"]
rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": "Master bedroom", "room_type": "BEDROOM"}, headers=H).json()["id"]
for l, v in (("Length", 4250), ("Width", 3600)): c.put(f"{API}/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=H)
v = c.post(f"{API}/rooms/{rid}/designs", json={"objects": [dict(id="w", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)]}, headers=H).json()["version"]
boq = c.post(f"{API}/rooms/{rid}/designs/{v}/boq", json={"gst_enabled": False}, headers=H).json(); QT = boq["quotation_no"]

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

with sync_playwright() as p:
    br = p.chromium.launch(); ctx = br.new_context(viewport={"width": 1600, "height": 1000}, accept_downloads=True)
    ctx.route("https://wa.me/**", lambda r: r.fulfill(status=200, body="<html><body>WhatsApp stub</body></html>", content_type="text/html"))   # never leave the machine
    page = ctx.new_page(); page.set_default_timeout(60000); page.set_default_navigation_timeout(90000); problems = []
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" and "409" not in m.text and "422" not in m.text else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and r.status not in (409, 422) and "wa.me" not in r.url else None)
    page.goto(f"{WEB}/login"); page.fill("#email", "admin@interioriq.com"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")

    # Settings → Notifications: ready + test email over real SMTP
    page.goto(f"{WEB}/settings/notifications"); page.wait_for_selector("[data-testid=smtp-ready]")
    check("settings show email ready with the sender", "studio@interioriq.test" in page.get_by_test_id("smtp-ready").inner_text())
    page.get_by_label("Test email address").fill(f"owner{RUN}@studio.test"); page.get_by_role("button", name="Send test").click(); page.wait_for_selector("[role=status] >> text=Test email sent")
    check("test email reaches the mail server", wait_mail(lambda m: f"owner{RUN}@studio.test" in m["To"] and "Test email" in m["Subject"]) is not None)

    # template edit shows up in the send drawer
    page.get_by_label("Template subject").fill("Your quotation $quotation_no — $company"); page.get_by_role("button", name="Save template").click(); page.wait_for_selector("text=Template saved")

    # Quotations: email the quotation with PDF + mark it sent
    page.goto(f"{WEB}/estimation/quotations"); row = page.locator(f"[data-quote='{QT}']"); row.wait_for()
    row.get_by_role("button", name="Send (quotation)").click(); d = page.get_by_role("dialog", name="Send quotation")
    page.wait_for_selector("[aria-label=Subject]")
    check("send drawer is prefilled from the edited template and the client's email",
          d.get_by_label("To", exact=True).input_value() == CMAIL and d.get_by_label("Subject", exact=True).input_value().startswith(f"Your quotation {QT}"))
    d.get_by_role("button", name="Send email").click(); page.wait_for_selector(f"[data-quote='{QT}'] [data-status=SENT]")
    mail = wait_mail(lambda m: CMAIL in m["To"] and QT in m["Subject"])
    pdfs = [a for a in mail.iter_attachments() if a.get_content_type() == "application/pdf"] if mail else []
    check("the quotation email arrives with its PDF attached", bool(pdfs) and pdfs[0].get_content()[:4] == b"%PDF" and QT in pdfs[0].get_filename())
    check("sending also marked the quotation Sent", row.locator("[data-status=SENT]").count() == 1)
    check("the email body has the amount and the portal link", mail is not None and "/client-portal" in mail.get_body(("plain",)).get_content())

    # WhatsApp click-to-chat
    row.get_by_role("button", name="Send (quotation)").click(); d = page.get_by_role("dialog", name="Send quotation")
    d.get_by_role("tab", name="WhatsApp").click(); page.wait_for_timeout(300)
    check("WhatsApp number is prefilled with the client's phone", d.get_by_label("WhatsApp number", exact=True).input_value() == cl["phone"])
    with ctx.expect_page() as pop: d.get_by_role("button", name="Open WhatsApp").click()
    wa = pop.value; wa.wait_for_load_state()
    check("WhatsApp opens wa.me with the number and the typed message", wa.url.startswith(f"https://wa.me/91{cl['phone'][-10:]}?text=") and QT in __import__("urllib.parse").parse.unquote(wa.url))
    wa.close()

    # automatic payment receipt
    page.goto(f"{WEB}/settings/notifications"); page.wait_for_selector("[data-testid=auto-switches]")
    sw = page.get_by_role("switch", name="Email a payment receipt when a payment is recorded")
    if sw.get_attribute("aria-checked") != "true": sw.click()
    try: page.wait_for_function("() => document.querySelector('[role=switch][aria-label=\"Email a payment receipt when a payment is recorded\"]')?.getAttribute('aria-checked') === 'true'", timeout=15000)
    except Exception: pass
    check("automatic payment receipt switched on", sw.get_attribute("aria-checked") == "true")
    c.post(f"{API}/boqs/{boq['id']}/status", json={"status": "APPROVED"}, headers=H)
    page.goto(f"{WEB}/projects/{pid}"); page.get_by_role("button", name="Record payment").click(); dd = page.get_by_role("dialog", name="Record payment")
    dd.get_by_label("Amount (₹)", exact=True).fill("50000"); dd.get_by_label("Reference (UTR / cheque no.)", exact=True).fill(f"UTR{RUN}"); dd.get_by_role("button", name="Save payment").click()
    receipt = wait_mail(lambda m: CMAIL in m["To"] and "Payment received" in m["Subject"])
    check("the client automatically gets a payment receipt", receipt is not None and f"UTR{RUN}" in receipt.get_body(("plain",)).get_content())

    # refused recipient → FAILED with the server's reason (after the worker's retries)
    page.reload(); page.locator("[data-quote]").first.wait_for(state="attached") if page.locator("[data-quote]").count() else None
    page.get_by_role("button", name="Send (quotation)").first.click(); d = page.get_by_role("dialog", name="Send quotation")
    d.get_by_label("To", exact=True).fill(f"nobody{RUN}@fail.test"); d.get_by_role("button", name="Send email").click(); page.wait_for_timeout(500)
    ok = False
    for _ in range(30):
        if any(x["status"] == "FAILED" and "fail.test" in x["to"] for x in c.get(f"{API}/messages", params={"project_id": pid}, headers=H).json()): ok = True; break
        time.sleep(1)
    check("a refused address ends FAILED after retries", ok)
    page.reload(); page.wait_for_selector("[data-testid=messages]")
    log = page.get_by_test_id("messages").inner_text()
    check("Messages log shows sent emails, the WhatsApp link, the auto receipt and the failure reason",
          "sent" in log and "Opened in WhatsApp" in log and "auto" in log and "No such user" in log and page.get_by_role("button", name="Retry").count() >= 1, log[:400])
    page.screenshot(path=f"{SHOTS}/messages.png", full_page=True)
    check("no browser errors or failed requests", not problems, "; ".join(problems[:5]))
    br.close()

c.put(f"{API}/notifications/auto", json={"PAYMENT": False}, headers=H); c.delete(f"{API}/notifications/templates/QUOTATION", headers=H)
smtp.shutdown()
print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
