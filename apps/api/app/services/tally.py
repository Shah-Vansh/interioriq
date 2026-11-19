"""M34 Accounting export — Tally Prime / Tally ERP 9 XML (free: Tally imports it via Gateway → Import → Vouchers) and a plain day-book CSV
for any other accounting software. Nothing is posted anywhere automatically; the user downloads the file and imports it.

Vouchers for a date range (company local dates):
  Sales        — each ISSUED invoice: party Dr total; Sales Cr taxable; Output CGST/SGST or IGST Cr
  Credit Note  — each ISSUED credit note: the reverse of the above
  Receipt      — each client payment: Bank (or Cash) Dr; party Cr
  Purchase     — each supplier bill (not VOID): Purchases Dr taxable; Input GST Dr; supplier Cr total
  Payment      — each supplier payment (not VOID): supplier Dr; Bank (or Cash) Cr
Tally's sign convention: a debit line has ISDEEMEDPOSITIVE=Yes and a NEGATIVE amount, a credit line No and a positive amount; every voucher
balances to zero exactly (Decimal). Party ledgers (clients under Sundry Debtors, suppliers under Sundry Creditors) and the configured ledgers
are included as masters so a fresh Tally company imports cleanly. Ledger names are set in Settings → Company → Accounting export."""
import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from app.models import models as m
from app.services import followups as fups

KEY = "tally"
DEFAULTS = {"company": "", "sales": "Sales - Interior Works", "cgst": "Output CGST", "sgst": "Output SGST", "igst": "Output IGST",
            "bank": "Bank Account", "cash": "Cash", "purchase": "Purchases - Materials", "input_gst": "Input GST",
            "debtors_group": "Sundry Debtors", "creditors_group": "Sundry Creditors"}
LABELS = {"company": "Tally company name (blank = the company open in Tally)", "sales": "Sales ledger", "cgst": "Output CGST ledger", "sgst": "Output SGST ledger",
          "igst": "Output IGST ledger", "bank": "Bank ledger (UPI / cheque / card / bank)", "cash": "Cash ledger", "purchase": "Purchase ledger",
          "input_gst": "Input GST ledger", "debtors_group": "Group for clients", "creditors_group": "Group for suppliers"}
PARENTS = {"sales": "Sales Accounts", "cgst": "Duties & Taxes", "sgst": "Duties & Taxes", "igst": "Duties & Taxes", "bank": "Bank Accounts", "cash": "Cash-in-Hand",
           "purchase": "Purchase Accounts", "input_gst": "Duties & Taxes"}
KINDS = ("sales", "credit", "receipt", "purchase", "payment")
Z = Decimal("0.00")


class ExportError(ValueError): pass


def settings_of(db: Session) -> dict:
    row = db.get(m.CompanySetting, KEY); v = (row.value if row else None) or {}
    return {k: (v.get(k) if v.get(k) is not None else d) for k, d in DEFAULTS.items()}


def save(db: Session, patch: dict, by: str | None) -> dict:
    bad = [k for k in patch if k not in DEFAULTS]
    if bad: raise ExportError(f"Unknown setting(s): {', '.join(bad)}")
    cur = settings_of(db)
    for k, v in patch.items():
        v = ("" if v is None else str(v)).strip()
        if k != "company" and not v: raise ExportError(f"{LABELS[k]} can't be empty")
        if len(v) > 100 or any(ch in v for ch in "<>&\"'"): raise ExportError(f"{LABELS[k]}: up to 100 characters, no < > & or quotes")
        cur[k] = v
    row = db.get(m.CompanySetting, KEY)
    if row: row.value, row.updated_by = dict(cur), by
    else: db.add(m.CompanySetting(key=KEY, value=dict(cur), updated_by=by))
    db.commit(); return settings_of(db)


def _range(d_from: date, d_to: date):
    if d_to < d_from: raise ExportError("The 'to' date is before the 'from' date")
    if (d_to - d_from).days > 400: raise ExportError("Export at most about one year at a time (400 days)")
    tz = fups.local_tz()
    return datetime.combine(d_from, time(0), tzinfo=tz).astimezone(timezone.utc), datetime.combine(d_to + timedelta(days=1), time(0), tzinfo=tz).astimezone(timezone.utc)


def _aw(t): return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
def _d(t) -> date: return _aw(t).astimezone(fups.local_tz()).date()
def _in(t, a, b) -> bool: return a <= _aw(t) < b
def D(x) -> Decimal: return Decimal(str(x or 0)).quantize(Decimal("0.01"))


def vouchers(db: Session, d_from: date, d_to: date, kinds=KINDS) -> list[dict]:
    """[{type, number, date, party, party_kind, narration, lines: [(ledger, signed amount: + debit / − credit)], project, reference}] sorted by date."""
    L = settings_of(db); a, b = _range(d_from, d_to); out = []
    projects = {p.id: p for p in db.query(m.Project)}; clients = {c.id: c for c in db.query(m.Client)}
    suppliers = {s.id: s for s in db.query(m.Supplier)}
    def client_name(pid, fallback=None):
        p = projects.get(pid); c = clients.get(p.client_id) if p and p.client_id else None
        return (c.name if c else None) or fallback or (p.name if p else "Client")
    def gst_lines(sign, cgst, sgst, igst):
        out_ = []
        if D(igst): out_.append((L["igst"], sign * D(igst)))
        if D(cgst): out_.append((L["cgst"], sign * D(cgst)))
        if D(sgst): out_.append((L["sgst"], sign * D(sgst)))
        return out_
    invoices = {i.id: i for i in db.query(m.Invoice)}
    if "sales" in kinds:
        for i in invoices.values():
            if i.status != "ISSUED" or not _in(i.issue_date, a, b): continue
            party = client_name(i.project_id, (i.buyer or {}).get("name"))
            out.append({"type": "Sales", "number": i.invoice_no, "date": _d(i.issue_date), "party": party, "party_kind": "client",
                        "narration": f"{i.description} — {projects[i.project_id].project_number if i.project_id in projects else ''}".strip(" —"),
                        "lines": [(party, D(i.amount)), (L["sales"], -D(i.taxable))] + gst_lines(-1, i.cgst, i.sgst, i.igst),
                        "project": projects[i.project_id].project_number if i.project_id in projects else "", "reference": i.invoice_no})
    if "credit" in kinds:
        for n in db.query(m.CreditNote).filter(m.CreditNote.status == "ISSUED"):
            if not _in(n.issue_date, a, b): continue
            inv = invoices.get(n.invoice_id); party = client_name(n.project_id, (inv.buyer or {}).get("name") if inv else None)
            out.append({"type": "Credit Note", "number": n.note_no, "date": _d(n.issue_date), "party": party, "party_kind": "client",
                        "narration": f"{n.reason} (against {inv.invoice_no if inv else ''})",
                        "lines": [(L["sales"], D(n.taxable))] + gst_lines(1, n.cgst, n.sgst, n.igst) + [(party, -D(n.amount))],
                        "project": projects[n.project_id].project_number if n.project_id in projects else "", "reference": inv.invoice_no if inv else ""})
    if "receipt" in kinds:
        for p in db.query(m.Payment):
            if not _in(p.received_on, a, b): continue
            party = client_name(p.project_id); cash = (p.mode or "").upper() == "CASH"
            out.append({"type": "Receipt", "number": f"RCPT-{_d(p.received_on):%Y%m%d}-{p.id[:6].upper()}", "date": _d(p.received_on), "party": party, "party_kind": "client",
                        "narration": f"Received by {p.mode.lower()}" + (f" ref. {p.reference}" if p.reference else ""),
                        "lines": [(L["cash"] if cash else L["bank"], D(p.amount)), (party, -D(p.amount))],
                        "project": projects[p.project_id].project_number if p.project_id in projects else "", "reference": p.reference or ""})
    if "purchase" in kinds:
        for bl in db.query(m.SupplierBill).filter(m.SupplierBill.status != "VOID"):
            if not _in(bl.bill_date, a, b): continue
            s = suppliers.get(bl.supplier_id); party = s.name if s else "Supplier"
            lines = [(L["purchase"], D(bl.taxable))] + ([(L["input_gst"], D(bl.gst))] if D(bl.gst) else []) + [(party, -D(bl.total))]
            out.append({"type": "Purchase", "number": bl.bill_no, "date": _d(bl.bill_date), "party": party, "party_kind": "supplier",
                        "narration": (bl.note or "Supplier bill") + (f" — {projects[bl.project_id].project_number}" if bl.project_id in projects else ""), "lines": lines,
                        "project": projects[bl.project_id].project_number if bl.project_id in projects else "", "reference": bl.bill_no})
    if "payment" in kinds:
        for sp in db.query(m.SupplierPayment).filter(m.SupplierPayment.status != "VOID"):
            if not _in(sp.paid_on, a, b): continue
            s = suppliers.get(sp.supplier_id); party = s.name if s else "Supplier"; cash = (sp.mode or "").upper() == "CASH"
            out.append({"type": "Payment", "number": f"PAY-{_d(sp.paid_on):%Y%m%d}-{sp.id[:6].upper()}", "date": _d(sp.paid_on), "party": party, "party_kind": "supplier",
                        "narration": f"Paid by {sp.mode.lower()}" + (f" ref. {sp.reference}" if sp.reference else ""),
                        "lines": [(party, D(sp.amount)), (L["cash"] if cash else L["bank"], -D(sp.amount))], "project": "", "reference": sp.reference or ""})
    for v in out:
        total = sum((amt for _, amt in v["lines"]), Z)
        if total != 0: raise ExportError(f"{v['type']} {v['number']} doesn't balance ({total}) — please report this")
    return sorted(out, key=lambda v: (v["date"], v["type"], v["number"]))


def _x(s) -> str: return escape("" if s is None else str(s))


def tally_xml(db: Session, d_from: date, d_to: date, kinds=KINDS, masters: bool = True) -> tuple[bytes, int]:
    L = settings_of(db); vs = vouchers(db, d_from, d_to, kinds); msgs = []
    if masters:
        names = {}
        for k, parent in PARENTS.items(): names[L[k]] = parent
        for v in vs: names.setdefault(v["party"], L["debtors_group"] if v["party_kind"] == "client" else L["creditors_group"])
        for name, parent in names.items():
            msgs.append(f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><LEDGER NAME="{_x(name)}" ACTION="Create"><NAME.LIST><NAME>{_x(name)}</NAME></NAME.LIST>'
                        f'<PARENT>{_x(parent)}</PARENT><ISBILLWISEON>{"Yes" if parent in (L["debtors_group"], L["creditors_group"]) else "No"}</ISBILLWISEON></LEDGER></TALLYMESSAGE>')
    for v in vs:
        lines = "".join(f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{_x(led)}</LEDGERNAME><ISDEEMEDPOSITIVE>{'Yes' if amt > 0 else 'No'}</ISDEEMEDPOSITIVE>"
                        f"<AMOUNT>{-amt:.2f}</AMOUNT></ALLLEDGERENTRIES.LIST>" for led, amt in v["lines"])
        msgs.append(f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER VCHTYPE="{_x(v["type"])}" ACTION="Create" OBJVIEW="Accounting Voucher View">'
                    f'<DATE>{v["date"]:%Y%m%d}</DATE><EFFECTIVEDATE>{v["date"]:%Y%m%d}</EFFECTIVEDATE><VOUCHERTYPENAME>{_x(v["type"])}</VOUCHERTYPENAME>'
                    f'<VOUCHERNUMBER>{_x(v["number"])}</VOUCHERNUMBER><REFERENCE>{_x(v["reference"])}</REFERENCE><PARTYLEDGERNAME>{_x(v["party"])}</PARTYLEDGERNAME>'
                    f'<NARRATION>{_x(v["narration"])}</NARRATION><PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>{lines}</VOUCHER></TALLYMESSAGE>')
    company = f"<STATICVARIABLES><SVCURRENTCOMPANY>{_x(L['company'])}</SVCURRENTCOMPANY></STATICVARIABLES>" if L["company"] else ""
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>'
           f'<REQUESTDESC><REPORTNAME>All Masters</REPORTNAME>{company}</REQUESTDESC><REQUESTDATA>' + "\n".join(msgs) + '</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>\n')
    return xml.encode("utf-8"), len(vs)


def daybook_csv(db: Session, d_from: date, d_to: date, kinds=KINDS) -> tuple[str, int]:
    vs = vouchers(db, d_from, d_to, kinds); out = io.StringIO(); w = csv.writer(out)
    w.writerow(["date", "voucher_type", "number", "party", "ledger", "debit", "credit", "narration", "project", "reference"])
    for v in vs:
        for led, amt in v["lines"]:
            w.writerow([v["date"].isoformat(), v["type"], v["number"], v["party"], led, f"{amt:.2f}" if amt > 0 else "", f"{-amt:.2f}" if amt < 0 else "",
                        v["narration"], v["project"], v["reference"]])
    return "﻿" + out.getvalue(), len(vs)
