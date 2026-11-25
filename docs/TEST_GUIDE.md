# InteriorIQ — Full Test Guide (basic → end-to-end)

Follow the parts in order: each part uses data created in the one before, so by the end you have one complete project from
**lead → handover → invoices → Tally export**. Tick each box as you go. Expected results are in *italics*.

> **Use a trial database, not your real one.** In `apps/api/.env` add the line
> `DATABASE_URL=sqlite:///./trial.db` and restart the API. A fresh trial database also gets sample catalogue items and
> users. When you're done, delete that line (and `apps/api/trial.db`) to go back to your real data.

---

## Part 0 — Start the app

- [ ] Terminal 1: `cd apps/api` → `pip install -r requirements.txt` → `uvicorn app.main:app --reload --port 8000`
- [ ] Terminal 2: `cd apps/web` → `npm install` → `npm run dev`
- [ ] Open http://localhost:8000/api/health → *`{"status":"ok"}`*
- [ ] Open http://localhost:3000 → *login page, no red "backend not running" box*

**Test users** (password `ChangeMe123!` for all):

| Email | Role |
|---|---|
| admin@interioriq.com | Super admin |
| priya@interioriq.com | Project manager |
| kiran@interioriq.com | Interior designer |
| amit@interioriq.com | Site engineer |

---

## Part 1 — Basics: login, roles, settings

- [ ] Log in as **admin** → *Dashboard opens*
- [ ] Wrong password → *clear error message, no login*
- [ ] **Settings → Company**: enter company name, address, phone, GSTIN (e.g. `24AAACB1234C1Z5` style) → Save → *"Saved"*
- [ ] Same page, **Default payment schedule & terms**: change to 3 milestones (40 / 35 / 25) → *total shows 100%, Save enabled*; try 40/35/20 → *shows 95%, Save disabled*
- [ ] **Settings → Users**: create a user with role **Sales** and a phone number → log out, log in as that user → *menu shows only what Sales may use*
- [ ] **Settings → Roles**: *matrix of roles vs. screens appears*
- [ ] **Settings → System**: *database = sqlite, schema "up to date", PDF fonts: rupee ✓, Gujarati/Hindi ✓*
- [ ] Log back in as **admin**

---

## Part 2 — Catalogue (needed by everything after)

- [ ] **Catalogue → Furniture**: *list of items with prices and stock*
- [ ] Open an item (e.g. a wardrobe) → **Add photo** (any JPG/PNG) → *photo shows; thumbnail appears in the list*
- [ ] Try uploading a PDF as photo → *"not a readable JPG, PNG or WebP photo"*
- [ ] **Change price** with a reason → *price history shows old → new, who, when*
- [ ] **Stock in** 5 with a reason → *stock history shows +5*
- [ ] **Catalogue → Suppliers**: add 2 suppliers (name, phone; optional GSTIN)
- [ ] Back on an item → **Supplier prices** → add a quote from supplier 2 cheaper than the cost → *"Buying today: supplier 2 … cheapest valid quote"*
- [ ] **Catalogue → Materials** → **Export Excel** → *a real .xlsx downloads* → edit a price in Excel → **Import CSV / Excel** → Preview → *shows the change* → Apply
- [ ] Import a file with a missing price → *error listed with its Excel row number; nothing imported*

---

## Part 3 — CRM: lead → follow-ups → client + project

- [ ] **CRM → Leads** → New lead: name, phone, requirement "3BHK interiors", budget
- [ ] Open the lead → **Schedule follow-up** (Call, tomorrow, note) with **Repeat: Every week** → *shows "↻ every week"*
- [ ] **CRM → Follow-ups** → *the call appears under Upcoming* → **WhatsApp** → *WhatsApp opens with the message typed* (don't need to send)
- [ ] Mark it **Done** with an outcome → *next weekly call is booked automatically*
- [ ] Drag the lead card to another stage (e.g. Site visit) → *saved; history shows the change*
- [ ] Drag a **second test lead** to **Lost** → *asks "why?"; Cancel keeps it where it was*
- [ ] On the first lead: **Convert** → *client + project created in one go, lead shows Won*
- [ ] **CRM → Clients**: try adding a client with the same phone written differently (`+91 98765-43210` vs `098765 43210`) → *duplicate warning*

---

## Part 4 — Survey: rooms, measurements, doors & windows, OCR

- [ ] **Projects** → open the new project → *timeline + cards*
- [ ] **Site Survey → Rooms**: add rooms — Master bedroom (4250 × 3600), Living (5200 × 4000), Kitchen (3600 × 3000), Bathroom (2400 × 1800), ceiling 2900
- [ ] Mark measurements as **verified**
- [ ] **Doors & windows** card: add a door on the south wall and a window on the east wall of the bedroom → *mini plan shows them*
- [ ] Try a window wider than the wall → *refused with a reason*
- [ ] **Room shape, ceiling, beams & columns** card (an odd room): Shape → *L-shaped*, tick North-east, 1500 × 1500 → Save shape → *plan shows the L, 6 walls, smaller floor area*
- [ ] Ceiling → *Sloped*, lowest 2700, highest 3300, high side N → Save → *"ceiling 2700–3300 mm"*
- [ ] Add a **Beam** (x 0, y 2000, 4800 × 230, 450 deep) and a **Column** (x 0, y 0, 350 × 350) → *drawn on the plan*
- [ ] Doors & windows → Wall → *"Wall 4 … faces E"* (the inside wall of the L) → add a door there → *drawn on that wall*
- [ ] AI Designer → generate → *nothing in the cut-out corner, nothing on the column, nothing tall under the beam*; Elevations → *sloped top line + beam*; 3D editor → *L-shaped walls, sloped ceiling, beam*
- [ ] Try a cut that leaves almost no room, or switching back to a rectangle while a door is on the inside wall → *refused with a reason*
- [ ] **Documents**: upload a PDF/photo of a plan with dimensions → *"Reading…" then a table of found dimensions* → Apply the ones you trust → *OCR values never overwrite verified ones (reason shown)*

---

## Part 5 — Design: AI Designer, chat, 3D editor, drawings

- [ ] **Design Studio → AI Designer**: pick the bedroom → **Generate** → *bed + wardrobe placed, reasons listed, valid ✓*
- [ ] **Design chat**: type `cheaper and no dresser, under 3 lakh` → *layout regenerates; reply says what changed and the total*
- [ ] Ask `which wardrobes under 1 lakh?` → *list from your catalogue with prices*
- [ ] Generate the **Kitchen** (try "L" shape), **Living** and **Bathroom** (*WC, vanity, mirror, shower*) → **Save version** for each
- [ ] **3D Editor**: pick the bedroom → *realistic room: walls, window, plank floor, real furniture shapes*
- [ ] Drag the bed onto the wardrobe → *both turn red, "Collision" listed* → Ctrl+Z → *valid again*
- [ ] Select an item → **Rotation** 45° and a **Colour** → Save version
- [ ] **Eye level** → *you stand in the doorway looking in*; move the **time slider** to 20:00 → *evening, lights on*
- [ ] **Snapshot** → *saved under Design Studio → Renders*
- [ ] Try switching room with unsaved changes → *asks before discarding*
- [ ] **Floor Plans / Elevations / Ceiling / Electrical** → *drawings show furniture, door, window; electrical points listed* → download DXF → *opens in any CAD viewer*

---

## Part 6 — Estimation: BOQ, quotation, approval

- [ ] **Estimation → BOQ** → pick the bedroom → **Create BOQ** from the saved design → *items with SKUs, rates, totals; quotation number QT-…*
- [ ] **Payment schedule & terms** card → Edit → change milestones → Save → *amounts recalculated, sum = grand total exactly*
- [ ] **Quotation PDF** → *₹ sign, item photos, your schedule and terms, signature block*
- [ ] **Costing** (what-if): change margin/discount → *shows difference, nothing saved*
- [ ] Project page → **Send** the quotation (WhatsApp or email) and mark **Sent**
- [ ] **Approve** the quotation → *status Approved; payment schedule card becomes read-only*

---

## Part 7 — Procurement & manufacturing

- [ ] **Execution → Procurement** → pick the project → **Raise purchase orders** (keep "Use stock first" ticked) → *stock allocated first, draft POs grouped by supplier; the cheaper supplier quote is used and mentioned*
- [ ] Open a PO → edit a rate (draft) → **Issue** → **PO PDF** → **Receive** quantities → *status Partial / Received*
- [ ] **Execution → Manufacturing** → **Create work orders from approved quotations** → *one card per in-house unit*
- [ ] On a wardrobe card: **Drawing** → *A3 shop drawing: front + internal elevation, sections, cutting list, title block*; **DXF** downloads
- [ ] On a kitchen hob unit: drawing shows *3 drawers and a 100 mm plinth*
- [ ] **Advance** a work order through the stages to **READY**
- [ ] **Execution → Cutting Lists** → *boards (sheets) and edge band per quotation*

---

## Part 8 — Delivery → installation → QC → handover

- [ ] **Execution → Delivery** → create a delivery note (only READY / received items allowed) → **Dispatch** → **Delivered** (received by) → challan PDF
- [ ] **Execution → Installation** → tasks appear → assign, mark **Done**
- [ ] **Execution → Quality Control** → mark one check **FAIL** with a note → *a snag is raised* → fix it → check returns to Pending → mark all **PASS**
- [ ] Try handover before everything passes → *refused with the list of blockers*
- [ ] **Handover** → *certificate PDF; project becomes Completed*

---

## Part 9 — Money: payments, invoices, credit notes, costs, payables, Tally

- [ ] Project page → **Record payment** (UPI, reference) → *payment tracker fills milestones in order*
- [ ] Try a payment above the quotation total, or dated tomorrow → *refused*
- [ ] **Raise invoice** by milestone → *Tax invoice (CGST/SGST if same state) — PDF with amount in words*
- [ ] On the invoice: **Credit note** ₹ 5,000 with a reason → *Credited + lower Receivable; credit note PDF*
- [ ] Try cancelling that invoice → *refused while it has a credit note*
- [ ] **Expenses** card: add a labour expense → **Profitability** card: *revenue, cost, margin, cash position*
- [ ] **Finance → Payables**: add a supplier bill against the PO → **Pay** the supplier → *bill Paid, ageing updates, supplier statement*
- [ ] **Finance → Accounting export**: this month → *voucher counts* → **Tally XML** and **Day book (CSV)** download; set your ledger names and Save

---

## Part 10 — Notifications & reminders

- [ ] **Settings → Notifications**: if you set SMTP in `.env` (Gmail + app password), **Send test** → *email arrives*
- [ ] Turn on **Follow-up reminders** → **Send what's due now** → *reminder log lists the emails (or "skipped: email not set up")*
- [ ] Edit a message template, try an unknown `$placeholder` → *refused*
- [ ] Project page → **Messages** card → *every email/WhatsApp sent is logged*

---

## Part 11 — Client portal

- [ ] **Settings → Users** → create a user with role **Client**, linked to the project's client
- [ ] Log in as that client → *only the Client Portal; trying a staff URL redirects back*
- [ ] *Sees: quotation (can approve/reject when Sent), payments, invoices + credit notes with PDFs, deliveries, timeline, handover certificate — no internal costs or QC notes*

---

## Part 12 — Teams, reports, AI project manager

- [ ] **Settings → Company** → turn on **Limit staff to their projects** → log in as kiran (not on the team) → *project not visible*; add kiran on the project's **Team** card → *now visible*; turn it off again
- [ ] **Reports → Revenue / Projects / Profitability** → *real numbers from your test project*
- [ ] Dashboard bell / AI alerts → *rules like overdue follow-up, payment behind, PO late — each names its rule*
- [ ] Top-bar search → type the client name → *finds lead, client, project*

---

## Part 13 — Backups & safety

- [ ] **Settings → Backups** → **Back up now** → **Verify** it → *all checksums OK*
- [ ] Download it (keep it safe — it contains client data)
- [ ] Optional restore drill on the trial database: **Restore** (type RESTORE) → *app comes back with the same data; a safety backup was made first*

---

## Part 14 — Things that must be refused (quick negative checks)

- [ ] Designer user tries to change catalogue prices → *403 / no button*
- [ ] Save a design with overlapping furniture → *flagged invalid, never silently accepted*
- [ ] BOQ from an invalid or empty design → *refused*
- [ ] Approved quotation: edit its payment terms → *refused*
- [ ] Invoice above the quotation total → *refused*
- [ ] Credit note above what's left on the invoice → *refused*
- [ ] Delete a lead → *not possible (archive instead)*

---

## Part 15 — Automated tests (optional, for developers)

```
cd apps/api && python -m pytest -q            # backend (≈345 tests, ~25 min)
cd apps/web && npm test                       # frontend logic (66 tests)
WEB_PORT=3100 API_PORT=8100 bash e2e/run.sh   # real-browser suites (needs: pip install playwright && python -m playwright install chromium)
```

When everything above is ticked, the whole flow — lead to handover to accounts — has been checked end to end.
Remove `DATABASE_URL=sqlite:///./trial.db` from `apps/api/.env` to return to your real data.
