"""Canonical Room Model rules.
Source priority: USER_VERIFIED > SITE_SURVEY > FLOOR_PLAN > OCR > VLM > AI_ESTIMATE.
A value may only be replaced by one of equal-or-higher priority, and a verified
value can only be replaced by USER_VERIFIED.
"""
PRIORITY = ["USER_VERIFIED", "SITE_SURVEY", "FLOOR_PLAN", "OCR", "VLM", "AI_ESTIMATE"]
_RANK = {s: i for i, s in enumerate(PRIORITY)}   # lower index = stronger

def can_overwrite(existing_source: str, existing_verified: bool, new_source: str) -> bool:
    if new_source not in _RANK:
        raise ValueError(f"Unknown source: {new_source}")
    if existing_verified:
        return new_source == "USER_VERIFIED"
    return _RANK[new_source] <= _RANK[existing_source]

def apply_measurement(existing, label: str, value: float, unit: str, source: str, confidence: float, verified: bool):
    """Returns (record_dict, applied: bool). Never silently overrides stronger data."""
    rec = dict(label=label, value=value, unit=unit, source=source, confidence=confidence,
               verified=verified and source == "USER_VERIFIED")
    if existing is None:
        return rec, True
    if can_overwrite(existing["source"], existing["verified"], source):
        return rec, True
    return dict(existing), False
