from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import asyncio
from datetime import datetime

from scraper import DataScraper
from extractor import EntityExtractor
from graph import GraphDB
from scheduler import Scheduler

app = FastAPI(title="HEALTHINT API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

db = GraphDB()
scraper = DataScraper()
extractor = EntityExtractor()
scheduler = Scheduler(scraper, extractor, db)


@app.on_event("startup")
async def startup():
    await db.init()
    asyncio.create_task(scheduler.run())


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


@app.post("/api/refresh")
async def trigger_refresh(background_tasks: BackgroundTasks):
    background_tasks.add_task(scheduler.run_once)
    return {"status": "refresh started", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/stats")
async def get_stats():
    return await db.get_stats()


@app.get("/api/cache-info")
async def get_cache_info():
    """Return cache status: when each data source was last fetched and entry counts."""
    return scraper.get_cache_info()


@app.get("/health")
async def health():
    return {"status": "ok"}
