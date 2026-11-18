import pytest
from dataclasses import dataclass
from app.services.dimensions import extract_candidates, parse_line

def one(text, conf=100):
    r = parse_line(text, conf); assert len(r) == 1, [c.to_dict() for c in r]; return r[0]
def pairs(text, conf=100): return {(c.label, c.value_mm) for c in parse_line(text, conf)}

@pytest.mark.parametrize("text,mm", [("2750 mm", 2750), ("2750mm", 2750), ("4.25 m", 4250), ("4.25m", 4250), ("425 cm", 4250), ("4,250 mm", 4250), ("4,25 m", 4250)])
def test_units_convert_to_mm(text, mm): assert one(text).value_mm == pytest.approx(mm)

@pytest.mark.parametrize("text,mm", [("14'-0\"", 4267.2), ("12'6\"", 3810.0), ("10'", 3048.0), ("9' 6\"", 2895.6)])
def test_feet_inches(text, mm): assert one(text).value_mm == pytest.approx(mm, abs=0.2)

def test_room_pair_larger_side_is_length():
    assert pairs("2400 x 3200 mm") == {("Length", 3200.0), ("Width", 2400.0)}
    assert pairs("3.2m x 2.4m") == {("Length", 3200.0), ("Width", 2400.0)}

def test_door_and_window_pairs_keep_width_height_order():
    assert pairs("Door 900x2100") == {("Door Width", 900.0), ("Door Height", 2100.0)}      # RapidOCR drops spaces around x
    assert pairs("WIN 1500 x 1200") == {("Window Width", 1500.0), ("Window Height", 1200.0)}

def test_labels_from_context():
    assert one("Ceiling height: 2750 mm").label == "Ceiling Height"
    assert one("Length 4250 mm").label == "Length" and one("W: 3600 mm").label == "Width"
    assert one("4250 mm").label is None
    assert one("Door 900 mm").label is None          # single door value is ambiguous -> user decides

def test_bare_numbers_are_low_confidence_and_range_limited():
    c = one("4250", 96); assert c.confidence < 60 and "assumed mm" in c.note
    assert parse_line("12", 99) == [] and parse_line("999999", 99) == []   # too small / too big to be a room dimension
    assert parse_line("Tel 98765 43210", 99) == []                          # phone digits are out of range, so ignored outright
    noise = parse_line("Drawn 2024", 99)                                    # a year IS in range, so it slips through...
    assert noise and all(c.confidence < 60 for c in noise)                  # ...but only at low confidence (the UI leaves it unticked)

def test_unitless_small_pairs_are_flagged_not_trusted():
    c = {x.label: x for x in parse_line("14 x 12", 100)}
    assert c["Length"].value_mm == pytest.approx(4267.2) and "feet" in c["Length"].note and c["Length"].confidence < 70

def test_implausible_values_are_dropped_or_flagged():
    assert parse_line("5 mm", 100) == [] and parse_line("90000 mm", 100) == []
    c = one("Ceiling 9000 mm"); assert "Unusual" in c.note and c.confidence < 100

def test_confidence_is_scaled_by_ocr_confidence():
    assert one("2750 mm", 74).confidence == 74.0 and one("2750 mm", 100).confidence == 100.0

def test_text_without_dimensions_yields_nothing():
    assert parse_line("MASTER BEDROOM", 99) == [] and parse_line("", 99) == []

@dataclass
class B: text: str; confidence: float; bbox: list; page: int = 0

def test_extract_dedupes_and_orders_labelled_first():
    blocks = [B("4250", 90, [0, 0, 1, 1]), B("Length 4250 mm", 80, [0, 0, 1, 1]), B("Length 4250 mm", 95, [0, 0, 1, 1]), B("Ceiling height: 2750 mm", 99, [0, 0, 1, 1])]
    out = extract_candidates(blocks)
    assert [(c.label, c.value_mm) for c in out][:2] == [("Ceiling Height", 2750.0), ("Length", 4250.0)]
    assert [c.confidence for c in out if c.label == "Length"] == [95.0]     # the duplicate kept the better reading
    assert out[-1].label is None                                            # the unlabelled bare 4250 is last
