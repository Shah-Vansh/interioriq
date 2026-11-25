"""Add ready-made catalogue items to an EXISTING database (the dev seed only fills brand-new ones).

    cd apps/api
    python -m app.catalogue_pack list                 # what each pack contains
    python -m app.catalogue_pack add bathroom utility # adds only SKUs that don't exist yet (backup first, see below)

Items go through the normal catalogue code (price history 'Item created'), with stock 0 — record real stock in Catalogue → Stock in.
Prices are typical market figures to start from: check them with your suppliers (Catalogue → item → Change price, which is logged).
A backup is made first unless --no-backup."""
import sys
from decimal import Decimal

from app.core.database import SessionLocal, engine, migrate
from app.models import models as m
from app.services import catalogue as cat

NOTE = "Starter item — check price and size with your supplier."
# sku, name, category, L, W, H, price, cost, material, style, mount_mm
PACKS = {
    "bathroom": [
        ("WC-WH-001", "Wall-hung WC with concealed cistern", "WC", 360, 540, 400, 24000, 17500, "Vitreous china", "modern, minimal", None),
        ("WC-FL-001", "Floor-mounted WC (one piece)", "WC", 380, 680, 760, 14500, 10500, "Vitreous china", "traditional", None),
        ("VAN-800-001", "Vanity Unit 800 with basin", "Vanity", 800, 480, 850, 32000, 23000, "BWP ply + quartz top", "modern", None),
        ("VAN-600-001", "Vanity Unit 600 with basin", "Vanity", 600, 450, 850, 24000, 17000, "BWP ply + ceramic basin", "minimal", None),
        ("SHW-900-001", "Shower Enclosure 900 x 900", "Shower Enclosure", 900, 900, 2000, 38000, 27000, "8 mm toughened glass", "modern", None),
        ("SHW-1200-001", "Shower Enclosure 1200 x 800", "Shower Enclosure", 1200, 800, 2000, 46000, 33000, "8 mm toughened glass", "luxury", None),
        ("MIR-800-001", "Mirror Cabinet 800", "Mirror Cabinet", 800, 150, 700, 12500, 8800, "Mirror + ply", "modern", 1300),
        ("MIR-600-001", "Mirror Cabinet 600", "Mirror Cabinet", 600, 150, 700, 9500, 6600, "Mirror + ply", "minimal", 1300),
        ("LIN-450-001", "Linen Cabinet 450", "Linen Cabinet", 450, 350, 1800, 16000, 11000, "BWP ply, laminate", "minimal", None),
    ],
    "utility": [
        ("WM-FL-001", "Washing machine space (front-loading)", "Washing Machine", 600, 600, 850, 0, 0, None, None, None),
        ("UTB-900-001", "Utility Base Cabinet 900", "Utility Base", 900, 560, 850, 19000, 13500, "BWP ply, laminate", None, None),
        ("UTB-600-001", "Utility Base Cabinet 600", "Utility Base", 600, 560, 850, 14500, 10200, "BWP ply, laminate", None, None),
        ("UTT-600-001", "Utility Tall Cabinet 600 (brooms)", "Utility Tall", 600, 560, 2100, 27000, 19000, "BWP ply, laminate", None, None),
        ("UTW-900-001", "Utility Wall Cabinet 900", "Utility Wall", 900, 350, 700, 13000, 9100, "BWP ply, laminate", None, 1450),
    ],
    "home": [
        ("OCH-CANE-001", "Cane Lounge Chair", "Outdoor Chair", 680, 720, 820, 14500, 10200, "Cane + teak frame", "traditional, boho", None),
        ("OTB-TEAK-001", "Outdoor Side Table — Teak", "Outdoor Table", 550, 550, 450, 7800, 5400, "Teak", "traditional", None),
        ("PLN-LRG-001", "Large Planter with Areca Palm", "Planter", 450, 450, 1400, 4200, 2900, "Ceramic pot", "boho, scandinavian", None),
        ("SHR-900-001", "Shoe Rack 900 with seat", "Shoe Rack", 900, 350, 1000, 16500, 11500, "BWP ply, laminate", "modern", None),
        ("CON-WLT-001", "Console Table — Walnut", "Console Table", 1100, 350, 780, 18500, 13000, "Walnut veneer", "modern, luxury", None),
        ("PJU-900-001", "Pooja Unit 900 with drawers", "Pooja Unit", 900, 450, 1800, 42000, 30000, "Teak veneer, brass bells", "traditional", None),
        ("STR-900-001", "Storage Unit 900 (store room)", "Storage", 900, 450, 2100, 24000, 17000, "BWP ply, laminate", None, None),
    ],
}
USER = {"sub": None, "name": "Catalogue pack"}


def add(packs: list[str]) -> list[str]:
    db = SessionLocal(); added = []
    try:
        for p in packs:
            for sku, name, category, L, W, H, price, cost, material, style, mount in PACKS[p]:
                if db.query(m.FurnitureItem).filter(m.FurnitureItem.sku == sku).first(): continue
                cat.create_item(db, cat.ItemIn(sku=sku, name=name, kind="FURNITURE", category=category, unit="No.", price=Decimal(price),
                                               cost_price=Decimal(cost) if cost else None, stock=0, length_mm=L, width_mm=W, height_mm=H,
                                               material=material, style=style, mount_mm=mount, description=NOTE), USER)
                added.append(sku)
        db.commit(); return added
    except Exception:
        db.rollback(); raise
    finally: db.close()


def main(argv):
    if not argv or argv[0] not in ("list", "add"):
        print(__doc__); return 2
    if argv[0] == "list":
        for p, rows in PACKS.items(): print(f"{p}: " + ", ".join(f"{r[0]} ({r[1]})" for r in rows))
        return 0
    packs = [a for a in argv[1:] if not a.startswith("--")] or list(PACKS)
    bad = [p for p in packs if p not in PACKS]
    if bad: print(f"Unknown pack(s): {', '.join(bad)}. Packs: {', '.join(PACKS)}"); return 2
    migrate(engine)
    if "--no-backup" not in argv:
        from app.services import backup as bk
        made = bk.create(kind="manual", include_files=True, by="before catalogue pack"); print(f"Backup: {made['name']}")
    added = add(packs)
    print(f"Added {len(added)} item(s): {', '.join(added) if added else 'none (all already there)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
