"""Limiti d'uso per le chiamate a Claude: per IP (oraria) e globale (giornaliera).

Contatori in memoria: si azzerano al riavvio del processo.
"""
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import HTTPException, Request

RATE_LIMIT_PER_HOUR = int(os.environ.get("RATE_LIMIT_PER_HOUR", "10"))
MAX_DAILY_AI_CALLS = int(os.environ.get("MAX_DAILY_AI_CALLS", "100"))

_hits: dict = defaultdict(deque)
_daily = {"day": None, "count": 0}


def client_ip(request: Request) -> str:
    # Render è dietro un proxy: il primo IP di X-Forwarded-For è il client reale
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request):
    """Dipendenza FastAPI: max RATE_LIMIT_PER_HOUR richieste per IP nell'ultima ora."""
    now = time.time()
    q = _hits[client_ip(request)]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= RATE_LIMIT_PER_HOUR:
        minutes = max(1, int((3600 - (now - q[0])) // 60) + 1)
        raise HTTPException(
            status_code=429,
            detail=(
                f"Hai superato il limite di {RATE_LIMIT_PER_HOUR} richieste all'ora. "
                f"Riprova tra {minutes} minuti."
            ),
        )
    q.append(now)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def try_consume_ai_call() -> bool:
    """Riserva una chiamata a Claude dal tetto giornaliero. False se il tetto è raggiunto."""
    today = _today()
    if _daily["day"] != today:
        _daily["day"], _daily["count"] = today, 0
    if _daily["count"] >= MAX_DAILY_AI_CALLS:
        print(f"[limits] Tetto giornaliero raggiunto ({MAX_DAILY_AI_CALLS}): chiamata a Claude saltata")
        return False
    _daily["count"] += 1
    return True


def ai_usage() -> dict:
    today = _today()
    used = _daily["count"] if _daily["day"] == today else 0
    return {"day": today, "used": used, "max": MAX_DAILY_AI_CALLS}
