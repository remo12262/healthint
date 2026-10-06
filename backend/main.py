from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import hmac
import os
from datetime import datetime

from scraper import DataScraper
from extractor import EntityExtractor
from graph import GraphDB
from scheduler import Scheduler
from limits import rate_limit, ai_usage

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
    x_refresh_key: Optional[str] = Header(default=None),
):
    expected = os.environ.get("REFRESH_KEY", "")
    if not expected:
        raise HTTPException(403, "Aggiornamento disattivato: REFRESH_KEY non configurata sul server.")
    if not x_refresh_key or not hmac.compare_digest(x_refresh_key, expected):
        raise HTTPException(401, "Chiave di aggiornamento non valida.")
    if scheduler.running:
        return {"status": "refresh già in corso", "timestamp": datetime.utcnow().isoformat()}
    background_tasks.add_task(scheduler.run_once)
    return {"status": "refresh started", "timestamp": datetime.utcnow().isoformat()}


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


@app.get("/health")
async def health():
    return {"status": "ok", "ai_calls_today": ai_usage()}
