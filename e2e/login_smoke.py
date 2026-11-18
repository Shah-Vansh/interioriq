"""Login must always either work or say exactly what is wrong — never spin or sit on 'Loading…' forever."""
import os, socket, sys, threading, time
from playwright.sync_api import sync_playwright

WEB = os.environ.get("IQ_WEB", "http://localhost:3000"); fails = []   # override when 3000 is taken
PORT = WEB.rsplit(":", 1)[1]
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

def to_login(page):
    page.goto(f"{WEB}/login"); page.wait_for_selector("#password")

with sync_playwright() as p:
    br = p.chromium.launch()
    def new(init=None):
        ctx = br.new_context(viewport={"width": 1200, "height": 800}); pg = ctx.new_page()
        if init: pg.add_init_script(init)
        return pg

    # 1. both ways of opening the site work (the site picks the API address from the address bar; CORS allows both)
    for origin in (f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"):
        pg = new(); pg.goto(f"{origin}/login"); pg.wait_for_selector("#password")
        pg.wait_for_selector("text=Backend connected", timeout=8000)
        pg.fill("#password", "ChangeMe123!"); pg.click("button:has-text('Sign in')")
        try: pg.wait_for_url("**/dashboard", timeout=15000); pg.wait_for_selector("h1", timeout=8000); ok = True
        except Exception: ok = False
        check(f"login works when opened as {origin}", ok)

    # 2. wrong password -> a clear message, no spinner left behind
    pg = new(); to_login(pg); pg.fill("#password", "wrong-password"); pg.click("button:has-text('Sign in')")
    pg.wait_for_selector("text=Incorrect email or password", timeout=8000)
    check("wrong password shows 'Incorrect email or password' and stops spinning", pg.locator("button svg.animate-spin").count() == 0)

    # 3. production build must NOT print the dev password on the login page
    expect_hint = os.environ.get("E2E_DEV_SERVER") == "1"      # `npm run dev` shows the local dev login; production builds must not
    check("dev password hint is " + ("shown in dev mode" if expect_hint else "hidden in production builds"), (pg.locator("[data-testid=dev-hint]").count() == 1) == expect_hint)

    # 4. backend down / unreachable -> immediate, accurate explanation
    pg = new(); pg.route("**/api/**", lambda r: r.abort()); to_login(pg)
    pg.wait_for_selector("text=The backend is not reachable", timeout=8000); check("login page warns when the backend is unreachable", True)
    pg.fill("#password", "ChangeMe123!"); pg.click("button:has-text('Sign in')"); pg.wait_for_selector("text=Cannot reach the API", timeout=8000)
    check("sign-in explains the problem and stops spinning", pg.locator("button svg.animate-spin").count() == 0)

    # 5. browser blocks localStorage (IDE preview panes, strict privacy modes): login must still work, with a visible notice
    pg = new("Object.defineProperty(window,'localStorage',{get(){throw new DOMException('blocked','SecurityError')}});"
             "Object.defineProperty(window,'sessionStorage',{get(){throw new DOMException('blocked','SecurityError')}});")
    to_login(pg); pg.fill("#password", "ChangeMe123!"); pg.click("button:has-text('Sign in')")
    try: pg.wait_for_url("**/dashboard", timeout=15000); pg.wait_for_selector("h1", timeout=8000); ok = True
    except Exception: ok = False
    check("login still works when storage is blocked", ok)
    check("...and the user is told why they'd be signed out on reload", pg.get_by_text("blocking local storage").count() == 1)

    # 6. unauthenticated visitor to a protected page ends up on the login form (not stuck on 'Loading…')
    pg = new(); pg.goto(f"{WEB}/survey/documents")
    try: pg.wait_for_url("**/login", timeout=15000); ok = True
    except Exception: ok = False
    check("protected page redirects to /login", ok)

    # 7. the exact reported symptom: a server that accepts the connection but never answers. A local "black hole" socket does exactly that.
    hole = socket.socket(); hole.bind(("127.0.0.1", 0)); hole.listen(16); held = []
    def accept_and_ignore():
        while True:
            try: held.append(hole.accept()[0])
            except OSError: return
    threading.Thread(target=accept_and_ignore, daemon=True).start()
    pg = new(); to_login(pg)
    pg.route("**/api/auth/login", lambda r: r.continue_(url=f"http://127.0.0.1:{hole.getsockname()[1]}/api/auth/login"))
    pg.fill("#password", "ChangeMe123!"); pg.click("button:has-text('Sign in')"); t0 = time.time()
    spinning = pg.locator("button svg.animate-spin").count() == 1
    pg.wait_for_selector("text=did not answer in time", timeout=30000)
    check("a hung server ends with a message instead of spinning forever", spinning and pg.locator("button svg.animate-spin").count() == 0, f"after {time.time()-t0:.0f}s")
    hole.close()
    br.close()

print("RESULT:", "ALL PASSED" if not fails else f"FAILED: {fails}"); sys.exit(1 if fails else 0)
