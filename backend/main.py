from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import hmac
import os
import time
from datetime import datetime

from scraper import DataScraper, SOURCES
from extractor import EntityExtractor
from graph import GraphDB
from scheduler import Scheduler
from limits import rate_limit, ai_usage
import costs

app = FastAPI(title="HEALTHINT API", version="1.0.0")

ALLOWED_ORIGINS = [
    "https://healthint-frontend.onrender.com",
    "https://healthint.healthhorizon.it",
    "https://healthhorizon.it",
    "https://www.healthhorizon.it",
    "http://localhost:5173",
] + [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

db = GraphDB()
scraper = DataScraper()
extractor = EntityExtractor()
scheduler = Scheduler(scraper, extractor, db)

# Pulsante "Aggiorna dati": al massimo un aggiornamento manuale ogni MANUAL_REFRESH_SECONDS
# (globale, non per utente) per contenere i costi dell'API Anthropic
MANUAL_REFRESH_SECONDS = int(os.environ.get("MANUAL_REFRESH_SECONDS", "3600"))
_last_manual_refresh = 0.0


@app.on_event("startup")
async def startup():
    # Solo caricamento dati (seed.json): nessuna chiamata a Claude all'avvio
    await db.init()


@app.get("/api/graph")
async def get_graph(domain: Optional[str] = None):
    nodes = await db.get_nodes(domain)
    edges = await db.get_edges(domain)
    return {"nodes": nodes, "edges": edges}


@app.get("/api/node/{node_id}")
async def get_node(node_id: str):
    node = await db.get_node(node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    relations = await db.get_node_relations(node_id)
    return {"node": node, "relations": relations}


@app.get("/api/alerts")
async def get_alerts(severity: Optional[str] = None):
    return await db.get_alerts(severity)


@app.get("/api/risk-scores")
async def get_risk_scores():
    return await db.get_risk_scores()


@app.post("/api/refresh", dependencies=[Depends(rate_limit)])
async def trigger_refresh(
    background_tasks: BackgroundTasks,
    wait: bool = False,
    x_refresh_key: Optional[str] = Header(default=None),
):
    """Aggiornamento programmato (GitHub Actions). Con wait=true risponde a lavoro finito."""
    expected = os.environ.get("REFRESH_KEY", "")
    if not expected:
        raise HTTPException(403, "Aggiornamento disattivato: REFRESH_KEY non configurata sul server.")
    if not x_refresh_key or not hmac.compare_digest(x_refresh_key, expected):
        raise HTTPException(401, "Chiave di aggiornamento non valida.")
    if scheduler.running:
        raise HTTPException(409, "Aggiornamento già in corso.")
    if not wait:
        background_tasks.add_task(scheduler.run_once)
        return {"status": "refresh started", "timestamp": datetime.utcnow().isoformat()}
    ok = await scheduler.run_once()
    if not ok:
        raise HTTPException(500, f"Aggiornamento non riuscito: {scheduler.last_error}")
    return scheduler.status()


@app.post("/api/refresh/manual", status_code=202, dependencies=[Depends(rate_limit)])
async def manual_refresh(background_tasks: BackgroundTasks):
    """Pulsante "Aggiorna dati": pubblico, al massimo uno ogni MANUAL_REFRESH_SECONDS."""
    global _last_manual_refresh
    if scheduler.running:
        raise HTTPException(409, "Un aggiornamento è già in corso: attendi qualche minuto.")
    wait_s = _last_manual_refresh + MANUAL_REFRESH_SECONDS - time.time()
    if wait_s > 0:
        minutes = int(wait_s // 60) + 1
        raise HTTPException(
            429,
            f"I dati sono già stati aggiornati da poco. Per contenere i costi è possibile "
            f"un aggiornamento manuale all'ora: riprova tra {minutes} minuti.",
        )
    _last_manual_refresh = time.time()
    background_tasks.add_task(scheduler.run_once)
    return {"status": "refresh started"}


@app.get("/api/status")
async def get_status():
    """Data dell'ultimo aggiornamento riuscito, fonti ed eventuali errori."""
    next_manual = max(0, int(_last_manual_refresh + MANUAL_REFRESH_SECONDS - time.time()))
    return {**scheduler.status(), "sources": SOURCES, "manual_available_in_s": next_manual}


@app.get("/api/export")
async def export_data():
    """Dati attuali nello stesso formato di data/seed.json."""
    return db.export()


@app.get("/api/stats")
async def get_stats():
    return await db.get_stats()


@app.get("/api/cache-info")
async def get_cache_info():
    """Return cache status: when each data source was last fetched and entry counts."""
    return scraper.get_cache_info()


@app.get("/api/ai-costs")
async def get_ai_costs():
    """Registro dei costi giornalieri delle chiamate a Claude."""
    return costs.report()


@app.get("/health")
async def health():
    return {"status": "ok", "ai_calls_today": ai_usage()}
