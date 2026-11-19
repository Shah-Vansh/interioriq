"""Catalogue packs: add bathroom/utility starter items to an existing database through the normal catalogue code (price history, stock 0),
only SKUs that don't exist yet, run twice = no change; the items then lay out a bathroom."""
from app import catalogue_pack as cp
from app.core.database import SessionLocal, engine, migrate
from app.models import models as m


def test_pack_adds_missing_items_once(monkeypatch):
    migrate(engine)
    db = SessionLocal()
    try:
        for sku in ("WC-FL-001", "SHW-1200-001", "UTB-600-001"):      # not in the dev seed → added
            it = db.query(m.FurnitureItem).filter_by(sku=sku).first()
            if it: db.query(m.PriceChange).filter_by(item_id=it.id).delete(); db.query(m.StockMovement).filter_by(item_id=it.id).delete(); db.delete(it)
        db.commit()
    finally: db.close()
    added = cp.add(["bathroom", "utility"])
    assert {"WC-FL-001", "SHW-1200-001", "UTB-600-001"} <= set(added)
    assert cp.add(["bathroom", "utility"]) == []
    db = SessionLocal()
    try:
        it = db.query(m.FurnitureItem).filter_by(sku="SHW-1200-001").first()
        assert it.stock == 0 and it.category == "Shower Enclosure" and it.is_active and it.length_mm == 1200
        assert db.query(m.PriceChange).filter_by(item_id=it.id).count() >= 1                        # logged like any new item
    finally: db.close()
    assert cp.main(["list"]) == 0 and cp.main(["add", "nope"]) == 2
