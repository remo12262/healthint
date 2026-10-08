"""Registro dei costi giornalieri delle chiamate a Claude, con avviso nei log oltre soglia.

Il costo si calcola dai token riportati dall'API in ogni risposta (response.usage).
Il registro vive in memoria e in COST_LOG_FILE: su Render il disco si azzera a ogni
deploy, quindi fanno fede le righe "[costi]" nei log del servizio.
"""
import json
import os
import threading
from datetime import datetime, timezone

# Dollari per milione di token (input, output). Prezzi pubblici Anthropic.
PRICES = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-opus-4-5": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
}
DEFAULT_PRICE = (5.00, 25.00)  # modello sconosciuto: si stima per eccesso
CACHE_WRITE_FACTOR = 1.25
CACHE_READ_FACTOR = 0.10
WEB_SEARCH_USD = 0.01  # per ricerca (10 $ ogni 1000)

ALERT_USD = float(os.environ.get("AI_COST_ALERT_USD", "0.20"))
COST_LOG_FILE = os.environ.get("COST_LOG_FILE", "ai_costs.json")
KEEP_DAYS = 60

_lock = threading.Lock()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _price(model: str):
    for prefix, price in PRICES.items():
        if model.startswith(prefix):
            return price
    return DEFAULT_PRICE


def _load() -> dict:
    try:
        with open(COST_LOG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_days = _load()


def _save():
    try:
        with open(COST_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(_days, f, indent=1)
    except Exception as e:
        print(f"[costi] Impossibile salvare il registro: {e}")


def call_cost(model: str, usage) -> float:
    """Costo in dollari di una risposta, da response.usage."""
    p_in, p_out = _price(model)
    get = lambda name: getattr(usage, name, 0) or 0
    cost = (
        get("input_tokens") * p_in
        + get("cache_creation_input_tokens") * p_in * CACHE_WRITE_FACTOR
        + get("cache_read_input_tokens") * p_in * CACHE_READ_FACTOR
        + get("output_tokens") * p_out
    ) / 1_000_000
    server = getattr(usage, "server_tool_use", None)
    if server is not None:
        cost += (getattr(server, "web_search_requests", 0) or 0) * WEB_SEARCH_USD
    return cost


def record(model: str, response, label: str = "") -> float:
    """Registra il costo di una risposta di Claude e avvisa nei log se si supera la soglia."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0.0
    cost = call_cost(model, usage)
    day = _today()
    with _lock:
        d = _days.setdefault(day, {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                   "cost_usd": 0.0, "alerted": False})
        d["calls"] += 1
        d["input_tokens"] += getattr(usage, "input_tokens", 0) or 0
        d["output_tokens"] += getattr(usage, "output_tokens", 0) or 0
        d["cost_usd"] = round(d["cost_usd"] + cost, 6)
        total = d["cost_usd"]
        crossed = total > ALERT_USD and not d["alerted"]
        if crossed:
            d["alerted"] = True
        for old in sorted(_days)[:-KEEP_DAYS]:
            del _days[old]
        _save()
    print(f"[costi] {label or model}: {cost:.4f} $ · totale {day}: {total:.4f} $ ({d['calls']} chiamate)")
    if crossed:
        print(f"[costi] ATTENZIONE: superata la soglia di {ALERT_USD:.2f} $ il {day}: "
              f"spesi {total:.4f} $ in {d['calls']} chiamate")
    return cost


def report() -> dict:
    """Registro giornaliero, dal giorno più recente."""
    with _lock:
        days = [{"day": k, **{x: v for x, v in d.items() if x != "alerted"},
                 "over_threshold": d["cost_usd"] > ALERT_USD}
                for k, d in sorted(_days.items(), reverse=True)]
    return {"threshold_usd": ALERT_USD, "days": days}
