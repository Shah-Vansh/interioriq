import json, re
import httpx
from app.core.config import settings

class LLMProvider:
    def extract_requirements(self, prompt: str) -> dict: raise NotImplementedError

STYLE_WORDS = ("modern", "luxury", "scandinavian", "minimal", "traditional", "industrial")


def _rule_based(prompt: str) -> dict:
    """Deterministic fallback so the platform works with no model installed."""
    p = prompt.lower()
    budget = None
    m = re.search(r"(?:₹|rs\.?\s*)?(\d+(?:\.\d+)?)\s*(l|lakh|lakhs|cr|crore)", p)
    if m:
        budget = float(m.group(1)) * (100_000 if m.group(2).startswith("l") else 10_000_000)
    styles = [s for s in STYLE_WORDS if s in p]
    cats = [c for c in ["bed", "wardrobe", "sofa", "desk", "tv unit", "dining"] if c in p]
    return {"style": " ".join(styles) or "modern", "styles": styles, "budget": budget, "priority": cats, "source": "rule_based"}   # styles: only what the brief SAYS

class LocalLLMProvider(LLMProvider):
    def extract_requirements(self, prompt: str) -> dict:
        try:
            r = httpx.post(f"{settings.OLLAMA_BASE_URL}/api/chat", timeout=60, json={
                "model": settings.OLLAMA_LLM_MODEL, "stream": False,
                "messages": [{"role": "system", "content": "Reply with JSON only: {style, budget_inr, priority:[furniture categories]}"},
                             {"role": "user", "content": prompt}]})
            r.raise_for_status()
            m = re.search(r"\{.*\}", r.json()["message"]["content"], re.S)
            data = json.loads(m.group())
            st = [w for w in str(data.get("style") or "").lower().replace(",", " ").split() if w in STYLE_WORDS]
            return {"style": data.get("style", "modern"), "styles": st, "budget": data.get("budget_inr"),
                    "priority": data.get("priority", []), "source": "ollama"}
        except Exception:
            return _rule_based(prompt)
