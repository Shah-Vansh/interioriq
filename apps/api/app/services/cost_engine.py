"""Deterministic, Decimal-safe cost engine. No LLM, no floats for money."""
import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

TWO = Decimal("0.01")
def q(x: Decimal) -> Decimal: return x.quantize(TWO, rounding=ROUND_HALF_UP)
def D(x) -> Decimal: return x if isinstance(x, Decimal) else Decimal(str(x))

@dataclass(frozen=True)
class Line:
    qty: Decimal; rate: Decimal; labour: Decimal = Decimal("0")
    @property
    def total(self) -> Decimal: return q(self.qty * (self.rate + self.labour))

def compute(lines: list[Line], overhead_pct="8", margin_pct="18", discount_pct="5", gst_pct="18",
            transport="0", installation="0") -> dict:
    sub = q(sum((l.total for l in lines), Decimal("0")) + D(transport) + D(installation))
    overhead = q(sub * D(overhead_pct) / 100)
    with_oh = sub + overhead
    margin = q(with_oh * D(margin_pct) / 100)
    pre_tax = with_oh + margin
    discount = q(pre_tax * D(discount_pct) / 100)
    after = pre_tax - discount
    gst = q(after * D(gst_pct) / 100)
    return {"subtotal": sub, "overhead": overhead, "margin": margin, "pre_tax": pre_tax,
            "discount": discount, "after_discount": after, "gst": gst, "grand_total": after + gst}


def inr(x) -> str:
    """Indian digit grouping, always 2 decimals: 1234567.5 -> '12,34,567.50'. No currency symbol (PDF fonts vary)."""
    d = q(D(x)); sign = "-" if d < 0 else ""; whole, frac = f"{abs(d):.2f}".split(".")
    if len(whole) > 3:
        whole = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", whole[:-3]) + "," + whole[-3:]
    return f"{sign}{whole}.{frac}"


def split_payments(total, percents: list) -> list[Decimal]:
    """Split `total` by percentages. Each share is rounded to paise and the LAST one absorbs the remainder, so the parts always sum to the total exactly."""
    total = q(D(total)); pcts = [D(str(p)) for p in percents]
    if sum(pcts) != 100: raise ValueError("Percentages must add up to 100")
    parts = [q(total * p / 100) for p in pcts[:-1]]
    return parts + [total - sum(parts, Decimal("0"))]
