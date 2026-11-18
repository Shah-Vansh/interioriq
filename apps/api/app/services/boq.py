"""Design Model -> BOQ. Deterministic: no LLM, exact decimals. Prices come from the catalogue AS OF NOW, never from the design's saved snapshot."""
from decimal import Decimal

from app.services.cost_engine import Line, compute, q

DEFAULTS = {"overhead_pct": "8", "margin_pct": "18", "discount_pct": "5", "gst_pct": "18", "labour_pct": "8", "transport": "0", "installation": "0", "gst_enabled": "true"}


def gst_on(params: dict) -> bool:
    """Was GST charged on this BOQ? BOQs saved before the switch existed count as GST-on when their rate was above 0."""
    flag = str(params.get("gst_enabled", "")).lower()
    if flag in ("false", "0"): return False
    return Decimal(str(params.get("gst_pct", "0"))) > 0


def normalize_params(raw: dict, company_default: bool) -> dict:
    """Request params → stored strings. gst_enabled missing → company default; off → GST rate forced to 0 so no GST is computed or printed."""
    p = {k: str(v) for k, v in raw.items() if k != "gst_enabled"}
    on = company_default if raw.get("gst_enabled") is None else bool(raw.get("gst_enabled"))
    p["gst_enabled"] = "true" if on else "false"
    if not on: p["gst_pct"] = "0"
    return p


class BoqError(Exception):
    def __init__(self, status: int, message: str): self.status, self.message = status, message


def build(objects: list[dict], by_sku: dict, by_name: dict, params: dict, suppliers: dict | None = None, takeoff: list[dict] | None = None) -> tuple[list[dict], list[str], dict]:
    """Returns (items, warnings, totals). `by_sku` / `by_name` map to catalogue rows (sku, name, category, material, price, stock)."""
    groups: dict[tuple, dict] = {}
    for o in objects:
        item = by_sku.get(o.get("sku") or "") or by_name.get(o["name"])      # name fallback: designs saved before SKUs existed
        key = ("sku", item.sku) if item else ("free", o["name"], o["category"], round(float(o.get("price", 0)), 2))
        g = groups.setdefault(key, {"item": item, "obj": o, "qty": 0}); g["qty"] += 1

    items, lines, warnings, unpriced = [], [], [], []
    labour_pct = Decimal(str(params["labour_pct"]))
    for g in groups.values():
        item, o, qty = g["item"], g["obj"], g["qty"]
        snapshot = Decimal(str(o.get("price", 0)))
        if item:
            rate = Decimal(str(item.price)); name, sku, cat, mat, flags = item.name, item.sku, item.category, item.material, []
            if snapshot > 0 and abs(snapshot - rate) >= Decimal("0.01"):
                warnings.append(f"{name}: price changed since the design was saved ({snapshot:.2f} -> {rate:.2f}); the BOQ uses the current catalogue price.")
            if item.is_active is False:
                warnings.append(f"{name}: archived in the catalogue (no longer offered); confirm before ordering.")
            if qty > (item.stock or 0):
                warnings.append(f"{name}: {qty} needed but only {item.stock or 0} in stock.")
        else:
            rate, name, sku, cat, mat, flags = snapshot, o["name"], o.get("sku") or None, o["category"], None, ["NOT_IN_CATALOGUE"]
            warnings.append(f"{name}: not found in the catalogue; priced from the design's saved price ({snapshot:.2f}).")
        if rate <= 0: unpriced.append(name)
        labour = q(rate * labour_pct / 100)
        line = Line(Decimal(qty), rate, labour); lines.append(line)
        sup = (suppliers or {}).get(item.supplier_id) if item and item.supplier_id else None
        items.append({"sku": sku, "category": cat, "description": name, "material": mat, "qty": Decimal(qty), "unit": (item.unit if item else None) or "No.",
                      "rate": rate, "labour": labour, "total": line.total, "supplier": sup.name if sup else None, "flags": flags})
    for t in takeoff or []:                                   # material & services take-off (services/takeoff.plan)
        it, qty = t["item"], Decimal(str(t["qty"]))
        rate = Decimal(str(it.price))
        if rate <= 0: unpriced.append(it.name); continue
        labour = q(rate * labour_pct / 100)
        line = Line(qty, rate, labour); lines.append(line)
        sup = (suppliers or {}).get(it.supplier_id) if it.supplier_id else None
        items.append({"sku": it.sku, "category": it.category, "description": t["description"], "material": it.material, "qty": qty, "unit": it.unit or "No.",
                      "rate": rate, "labour": labour, "total": line.total, "supplier": sup.name if sup else None, "flags": ["TAKEOFF"]})
    if unpriced:
        raise BoqError(409, "Cannot build a BOQ: no price for " + ", ".join(unpriced) + ". Set a catalogue price first.")

    transport, installation = Decimal(str(params["transport"])), Decimal(str(params["installation"]))
    for label, value in (("Transport", transport), ("Installation", installation)):
        if value > 0:
            items.append({"sku": None, "category": label, "description": f"{label} (lump sum)", "material": None, "qty": Decimal(1), "unit": "Lump",
                          "rate": value, "labour": Decimal(0), "total": value, "supplier": None, "flags": []})
    totals = compute(lines, params["overhead_pct"], params["margin_pct"], params["discount_pct"], params["gst_pct"], transport, installation)
    items.sort(key=lambda i: (i["category"] in ("Transport", "Installation"), "TAKEOFF" in (i["flags"] or []), i["category"], i["description"]))
    return items, warnings, totals
