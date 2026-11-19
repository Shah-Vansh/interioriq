"""M26 Payment schedule + terms per quotation.

The company keeps a DEFAULT schedule (milestones whose % add up to exactly 100) and default terms (Settings → Company). Every new quotation
copies them into its params, so a later change of the default never rewrites a quotation that was already printed or approved.
A quotation's own schedule/terms can be edited while it isn't APPROVED and nothing has been invoiced/paid against it. Quotations saved before
M26 (no schedule in params) keep the built-in schedule they were printed with. Money for each milestone is always split on the server
(cost_engine.split_payments: the last milestone absorbs the rounding, so the parts sum to the total exactly)."""
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.models import models as m

BUILTIN_SCHEDULE = [("Agreement signing", "30"), ("Design approval", "20"), ("Material procurement", "25"), ("Installation complete", "20"), ("Handover and final QC", "5")]
BUILTIN_TERMS = ["Prices are based on the approved design and are valid until the date shown.",
                 "Any change to scope, materials or dimensions after approval may change the price.",
                 "Material selection is finalised at design approval.",
                 "The site must be clear and accessible before installation starts.",
                 "Warranty, delivery timelines and disputes are as set out in the contract signed on acceptance."]
KEY = "quote_terms"
MAX_MILESTONES, MAX_TERMS = 10, 20


class TermsError(ValueError): pass


def _plain(d: Decimal) -> str:
    s = format(d.normalize(), "f")
    return s


def clean_schedule(rows) -> list[dict]:
    """[{label, pct}] → validated, % as plain decimal strings; 1–10 milestones, unique labels, each 0 < % ≤ 100 with ≤ 2 decimals, total exactly 100."""
    if not isinstance(rows, list) or not rows: raise TermsError("Add at least one payment milestone")
    if len(rows) > MAX_MILESTONES: raise TermsError(f"At most {MAX_MILESTONES} payment milestones")
    out, seen, total = [], set(), Decimal(0)
    for i, r in enumerate(rows, 1):
        if not isinstance(r, dict): raise TermsError(f"Milestone {i}: expected a label and a %")
        label = str(r.get("label") or "").strip()
        if not label: raise TermsError(f"Milestone {i}: enter a name")
        if len(label) > 80: raise TermsError(f"Milestone {i}: the name is longer than 80 characters")
        if label.lower() in seen: raise TermsError(f"'{label}' appears twice — each milestone needs its own name")
        seen.add(label.lower())
        try: pct = Decimal(str(r.get("pct")).strip())
        except (InvalidOperation, TypeError): raise TermsError(f"'{label}': % must be a number")
        if not pct.is_finite() or pct <= 0 or pct > 100: raise TermsError(f"'{label}': % must be more than 0 and at most 100")
        if pct != pct.quantize(Decimal("0.01")): raise TermsError(f"'{label}': use at most 2 decimals")
        total += pct; out.append({"label": label, "pct": _plain(pct)})
    if total != 100: raise TermsError(f"The milestones add up to {_plain(total)}% — they must add up to exactly 100%")
    return out


def clean_terms(rows) -> list[str]:
    if rows is None: return []
    if not isinstance(rows, list): raise TermsError("Terms must be a list of lines")
    out = [str(t).strip() for t in rows if str(t or "").strip()]
    if len(out) > MAX_TERMS: raise TermsError(f"At most {MAX_TERMS} terms")
    long = [i for i, t in enumerate(out, 1) if len(t) > 500]
    if long: raise TermsError(f"Term {long[0]} is longer than 500 characters")
    return out


def company_defaults(db: Session) -> dict:
    row = db.get(m.CompanySetting, KEY); v = (row.value if row else None) or {}
    return {"schedule": v.get("schedule") or [{"label": l, "pct": p} for l, p in BUILTIN_SCHEDULE],
            "terms": v["terms"] if "terms" in v else list(BUILTIN_TERMS), "customised": bool(row)}


def save_company_defaults(db: Session, schedule, terms, by: str | None) -> dict:
    val = {"schedule": clean_schedule(schedule), "terms": clean_terms(terms)}
    row = db.get(m.CompanySetting, KEY)
    if row: row.value, row.updated_by = val, by
    else: db.add(m.CompanySetting(key=KEY, value=val, updated_by=by))
    db.commit(); return company_defaults(db)


def reset_company_defaults(db: Session) -> dict:
    row = db.get(m.CompanySetting, KEY)
    if row: db.delete(row); db.commit()
    return company_defaults(db)


def schedule_of(params: dict | None) -> list[tuple[str, str]]:
    """(label, pct) of a quotation — its own copy, else the built-in schedule it was printed with before M26."""
    rows = (params or {}).get("payment_schedule")
    if isinstance(rows, list) and rows: return [(r["label"], str(r["pct"])) for r in rows]
    return list(BUILTIN_SCHEDULE)


def terms_of(params: dict | None) -> list[str]:
    rows = (params or {}).get("terms")
    return list(rows) if isinstance(rows, list) else list(BUILTIN_TERMS)
