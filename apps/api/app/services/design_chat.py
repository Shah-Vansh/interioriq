"""M35 Design chat for the AI Designer — zero cost, works with no model installed.

The chat only turns what the designer types into OPTIONS for the deterministic layout generator (style, price tier, budget, items to leave
out or bring back, kitchen shape, dining seats) — or answers a catalogue question from the DATABASE. It never places furniture, never does
geometry and never computes money (constraint 2): the generator and the cost engine do that, and every number shown comes from the server.

Reading the message: a built-in rule-based reader always runs; when a local Ollama model is reachable (Settings → AI engines) it is asked
for the same JSON, and its answer is used only after strict validation (unknown keys / values are dropped) — otherwise the rules win."""
import json
import re
from decimal import Decimal

import httpx

from app.core.config import settings
from app.services import layouts
from app.services.providers import STYLE_WORDS

TIERS = {"BUDGET": ("cheaper", "cheap", "budget", "low cost", "lower cost", "less expensive", "economical", "affordable", "save money"),
         "PREMIUM": ("premium", "luxur", "high end", "high-end", "expensive", "best quality", "upgrade", "top quality"),
         "BALANCED": ("balanced", "mid range", "mid-range", "standard")}
SHAPES = {"L": ("l-shaped", "l shaped", "l shape", "l-shape"), "U": ("u-shaped", "u shaped", "u shape", "u-shape"),
          "PARALLEL": ("parallel", "galley", "two wall", "two-wall"), "STRAIGHT": ("straight", "single wall", "one wall", "one-wall", "linear")}
QUESTION = re.compile(r"^\s*(what|which|how many|how much|do we have|do you have|show me|list|any)\b", re.I)
AMOUNT = re.compile(r"(?:₹|rs\.?|inr)?\s*(\d+(?:[.,]\d+)?)\s*(crore|cr|lakhs?|lacs?|l\b|k\b|thousand)?", re.I)


def _slot_words() -> dict:
    """phrase → slot, from the generator's own labels and catalogue categories (longest phrases first)."""
    out = {}
    for slot, cats in layouts.SLOTS.items():
        for w in {layouts.LABEL[slot].lower(), *cats}: out.setdefault(w, slot)        # the first (room-specific) slot keeps a shared word
    out.update({"tv": "tv", "coffee table": "coffee", "bedside": "bedside", "side tables": "bedside", "mirror": "mirror", "shower": "shower",
                "wall cabinets": "wall_unit", "wall units": "wall_unit", "fillers": "filler", "chair": "desk_chair", "armchairs": "armchair",
                "bookshelves": "bookshelf", "linen": "linen", "dresser": "dresser", "crockery": "crockery"})
    return dict(sorted(out.items(), key=lambda kv: -len(kv[0])))


def money(text: str) -> Decimal | None:
    for mt in AMOUNT.finditer(text or ""):
        n, unit = mt.group(1).replace(",", ""), (mt.group(2) or "").lower()
        if not unit and len(n.split(".")[0]) < 4: continue                 # '2 people', '6 seater' are not money
        v = Decimal(n) * (Decimal(10_000_000) if unit.startswith("cr") else Decimal(100_000) if unit[:1] == "l" else Decimal(1000) if unit in ("k", "thousand") else 1)
        if v >= 1000: return v.quantize(Decimal("0.01"))
    return None


def rules(message: str, kind: str | None) -> dict:
    p = " " + (message or "").lower() + " "
    ch: dict = {}
    for tier, words in TIERS.items():
        if any(w in p for w in words): ch["tier"] = tier; break
    styles = [s for s in STYLE_WORDS if s in p]
    if styles: ch["styles"] = styles[:1]
    if re.search(r"\b(under|below|within|max(imum)?|upto|up to|budget( of| is)?|not more than|around|about)\b", p) and (b := money(p)): ch["budget"] = b
    if re.search(r"\b(no|remove|without|drop|skip|leave out|don'?t want|get rid of)\b", p) or re.search(r"\b(add|include|with|bring back|put|need)\b", p):
        optional = set(layouts.OPTIONAL.get(kind or "", ())) if kind else {s for v in layouts.OPTIONAL.values() for s in v}
        words = _slot_words(); taken = set()
        for phrase, slot in words.items():
            if slot not in optional or slot in taken: continue
            mt = re.search(rf"\b(no|remove|without|drop|skip|leave out|don'?t want|get rid of|add|include|with|bring back|put|need)\b(?:\s+(?:the|a|an|any|some))?\s+{re.escape(phrase)}s?\b", p)
            if not mt: continue
            taken.add(slot)
            if mt.group(1) in ("add", "include", "with", "bring back", "put", "need"): ch.setdefault("add", []).append(slot)
            else: ch.setdefault("skip", []).append(slot)
    for shape, words in SHAPES.items():
        if any(w in p for w in words): ch["kitchen_shape"] = shape; break
    if mt := re.search(r"(\d+)\s*[- ]?\s*(seater|seats|people|persons|chairs)", p): ch["seats"] = max(1, min(12, int(mt.group(1))))
    return ch


SYSTEM = ("You turn an interior designer's request into JSON for a layout generator. Reply with JSON ONLY, keys optional: "
          '{"tier": "BUDGET"|"BALANCED"|"PREMIUM", "styles": [one of modern, luxury, scandinavian, minimal, traditional, industrial], '
          '"budget_inr": number, "skip": [item slots to leave out], "add": [item slots to bring back], "kitchen_shape": "STRAIGHT"|"L"|"PARALLEL"|"U", '
          '"seats": number, "reply": "one short friendly sentence"}. Item slots: ')


def _clean(raw: dict, kind: str | None) -> dict:
    optional = set(layouts.OPTIONAL.get(kind or "", ())) if kind else {s for v in layouts.OPTIONAL.values() for s in v}
    out: dict = {}
    if str(raw.get("tier", "")).upper() in layouts.TIERS: out["tier"] = str(raw["tier"]).upper()
    st = [s for s in (raw.get("styles") or []) if isinstance(s, str) and s.lower() in STYLE_WORDS]
    if st: out["styles"] = [st[0].lower()]
    try:
        b = Decimal(str(raw.get("budget_inr"))) if raw.get("budget_inr") not in (None, "", 0) else None
        if b is not None and Decimal(1000) <= b <= Decimal(1_000_000_000): out["budget"] = b.quantize(Decimal("0.01"))
    except Exception: pass
    for k in ("skip", "add"):
        v = [s for s in (raw.get(k) or []) if isinstance(s, str) and s in optional]
        if v: out[k] = v
    if str(raw.get("kitchen_shape", "")).upper() in ("STRAIGHT", "L", "PARALLEL", "U"): out["kitchen_shape"] = str(raw["kitchen_shape"]).upper()
    if isinstance(raw.get("seats"), (int, float)) and 1 <= raw["seats"] <= 12: out["seats"] = int(raw["seats"])
    return out


def ollama(message: str, kind: str | None) -> tuple[dict, str | None] | None:
    if not settings.DESIGN_CHAT_LLM: return None
    try:
        slots = ", ".join(sorted({s for v in layouts.OPTIONAL.values() for s in v}))
        r = httpx.post(f"{settings.OLLAMA_BASE_URL}/api/chat", timeout=25, json={"model": settings.OLLAMA_LLM_MODEL, "stream": False, "format": "json",
                       "messages": [{"role": "system", "content": SYSTEM + slots + f". Room type: {kind or 'unknown'}."}, {"role": "user", "content": message}]})
        r.raise_for_status()
        raw = json.loads(re.search(r"\{.*\}", r.json()["message"]["content"], re.S).group())
        reply = raw.get("reply") if isinstance(raw.get("reply"), str) else None
        return _clean(raw, kind), (reply or "")[:300] or None
    except Exception:
        return None


def interpret(message: str, kind: str | None) -> dict:
    """{'changes': {...}, 'source': 'rules'|'ollama', 'llm_reply': str|None, 'question': bool}"""
    base = rules(message, kind); source, llm_reply = "rules", None
    got = ollama(message, kind)
    if got is not None:
        llm, llm_reply = got
        if llm: base = {**base, **llm}; source = "ollama"
    return {"changes": base, "source": source, "llm_reply": llm_reply, "question": bool(QUESTION.search(message or "")) or ((message or "").strip().endswith("?") and not (set(base) - {"budget", "styles"}))}


def apply(options: dict, budget: Decimal | None, ch: dict) -> tuple[dict, Decimal | None, list[str]]:
    """New generator options + budget, and a plain-English list of what changed (for the reply)."""
    o = {"skip": list(options.get("skip") or []), "tier": options.get("tier") or "BALANCED", "styles": list(options.get("styles") or []),
         "kitchen_shape": options.get("kitchen_shape") or "AUTO", "seats": options.get("seats")}
    said = []
    if "tier" in ch and ch["tier"] != o["tier"]: o["tier"] = ch["tier"]; said.append({"BUDGET": "cheaper items first", "PREMIUM": "premium items first", "BALANCED": "balanced choice of items"}[ch["tier"]])
    if "styles" in ch and ch["styles"] != o["styles"]: o["styles"] = ch["styles"]; said.append(f"{ch['styles'][0]} style preferred")
    for s in ch.get("skip", []):
        if s not in o["skip"]: o["skip"].append(s); said.append(f"no {layouts.LABEL[s].lower()}")
    for s in ch.get("add", []):
        if s in o["skip"]: o["skip"].remove(s); said.append(f"{layouts.LABEL[s].lower()} back in")
    if "kitchen_shape" in ch and ch["kitchen_shape"] != o["kitchen_shape"]: o["kitchen_shape"] = ch["kitchen_shape"]; said.append(f"{ch['kitchen_shape'].lower()} kitchen")
    if "seats" in ch and ch["seats"] != o["seats"]: o["seats"] = ch["seats"]; said.append(f"seating for {ch['seats']}")
    if "budget" in ch and ch["budget"] != budget: budget = ch["budget"]; said.append(f"budget Rs. {budget:,.0f}")
    return o, budget, said
