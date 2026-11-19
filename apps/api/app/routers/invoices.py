"""Invoices (GST optional — follows each quotation's GST switch). Issued invoices are never edited; cancel keeps the number used."""
from datetime import date, datetime, time, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models import models as m
from app.services import access
from app.services import boq as boqlib, company as companylib, doc_pdf, flow, invoicing, notify
from app.services.cost_engine import D, inr, split_payments
from app.services.quote_terms import schedule_of

router = APIRouter(tags=["Invoices"])
STAFF = tuple(r for r in m.ROLES if r not in ("CLIENT", "SUPER_ADMIN"))
WRITE = ("ADMIN", "PROJECT_MANAGER", "SALES")


def _m(x) -> str: return f"{D(x):.2f}"


def _qno(db, b: m.Boq) -> str: return flow.quote_no(flow.project_of_boq(db, b).project_number, b)


def inv_out(i: m.Invoice, credited: Decimal | None = None) -> dict:
    cr = D(credited or 0)
    return {"credited": _m(cr), "net": _m(D(i.amount) - cr) if i.status == "ISSUED" else _m(0), "id": i.id, "invoice_no": i.invoice_no, "kind": i.kind, "status": i.status, "project_id": i.project_id, "boq_id": i.boq_id,
            "issue_date": i.issue_date.date().isoformat(), "description": i.description, "amount": _m(i.amount), "taxable": _m(i.taxable),
            "gst_rate": format(D(i.gst_rate).normalize(), "f"), "cgst": _m(i.cgst), "sgst": _m(i.sgst), "igst": _m(i.igst),
            "place_of_supply": i.place_of_supply, "place_of_supply_name": invoicing.STATES.get(i.place_of_supply or ""), "buyer_name": (i.buyer or {}).get("name"),
            "cancel_reason": i.cancel_reason, "user_name": i.user_name, "created_at": i.created_at.isoformat() if i.created_at else None}


def credited_by_invoice(db: Session, invoice_ids) -> dict:
    ids = list(invoice_ids)
    if not ids: return {}
    rows = db.query(m.CreditNote.invoice_id, func.coalesce(func.sum(m.CreditNote.amount), 0)).filter(m.CreditNote.invoice_id.in_(ids), m.CreditNote.status == "ISSUED") \
        .group_by(m.CreditNote.invoice_id).all()
    return {k: D(v or 0) for k, v in rows}


def _invoiced(db: Session, bid: str, description: str | None = None) -> Decimal:
    """NET invoiced against a quotation (issued invoices − their active credit notes), so a credited amount can be invoiced again."""
    q = db.query(m.Invoice).filter(m.Invoice.boq_id == bid, m.Invoice.status == "ISSUED")
    if description is not None: q = q.filter(m.Invoice.description == description)
    invs = q.all(); cr = credited_by_invoice(db, [i.id for i in invs])
    return sum((D(i.amount) - cr.get(i.id, Decimal(0)) for i in invs), Decimal(0))


def _approved(db: Session, pid: str) -> list[m.Boq]:
    rooms = [r.id for r in db.query(m.Room.id).filter_by(project_id=pid)]
    return db.query(m.Boq).filter(m.Boq.room_id.in_(rooms), m.Boq.status == "APPROVED").order_by(m.Boq.created_at).all() if rooms else []


def summary(db: Session, pid: str) -> dict:
    boqs = _approved(db, pid)
    out_boqs = []
    for b in boqs:
        total = D(b.totals["grand_total"])
        ms = [{"stage": label, "pct": pct, "amount": _m(share), "invoiced": _m(_invoiced(db, b.id, label)), "remaining": _m(max(Decimal(0), share - _invoiced(db, b.id, label)))}
              for (label, pct), share in zip(schedule_of(b.params), split_payments(total, [p for _, p in schedule_of(b.params)]))]
        out_boqs.append({"boq_id": b.id, "quotation_no": _qno(db, b), "grand_total": _m(total), "gst_enabled": boqlib.gst_on(b.params),
                         "gst_pct": b.params.get("gst_pct", "0"), "invoiced": _m(_invoiced(db, b.id)), "remaining": _m(total - _invoiced(db, b.id)), "milestones": ms})
    invs = db.query(m.Invoice).filter_by(project_id=pid).order_by(m.Invoice.seq.desc(), m.Invoice.created_at.desc()).all()
    cr = credited_by_invoice(db, [i.id for i in invs])
    invoiced = sum((D(i.amount) for i in invs if i.status == "ISSUED"), Decimal(0))
    credited = sum((cr.get(i.id, Decimal(0)) for i in invs if i.status == "ISSUED"), Decimal(0))
    paid = D(db.query(func.coalesce(func.sum(m.Payment.amount), 0)).filter_by(project_id=pid).scalar() or 0)
    notes = db.query(m.CreditNote).filter_by(project_id=pid).order_by(m.CreditNote.created_at.desc()).all()
    numbers = {i.id: i.invoice_no for i in invs}
    return {"quotations": out_boqs, "invoices": [inv_out(i, cr.get(i.id)) for i in invs], "credit_notes": [cn_out(n, numbers.get(n.invoice_id)) for n in notes],
            "totals": {"invoiced": _m(invoiced), "credited": _m(credited), "paid": _m(paid), "receivable": _m(max(Decimal(0), invoiced - credited - paid))}}


@router.get("/projects/{pid}/invoices")
def project_invoices(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    if not db.get(m.Project, pid): raise HTTPException(404, "Project not found")
    return {**summary(db, pid), "states": invoicing.STATES}


class InvoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    boq_id: str
    milestone: str | None = Field(None, max_length=80)
    amount: Decimal | None = Field(None, gt=0, le=10_000_000_000, decimal_places=2)
    description: str | None = Field(None, max_length=200)
    issue_date: date | None = None
    place_of_supply: str | None = Field(None, max_length=2)


@router.post("/projects/{pid}/invoices", status_code=201)
def create_invoice(pid: str, body: InvoiceIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    p = db.get(m.Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    b = db.get(m.Boq, body.boq_id)
    if not b or flow.project_of_boq(db, b).id != pid: raise HTTPException(404, "Quotation not found on this project")
    if flow.boq_status(b) != "APPROVED": raise HTTPException(409, f"{_qno(db, b)} is {flow.boq_status(b)}; invoices are raised only against an APPROVED quotation.")
    total = D(b.totals["grand_total"]); already = _invoiced(db, b.id)
    sch = schedule_of(b.params)
    labels = dict(zip([l for l, _ in sch], split_payments(total, [pc for _, pc in sch])))
    if body.milestone and body.milestone not in labels: raise HTTPException(422, f"milestone must be one of: {', '.join(labels)}")
    amount = body.amount
    if amount is None:
        if not body.milestone: raise HTTPException(422, "Give an amount or pick a payment milestone")
        amount = labels[body.milestone] - _invoiced(db, b.id, body.milestone)
        if amount <= 0: raise HTTPException(409, f"'{body.milestone}' on {_qno(db, b)} is already fully invoiced")
    if already + amount > total:
        raise HTTPException(409, f"That would invoice Rs. {inr(already + amount)} against {_qno(db, b)} (total Rs. {inr(total)}); Rs. {inr(total - already)} is left to invoice.")
    when = body.issue_date or date.today()
    if when > date.today(): raise HTTPException(422, "An invoice can't be dated in the future")
    comp = companylib.get(db); c = db.get(m.Client, p.client_id) if p.client_id else None
    gst = boqlib.gst_on(b.params); rate = D(b.params.get("gst_pct", "0")) if gst else Decimal(0)
    seller_state = companylib.state_code(comp.get("gstin"))
    if gst and not comp.get("gstin"):
        raise HTTPException(409, f"{_qno(db, b)} includes GST, so this must be a GST tax invoice — set your GSTIN in Settings → Company first.")
    pos = None
    if gst:
        pos = body.place_of_supply or companylib.state_code(c.gstin if c else None) or seller_state
        if pos not in invoicing.STATES: raise HTTPException(422, "place_of_supply must be a GST state code (e.g. 24 for Gujarat)")
    parts = invoicing.split(amount, rate, intra_state=(pos == seller_state)) if gst else invoicing.split(amount, 0, True)
    fy = invoicing.financial_year(when)
    seq = (db.query(func.max(m.Invoice.seq)).filter_by(fy=fy).scalar() or 0) + 1
    prefix = (comp.get("invoice_prefix") or "INV").upper()
    inv = m.Invoice(invoice_no=f"{prefix}/{fy}/{seq:04d}", seq=seq, fy=fy, project_id=pid, boq_id=b.id, kind="TAX" if gst else "PLAIN",
                    issue_date=datetime.combine(when, time(12), tzinfo=timezone.utc), description=(body.description or body.milestone or "Interior works").strip(),
                    amount=amount, taxable=parts["taxable"], gst_rate=rate, cgst=parts["cgst"], sgst=parts["sgst"], igst=parts["igst"], place_of_supply=pos,
                    sac_code=comp.get("sac_code") or None,
                    seller={k: comp.get(k) for k in ("name", "address", "phone", "email", "gstin")} | {"state": seller_state},
                    buyer={"name": c.name if c else p.name, "company": c.company if c else None, "address": p.site_address or (c.address if c else None),
                           "city": c.city if c else None, "phone": c.phone if c else None, "gstin": c.gstin if c else None},
                    user_id=user.get("sub"), user_name=user.get("name"))
    db.add(inv)
    flow.event(db, pid, "INVOICE", f"{'Tax invoice' if gst else 'Invoice'} {inv.invoice_no} issued: Rs. {inr(amount)} — {inv.description}", user, "INVOICE", inv.id)
    db.flush(); notify.auto(db, "INVOICE", inv.id, user)
    db.commit(); return inv_out(inv)


class CancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=500)


@router.post("/invoices/{iid}/cancel")
def cancel_invoice(iid: str, body: CancelIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    i = db.get(m.Invoice, iid)
    if not i: raise HTTPException(404, "Invoice not found")
    if i.status == "CANCELLED": raise HTTPException(409, f"{i.invoice_no} is already cancelled")
    if db.query(m.CreditNote).filter_by(invoice_id=i.id, status="ISSUED").count():
        raise HTTPException(409, f"{i.invoice_no} has credit notes — cancel them first, or keep the invoice and its credit notes as they are.")
    i.status, i.cancel_reason, i.cancelled_at = "CANCELLED", body.reason.strip(), flow.now()
    flow.event(db, i.project_id, "INVOICE", f"Invoice {i.invoice_no} cancelled: {i.cancel_reason} (number not reused)", user, "INVOICE", i.id)
    db.commit(); return inv_out(i)


@router.get("/invoices")
def all_invoices(status: str | None = None, kind: str | None = None, q: str | None = None, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    qry = access.scope(db.query(m.Invoice), m.Invoice.project_id, db, user)
    if status: qry = qry.filter_by(status=status)
    if kind: qry = qry.filter_by(kind=kind)
    projects = {p.id: p for p in db.query(m.Project)}
    rows = []
    for i in qry.order_by(m.Invoice.created_at.desc()):
        r = inv_out(i); pr = projects.get(i.project_id); r["project_number"] = pr.project_number if pr else None; r["project_name"] = pr.name if pr else None
        rows.append(r)
    if q and q.strip():
        k = q.strip().lower(); rows = [r for r in rows if any(k in (r[f] or "").lower() for f in ("invoice_no", "project_number", "project_name", "buyer_name", "description"))]
    return rows


def render_pdf(i: m.Invoice) -> bytes:
    s, bu = i.seller or {}, i.buyer or {}
    tax = i.kind == "TAX"
    rate = format(D(i.gst_rate).normalize(), "f")
    totals = [("Taxable value", inr(i.taxable))] if tax else []
    if tax and D(i.igst) > 0: totals.append((f"IGST {rate}%", inr(i.igst)))
    elif tax: totals += [(f"CGST {format((D(i.gst_rate) / 2).normalize(), 'f')}%", inr(i.cgst)), (f"SGST {format((D(i.gst_rate) / 2).normalize(), 'f')}%", inr(i.sgst))]
    totals.append(("Total payable (Rs.)", inr(i.amount)))
    meta = [("Invoice date", i.issue_date.date().isoformat())]
    if tax: meta += [("Place of supply", f"{i.place_of_supply} - {invoicing.STATES.get(i.place_of_supply, '')}"), ("Reverse charge", "No")]
    paras = [f"Amount in words: {invoicing.words(i.amount)}"]
    paras.append("GST included as shown above." if tax else "GST is not charged on this invoice.")
    if i.status == "CANCELLED": paras.insert(0, f"*** CANCELLED — {i.cancel_reason} ***")
    seller_lines = [s.get("name"), s.get("address"), s.get("phone"), s.get("email")] + ([f"GSTIN {s['gstin']}", f"State {s.get('state')} - {invoicing.STATES.get(s.get('state') or '', '')}"] if tax and s.get("gstin") else [])
    buyer_lines = [bu.get("name"), bu.get("company"), bu.get("address"), bu.get("city"), bu.get("phone")] + ([f"GSTIN {bu['gstin']}"] if bu.get("gstin") else [])
    header = ["#", "Description", "SAC", "Taxable value (Rs.)", "Amount (Rs.)"] if tax else ["#", "Description", "", "", "Amount (Rs.)"]
    row = ["1", i.description, i.sac_code or "" if tax else "", inr(i.taxable) if tax else "", inr(i.amount)]
    return doc_pdf.render(company={**s, "name": s.get("name") or "—"}, title="Tax Invoice" if tax else "Invoice", number=i.invoice_no, meta=meta,
                          parties=[("Seller", seller_lines), ("Bill to", buyer_lines)], header=header, rows=[row], widths=[10, 86, 20, 32, 30], right_cols=(3, 4),
                          totals=totals, paragraphs=paras, signatures=("Received by (client)", "Authorised signatory"))


# ── M33 credit notes ───────────────────────────────────────────────────────────
def cn_out(n: m.CreditNote, invoice_no: str | None = None) -> dict:
    return {"id": n.id, "note_no": n.note_no, "invoice_id": n.invoice_id, "invoice_no": invoice_no, "project_id": n.project_id, "status": n.status,
            "issue_date": n.issue_date.date().isoformat(), "reason": n.reason, "amount": _m(n.amount), "taxable": _m(n.taxable), "cgst": _m(n.cgst),
            "sgst": _m(n.sgst), "igst": _m(n.igst), "cancel_reason": n.cancel_reason, "user_name": n.user_name,
            "created_at": n.created_at.isoformat() if n.created_at else None}


class CreditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Decimal = Field(gt=0, le=10_000_000_000, decimal_places=2)
    reason: str = Field(min_length=5, max_length=300)
    issue_date: date | None = None


@router.post("/invoices/{iid}/credit-notes", status_code=201)
def create_credit_note(iid: str, body: CreditIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    i = db.get(m.Invoice, iid)
    if not i: raise HTTPException(404, "Invoice not found")
    access.check(db, user, i.project_id)
    if i.status != "ISSUED": raise HTTPException(409, f"{i.invoice_no} is cancelled; credit notes are only for issued invoices")
    left = D(i.amount) - credited_by_invoice(db, [i.id]).get(i.id, Decimal(0))
    if body.amount > left: raise HTTPException(409, f"Only Rs. {inr(left)} of {i.invoice_no} is left to credit")
    when = body.issue_date or date.today()
    if when > date.today(): raise HTTPException(422, "A credit note can't be dated in the future")
    if when < i.issue_date.date(): raise HTTPException(422, f"A credit note can't be dated before its invoice ({i.issue_date.date().isoformat()})")
    if i.kind == "TAX": parts = invoicing.split(body.amount, D(i.gst_rate), intra_state=D(i.igst) == 0)
    else: parts = invoicing.split(body.amount, 0, True)
    fy = invoicing.financial_year(when)
    seq = (db.query(func.max(m.CreditNote.seq)).filter_by(fy=fy).scalar() or 0) + 1
    prefix = (companylib.get(db).get("invoice_prefix") or "INV").upper()
    n = m.CreditNote(note_no=f"{prefix}/CN/{fy}/{seq:04d}", seq=seq, fy=fy, invoice_id=i.id, project_id=i.project_id,
                     issue_date=datetime.combine(when, time(12), tzinfo=timezone.utc), reason=body.reason.strip(), amount=body.amount, taxable=parts["taxable"],
                     cgst=parts["cgst"], sgst=parts["sgst"], igst=parts["igst"], user_id=user.get("sub"), user_name=user.get("name"))
    db.add(n)
    flow.event(db, i.project_id, "INVOICE", f"Credit note {n.note_no} against {i.invoice_no}: Rs. {inr(body.amount)} — {n.reason}", user, "INVOICE", i.id)
    db.commit(); return cn_out(n, i.invoice_no)


@router.post("/credit-notes/{cid}/cancel")
def cancel_credit_note(cid: str, body: CancelIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    n = db.get(m.CreditNote, cid)
    if not n: raise HTTPException(404, "Credit note not found")
    access.check(db, user, n.project_id)
    if n.status == "CANCELLED": raise HTTPException(409, f"{n.note_no} is already cancelled")
    n.status, n.cancel_reason, n.cancelled_at = "CANCELLED", body.reason.strip(), flow.now()
    flow.event(db, n.project_id, "INVOICE", f"Credit note {n.note_no} cancelled: {n.cancel_reason} (number not reused)", user, "INVOICE", n.invoice_id)
    db.commit(); return cn_out(n, db.get(m.Invoice, n.invoice_id).invoice_no)


def render_credit_pdf(n: m.CreditNote, i: m.Invoice) -> bytes:
    s, bu = i.seller or {}, i.buyer or {}; inv_no, inv_date, tax, rate = i.invoice_no, i.issue_date.date().isoformat(), i.kind == "TAX", D(i.gst_rate)
    rs = format(rate.normalize(), "f")
    totals = [("Taxable value", inr(n.taxable))] if tax else []
    if tax and D(n.igst) > 0: totals.append((f"IGST {rs}%", inr(n.igst)))
    elif tax: totals += [(f"CGST {format((rate / 2).normalize(), 'f')}%", inr(n.cgst)), (f"SGST {format((rate / 2).normalize(), 'f')}%", inr(n.sgst))]
    totals.append(("Total credited (Rs.)", inr(n.amount)))
    paras = [f"Amount in words: {invoicing.words(n.amount)}", f"This credit note reduces invoice {inv_no} dated {inv_date} by the amount above."]
    if n.status == "CANCELLED": paras.insert(0, f"*** CANCELLED — {n.cancel_reason} ***")
    seller_lines = [s.get("name"), s.get("address"), s.get("phone"), s.get("email")] + ([f"GSTIN {s['gstin']}"] if tax and s.get("gstin") else [])
    buyer_lines = [bu.get("name"), bu.get("company"), bu.get("address"), bu.get("city"), bu.get("phone")] + ([f"GSTIN {bu['gstin']}"] if bu.get("gstin") else [])
    header = ["#", "Reason", "", "Taxable value (Rs.)" if tax else "", "Amount (Rs.)"]
    row = ["1", n.reason, "", inr(n.taxable) if tax else "", inr(n.amount)]
    return doc_pdf.render(company={**s, "name": s.get("name") or "-"}, title="Credit Note", number=n.note_no,
                          meta=[("Date", n.issue_date.date().isoformat()), ("Against invoice", f"{inv_no} dated {inv_date}")],
                          parties=[("Issued by", seller_lines), ("Issued to", buyer_lines)], header=header, rows=[row], widths=[10, 86, 20, 32, 30], right_cols=(3, 4),
                          totals=totals, paragraphs=paras, signatures=("Received by (client)", "Authorised signatory"))


@router.get("/credit-notes/{cid}/pdf")
def credit_pdf(cid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    n = db.get(m.CreditNote, cid)
    if not n: raise HTTPException(404, "Credit note not found")
    access.check(db, user, n.project_id)
    return Response(render_credit_pdf(n, db.get(m.Invoice, n.invoice_id)), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{n.note_no.replace("/", "-")}.pdf"'})


@router.get("/portal/credit-notes/{cid}/pdf")
def portal_credit_pdf(cid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles("CLIENT"))):
    n = db.get(m.CreditNote, cid); p = db.get(m.Project, n.project_id) if n else None
    if not n or n.status != "ISSUED" or not p or not user.get("client_id") or p.client_id != user["client_id"]: raise HTTPException(404, "Credit note not found")
    return Response(render_credit_pdf(n, db.get(m.Invoice, n.invoice_id)), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{n.note_no.replace("/", "-")}.pdf"'})


@router.get("/invoices/{iid}/pdf")
def invoice_pdf(iid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    i = db.get(m.Invoice, iid)
    if not i: raise HTTPException(404, "Invoice not found")
    return Response(render_pdf(i), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{i.invoice_no.replace("/", "-")}.pdf"'})


# ── client portal ──
@router.get("/portal/invoices/{iid}/pdf")
def portal_invoice_pdf(iid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles("CLIENT"))):
    i = db.get(m.Invoice, iid); p = db.get(m.Project, i.project_id) if i else None
    if not i or not p or not user.get("client_id") or p.client_id != user["client_id"]: raise HTTPException(404, "Invoice not found")
    return Response(render_pdf(i), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{i.invoice_no.replace("/", "-")}.pdf"'})
