# InteriorIQ

A local, zero-cost platform for turnkey interior projects: lead → survey → design → 3D → CAD → BOQ → quotation → procurement →
manufacturing → delivery → installation → QC → handover, on real data.

**Highlights**
- CRM with lead follow-ups (email + WhatsApp reminders), client portal, project teams and role-based access
- Room survey with OCR of drawings (PDF text layer / RapidOCR), doors & windows
- Rule-based layouts for bedroom, living, dining, kitchen, study, bathroom and utility, validated with Shapely; a design chat adjusts them
- Whole-home design: every room type (verandah, foyer, living, dining, kitchen, bedrooms, bathrooms, wash area, pooja, store), one style for
  the whole home (feature walls, ceilings, floors, curtains, decor), rooms on one house plan, the whole home in 3D, a design presentation PDF
- Realistic 3D editor (React Three Fiber) with free rotation, colours, sunlight, ambient occlusion and path-traced photo renders;
  L-shaped / odd rooms, sloped ceilings, beams and columns; DXF drawings (plan, ceiling, electrical, elevations)
- Working drawings for the site team (A3, feet-inches): light detail, room plans and elevations, bed, wardrobe and kitchen details;
  shop drawings and cutting lists per work order
- Catalogue with photos, Excel import, price/stock ledgers and per-supplier quotes; BOQ + quotation PDFs (₹, Gujarati/Hindi, editable payment terms);
  optional GST invoices + credit notes, purchase orders, payables, profitability, Tally export
- Decimal-only money on the server; append-only design history; Alembic migrations; optional Celery workers

**Stack:** FastAPI · SQLAlchemy · Alembic · SQLite (Postgres via `DATABASE_URL`) · Next.js 14 · Tailwind · Three.js · Playwright

## Run
    # terminal 1                          # terminal 2
    cd apps/api                           cd apps/web
    pip install -r requirements.txt       npm install
    uvicorn app.main:app --reload         npm run dev
Open http://localhost:3000 and sign in as admin@interioriq.com / ChangeMe123! (dev only). API docs: http://localhost:8000/docs

Configuration: copy `apps/api/.env.example` to `apps/api/.env` (set `SECRET_KEY` before real use; SMTP for email is optional).
The database schema is migrated automatically on start (`alembic upgrade head`).

Background jobs (OCR, email) run inside the API by default. For several servers set `TASK_BACKEND=celery` and
`CELERY_BROKER_URL` in `.env`, then start a worker: `cd apps/api && celery -A app.worker worker --loglevel=info` (Windows: add `--pool=solo`).

Deploying with Postgres, several servers, a domain, and backups: see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
Backups: Settings → Backups, or `python -m app.backup create|verify|restore` (from `apps/api`).

## Tests
    cd apps/api && python -m pytest -q        # backend
    cd apps/web && npm test                   # frontend logic
    bash e2e/run.sh                           # real-browser tests (needs: pip install playwright && python -m playwright install chromium)

## Can't sign in?
1. **Is the backend running?** Open http://localhost:8000/api/health — you should see `{"status":"ok"}`. If not, start it: `cd apps/api && uvicorn app.main:app --reload` (run it from `apps/api`).
2. **Open the site at http://localhost:3000** (or 127.0.0.1). If port 3000 was busy, Next uses 3001 — that works too, just use whatever address the terminal prints.
3. **Password:** `admin@interioriq.com` / `ChangeMe123!` (the login page also prints it in dev mode). Accounts are created the first time the API starts.
4. The login page shows a red box if it can't reach the backend, and a message if the server doesn't answer within 20 seconds.
5. Still stuck on "Loading…"? Click *Go to sign in*. If your browser blocks local storage (some IDE preview panes), open the site in a normal browser tab.
