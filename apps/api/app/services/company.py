"""Company profile: stored in company_settings (Settings -> Company), falling back to the environment (.env) for anything not set yet."""
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import models as m

FIELDS = {   # key: (label, default from env, max length)
    "name": ("Company name", lambda: settings.COMPANY_NAME, 120),
    "address": ("Address", lambda: settings.COMPANY_ADDRESS, 400),
    "phone": ("Phone", lambda: settings.COMPANY_PHONE, 40),
    "email": ("Email", lambda: settings.COMPANY_EMAIL, 120),
    "gstin": ("GSTIN", lambda: settings.COMPANY_GSTIN, 15),
    "quote_valid_days": ("Quotation validity (days)", lambda: settings.QUOTE_VALID_DAYS, None),
    "warranty_months": ("Default warranty (months)", lambda: 12, None),
    "board_sku_18": ("18mm carcass board SKU (for cutting-list purchasing)", lambda: "", 40),
    "board_sku_8": ("8mm back panel board SKU", lambda: "", 40),
    "edge_band_sku": ("Edge band SKU (bought per r.m)", lambda: "", 40),
    "gst_enabled": ("Charge GST by default (new quotations start with GST on)", lambda: True, None),
    "default_gst_pct": ("Default GST rate (%)", lambda: 18, None),
    "sac_code": ("SAC / HSN code printed on invoices", lambda: "9954", 10),
    "invoice_prefix": ("Invoice number prefix", lambda: "INV", 10),
    "limit_staff_to_projects": ("Limit staff to their projects (staff see only projects whose team they're on)", lambda: False, None),
    "all_projects_roles": ("Roles that see every project anyway (comma separated; admins always do)", lambda: "PROCUREMENT_MANAGER, INVENTORY_MANAGER", 200),
}
INT_KEYS = {"quote_valid_days": (1, 365), "warranty_months": (0, 120), "default_gst_pct": (0, 28)}
BOOL_KEYS = {"gst_enabled", "limit_staff_to_projects"}


def state_code(gstin: str | None) -> str | None:
    """First two digits of a GSTIN = the GST state code (place of business)."""
    return gstin[:2] if gstin and len(gstin) == 15 and gstin[:2].isdigit() else None


def get(db: Session) -> dict:
    stored = {r.key: r.value for r in db.query(m.CompanySetting)}
    return {k: (stored[k] if stored.get(k) is not None else d()) for k, (_, d, _) in FIELDS.items()}
