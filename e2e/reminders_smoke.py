"""Real-browser test of M25 follow-up reminders with a REAL SMTP conversation (local mail server on 127.0.0.1:2525, started here):
switch reminders on in Settings → Notifications, 'Send what's due now' → the assignee receives the 'due soon' email (lead phone + WhatsApp
link) and the morning summary; the reminder log lists them; CRM → Follow-ups shows 'Reminder emailed'; WhatsApp to the lead and a WhatsApp
reminder to the assignee open click-to-chat links (stubbed, nothing leaves the machine) and are written to the lead history.
The API must be started with SMTP_HOST=127.0.0.1 SMTP_PORT=2525 SMTP_SECURITY=none (e2e/run.sh does this)."""
import email, os, socketserver, sys, tempfile, threading, time
from datetime import datetime, timedelta, timezone
from email import policy
from urllib.parse import unquote
import httpx
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]
INBOX: list = []


class SMTPHandler(socketserver.StreamRequestHandler):
    """Just enough SMTP for smtplib: EHLO, MAIL, RCPT, DATA, RSET, NOOP, QUIT."""
    def w(self, s): self.wfile.write((s + "\r\n").encode())
    def handle(self):
        self.w("220 iq-test-smtp ready")
        while True:
            line = self.rfile.readline()
            if not line: return
            up = line.decode("utf-8", "replace").strip().upper()
            if up.startswith(("EHLO", "HELO")): self.w("250-iq-test-smtp"); self.w("250-8BITMIME"); self.w("250 SMTPUTF8")
            elif up.startswith(("MAIL FROM", "RCPT TO")) or up in ("RSET", "NOOP"): self.w("250 OK")
            elif up == "DATA":
                self.w("354 End data with <CR><LF>.<CR><LF>"); data = b""
                while True:
                    l = self.rfile.readline()
                    if l in (b".\r\n", b".\n", b""): break
                    data += l[1:] if l.startswith(b"..") else l
                INBOX.append(email.message_from_bytes(data, policy=policy.default)); self.w("250 OK queued")
            elif up == "QUIT": self.w("221 Bye"); return
            else: self.w("502 Not implemented")


socketserver.ThreadingTCPServer.allow_reuse_address = True
smtp = socketserver.ThreadingTCPServer(("127.0.0.1", 2525), SMTPHandler); threading.Thread(target=smtp.serve_forever, daemon=True).start()


def wait_mail(pred, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        hit = next((x for x in INBOX if pred(x)), None)
        if hit: return hit
        time.sleep(0.5)
    return None


def body(msg): return msg.get_body(("plain",)).get_content()


c = httpx.Client(timeout=30)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
users = {u["email"]: u for u in c.get(f"{API}/users", headers=H).json()}
PRIYA = users["priya@interioriq.com"]
LEAD = f"Reminder Rhea {RUN}"; PHONE = f"98{RUN}33"[:10]
lead = c.post(f"{API}/leads", json={"name": LEAD, "phone": PHONE, "requirement": "2BHK interiors"}, headers=H).json()
c.post(f"{API}/leads/{lead['id']}/assign", json={"user_id": PRIYA["id"]}, headers=H).raise_for_status()
fu = c.post(f"{API}/leads/{lead['id']}/followups", json={"due_at": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(), "kind": "CALL",
                                                          "note": f"Share the kitchen options {RUN}"}, headers=H).json()
c.put(f"{API}/notifications/followup-reminders", json={"enabled": False, "before_minutes": 30, "digest": True, "digest_hour": 9}, headers=H).raise_for_status()

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

with sync_playwright() as p:
    br = p.chromium.launch(); ctx = br.new_context(viewport={"width": 1600, "height": 1000})
    ctx.route("https://wa.me/**", lambda r: r.fulfill(status=200, body="<html><body>WhatsApp stub</body></html>", content_type="text/html"))   # never leave the machine
    page = ctx.new_page(); page.set_default_timeout(60000); page.set_default_navigation_timeout(90000); problems = []
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" and "409" not in m.text and "422" not in m.text else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and r.status not in (409, 422) and "wa.me" not in r.url else None)
    page.goto(f"{WEB}/login"); page.fill("#email", "admin@interioriq.com"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")

    # Settings → Notifications: switch reminders on, run what's due
    page.goto(f"{WEB}/settings/notifications"); rs = page.get_by_test_id("reminder-settings"); rs.wait_for()
    sw = rs.get_by_role("switch", name="Send follow-up reminders by email")
    check("reminders are off until switched on", sw.get_attribute("aria-checked") == "false" and rs.get_by_label("Remind before").is_disabled())
    sw.click(); page.wait_for_function("() => document.querySelector('[role=switch][aria-label=\"Send follow-up reminders by email\"]').getAttribute('aria-checked') === 'true'")
    rs.get_by_label("Remind before").select_option("30"); rs.get_by_label("Morning summary time").select_option("9"); page.wait_for_timeout(800)
    s = c.get(f"{API}/notifications/followup-reminders", headers=H).json()
    check("settings saved on the server", s["enabled"] and s["before_minutes"] == 30 and s["digest"] and s["digest_hour"] == 9, str({k: s[k] for k in ("enabled", "before_minutes", "digest_hour")}))
    rs.get_by_role("button", name="Send what's due now").click(); rs.get_by_text("what was due has been queued").wait_for()
    rem = wait_mail(lambda x: LEAD in (x["Subject"] or "") and x["Subject"].startswith("Reminder:"))
    check("'due soon' email reached Priya over real SMTP", rem is not None and "priya@interioriq.com" in rem["To"], rem["To"] if rem else "no mail")
    if rem:
        b = body(rem)
        check("reminder has the phone, note, WhatsApp link and a link to the list", PHONE in b and f"Share the kitchen options {RUN}" in b and "https://wa.me/91" in b and "/crm/followups" in b, b[:300])
    dig = wait_mail(lambda x: (x["Subject"] or "").startswith("Your follow-ups for") and "priya@interioriq.com" in x["To"] and LEAD in body(x))
    # the scheduler thread may have sent today's summary before the click; either way Priya has one listing this lead
    check("morning summary lists the follow-up", dig is not None and "TODAY (" in body(dig) if dig else False)
    page.reload(); rs = page.get_by_test_id("reminder-settings"); rs.wait_for(); log = page.get_by_test_id("reminder-log")
    log.locator("summary").click()
    check("reminder log shows the reminder email", "Follow-up reminder to priya@interioriq.com" in log.inner_text(), log.inner_text()[:300])
    page.get_by_role("tab", name="WhatsApp to a lead").click()
    check("templates: reminder tabs exist; the WhatsApp one has no email subject",
          page.get_by_role("tab", name="Morning summary").count() == 1 and page.get_by_label("Template subject").count() == 0)
    page.screenshot(path=f"{SHOTS}/reminder_settings.png", full_page=True)

    # CRM → Follow-ups: 'Reminder emailed', WhatsApp the lead, remind Priya on WhatsApp
    page.goto(f"{WEB}/crm/followups"); page.get_by_label("Whose follow-ups").select_option("team")
    row = page.locator(f"[data-followup-row='{LEAD}']")
    for tab in ("Today", "Upcoming"):
        if row.count(): break
        page.get_by_role("tab", name=tab).click(); page.wait_for_timeout(1200)
    row.wait_for()
    check("follow-up row says the reminder was emailed", row.get_by_test_id("reminded").count() == 1)
    row.get_by_role("button", name=f"WhatsApp {LEAD}").click(); d = page.get_by_role("dialog", name="WhatsApp"); d.wait_for()
    page.wait_for_function("() => (document.querySelector('[aria-label=\"WhatsApp message\"]')?.value || '').length > 10")
    check("WhatsApp draft to the lead is prefilled", d.get_by_label("WhatsApp number").input_value() == PHONE and LEAD in d.get_by_label("WhatsApp message").input_value())
    with ctx.expect_page() as pop: d.get_by_role("button", name="Open WhatsApp").click()
    url = unquote(pop.value.url)
    check("WhatsApp opens for the lead with the message typed", url.startswith(f"https://wa.me/91{PHONE}") and LEAD in url, url[:120])
    pop.value.close(); d.wait_for(state="detached")
    row.get_by_role("button", name="Remind Priya Mehta on WhatsApp").click(); d = page.get_by_role("dialog", name="WhatsApp"); d.wait_for()
    page.wait_for_function("() => (document.querySelector('[aria-label=\"WhatsApp message\"]')?.value || '').length > 10")
    if not d.get_by_label("WhatsApp number").input_value():
        check("missing assignee phone is explained", "Settings → Users" in d.get_by_test_id("wa-problem").inner_text())
        d.get_by_label("WhatsApp number").fill("98250 22222")
    check("WhatsApp reminder text names the lead and the time", LEAD in d.get_by_label("WhatsApp message").input_value())
    with ctx.expect_page() as pop: d.get_by_role("button", name="Open WhatsApp").click()
    url = unquote(pop.value.url)
    check("WhatsApp reminder opens for Priya", url.startswith("https://wa.me/91") and LEAD in url, url[:120])
    pop.value.close(); d.wait_for(state="detached")
    page.screenshot(path=f"{SHOTS}/reminder_followups.png", full_page=True)

    # lead history has both WhatsApp entries; the drawer offers the same buttons
    hist = " ".join(a.get("text") or "" for a in c.get(f"{API}/leads/{lead['id']}", headers=H).json()["activity"])
    check("lead history records both WhatsApp messages", "WhatsApp opened to the lead" in hist and "WhatsApp reminder opened for Priya Mehta" in hist)
    page.goto(f"{WEB}/crm/leads"); page.locator(f"[data-lead='{LEAD}'] p", has_text=LEAD).click(); fx = page.get_by_test_id("lead-followups"); fx.wait_for()
    try: fx.get_by_role("button", name="Remind Priya Mehta on WhatsApp").wait_for(timeout=15000)
    except Exception: page.screenshot(path=f"{SHOTS}/reminder_drawer_fail.png", full_page=True)
    check("lead drawer has WhatsApp + Remind on the follow-up", fx.get_by_role("button", name="WhatsApp the lead").count() == 1
          and fx.get_by_role("button", name="Remind Priya Mehta on WhatsApp").count() == 1)
    # M31: a weekly call repeats when marked done
    fx.get_by_label("Follow-up type").select_option("CALL"); fx.get_by_label("Follow-up note").fill(f"Weekly nudge {RUN}"); fx.get_by_label("Follow-up repeat").select_option("7")
    fx.get_by_role("button", name="Schedule follow-up").click(); fx.get_by_test_id("repeat-tag").first.wait_for()
    check("repeating follow-up shows 'every week'", "every week" in fx.get_by_test_id("repeat-tag").first.inner_text())
    weekly = fx.locator("li", has_text=f"Weekly nudge {RUN}")
    weekly.get_by_role("button", name="Done Call").click(); dd = page.get_by_role("dialog", name="Follow-up done"); dd.wait_for()
    check("done dialog says the next one is booked automatically", dd.get_by_test_id("repeat-note").count() == 1 and dd.get_by_label("Next follow-up time").count() == 0)
    dd.get_by_label("Outcome").fill("Left a message"); dd.get_by_role("button", name="Save").click(); dd.wait_for(state="detached"); page.wait_for_timeout(1000)
    opn = [f for f in c.get(f"{API}/leads/{lead['id']}", headers=H).json()["follow_ups"] if f["status"] == "OPEN" and f["note"] == f"Weekly nudge {RUN}"]
    check("next weekly call was booked, still repeating", len(opn) == 1 and opn[0]["repeat_days"] == 7)
    check("no page errors", not problems, "; ".join(problems[:5]))
    br.close()

c.put(f"{API}/notifications/followup-reminders", json={"enabled": False}, headers=H)
smtp.shutdown()
print(f"\n{'ALL PASSED' if not fails else f'{len(fails)} FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
