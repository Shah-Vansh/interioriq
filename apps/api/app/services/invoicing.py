"""Invoices against an approved quotation. GST is OPTIONAL and follows the quotation's own GST switch:
- quotation GST ON  → TAX invoice: the amount already includes GST; it is split into taxable value + CGST/SGST (same state) or IGST (other state).
- quotation GST OFF → PLAIN invoice: no GST anywhere.
All money is Decimal; every split sums back to the invoice amount exactly."""
from datetime import date
from decimal import Decimal

from app.services.cost_engine import D, q

STATES = {"01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
          "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
          "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
          "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala",
          "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh", "97": "Other Territory"}


def financial_year(d: date) -> str:
    """Indian financial year April–March: 17 Nov 2026 → '2026-27', 10 Feb 2027 → '2026-27'."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def split(amount, gst_rate, intra_state: bool) -> dict:
    """GST-inclusive amount → taxable + CGST/SGST or IGST. tax = amount − taxable, so the parts always add back to the amount."""
    amount, rate = q(D(amount)), D(gst_rate)
    if rate <= 0: return {"taxable": amount, "cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": Decimal("0.00")}
    taxable = q(amount * 100 / (100 + rate)); tax = amount - taxable
    if intra_state:
        cgst = q(tax / 2); return {"taxable": taxable, "cgst": cgst, "sgst": tax - cgst, "igst": Decimal("0.00")}
    return {"taxable": taxable, "cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": tax}


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
         "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n: int) -> str:
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else ""))


def _three(n: int) -> str:
    h, r = divmod(n, 100)
    return " ".join(x for x in ((_ONES[h] + " Hundred") if h else "", _two(r) if r else "") if x)


def words(amount) -> str:
    """Indian system: 125430.50 → 'Rupees One Lakh Twenty Five Thousand Four Hundred Thirty and Fifty Paise Only'."""
    a = q(D(amount)); rupees, paise = int(a), int((a - int(a)) * 100)
    parts, n = [], rupees
    for size, name in ((10_000_000, "Crore"), (100_000, "Lakh"), (1000, "Thousand")):
        if n >= size:
            k, n = divmod(n, size)
            parts.append(f"{words_int(k)} {name}")
    if n: parts.append(_three(n))
    text = "Rupees " + (" ".join(parts) if parts else "Zero")
    if paise: text += f" and {_two(paise)} Paise"
    return text + " Only"


def words_int(n: int) -> str:
    """Words for a count of crores/lakhs/thousands (may itself be large for crores)."""
    if n < 1000: return _three(n)
    return words(n).removeprefix("Rupees ").removesuffix(" Only")
