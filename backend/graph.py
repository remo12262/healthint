import asyncpg
import json
import os
from typing import List, Dict, Optional
from datetime import datetime

DATABASE_URL = os.environ.get("DATABASE_URL", "")


class GraphDB:
    pool: asyncpg.Pool = None

    async def init(self):
        self.pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS nodes (
                        id TEXT PRIMARY KEY,
                        label TEXT NOT NULL,
                        type TEXT NOT NULL,
                        domain TEXT DEFAULT 'health',
                        region TEXT,
                        description TEXT,
                        risk_score INTEGER DEFAULT 0,
                        created_at TEXT,
                        updated_at TEXT
                    )
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS edges (
                        id TEXT PRIMARY KEY,
                        source TEXT NOT NULL,
                        target TEXT NOT NULL,
                        type TEXT NOT NULL,
                        fact TEXT,
                        risk_score INTEGER DEFAULT 0,
                        source_doc TEXT,
                        date TEXT,
                        created_at TEXT
                    )
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS alerts (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        description TEXT,
                        severity TEXT DEFAULT 'MEDIUM',
                        entities_involved TEXT,
                        predicted_impact TEXT,
                        timeframe TEXT,
                        recommendation TEXT,
                        created_at TEXT,
                        is_read INTEGER DEFAULT 0
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity)")

                count = await conn.fetchval("SELECT COUNT(*) FROM nodes")
                if count == 0:
                    await self._seed_baseline(conn)

    async def _seed_baseline(self, conn):
        now = datetime.utcnow().isoformat()
        nodes = [
            ("aifa",        "AIFA",                   "RegulatorAgency",   "health", "IT",       "Agenzia Italiana del Farmaco. Autorizza e monitora farmaci in Italia.", 10),
            ("ema",         "EMA",                    "RegulatorAgency",   "health", "EU",        "European Medicines Agency. Autorizzazione farmaci a livello europeo.", 10),
            ("iss",         "ISS",                    "RegulatorAgency",   "health", "IT",        "Istituto Superiore di Sanità. Ricerca e sorveglianza epidemiologica.", 10),
            ("minsalute",   "Ministero della Salute", "RegulatorAgency",   "health", "IT",        "Ministero della Salute italiano. Definisce LEA e politiche sanitarie.", 10),
            ("agenas",      "AGENAS",                 "RegulatorAgency",   "health", "IT",        "Agenzia Nazionale per i Servizi Sanitari Regionali. Monitoraggio SSN.", 12),
            ("consip",      "CONSIP",                 "ProcurementBody",   "health", "IT",        "Centrale acquisti nazionale. Gestisce gare farmaci e dispositivi per SSN.", 20),
            ("regSicilia",  "Regione Sicilia",         "RegionalAuthority", "health", "Sicilia",   "Assessorato alla Salute Regione Sicilia. Gestione SSR siciliano.", 35),
            ("aospme",      "AO Papardo Messina",      "HospitalNetwork",   "health", "Sicilia",   "Azienda Ospedaliera Papardo di Messina.", 25),
            ("aouMe",       "AOU G. Martino Messina",  "HospitalNetwork",   "health", "Sicilia",   "Azienda Ospedaliera Universitaria di Messina.", 20),
            ("asp_me",      "ASP Messina",             "HospitalNetwork",   "health", "Sicilia",   "Azienda Sanitaria Provinciale di Messina.", 30),
            ("pfizer",      "Pfizer",                  "PharmaCompany",     "health", "US",        "Multinazionale farmaceutica. Vaccini, oncologia, cardiologia.", 30),
            ("roche",       "Roche",                   "PharmaCompany",     "health", "CH",        "Farmaceutica svizzera leader in oncologia e diagnostica.", 28),
            ("farmindustria","Farmindustria",           "ProcurementBody",   "health", "IT",        "Associazione industria farmaceutica italiana.", 20),
            ("humanitas",   "Humanitas",               "PrivateGroup",      "health", "Lombardia", "Gruppo ospedaliero privato. Ricerca e clinica ad alta specializzazione.", 22),
            ("gvm",         "GVM Care & Research",     "PrivateGroup",      "health", "IT",        "Gruppo privato ospedaliero italiano. Presenza in più regioni.", 28),
        ]
        edges = [
            ("e1",  "aifa",      "minsalute",  "MEMBRO_DI",     "AIFA opera sotto vigilanza del Ministero della Salute.", 8,  "2004-01"),
            ("e2",  "aifa",      "ema",        "COLLABORA_CON", "AIFA collabora con EMA per autorizzazioni centralizzate.", 10, "2004-11"),
            ("e3",  "iss",       "minsalute",  "COLLABORA_CON", "ISS fornisce supporto scientifico al Ministero della Salute.", 8, "1958-01"),
            ("e4",  "agenas",    "minsalute",  "MEMBRO_DI",     "AGENAS è agenzia tecnica del Ministero della Salute.", 10, "2003-01"),
            ("e5",  "consip",    "minsalute",  "COLLABORA_CON", "CONSIP gestisce gare nazionali farmaci per conto del MEF/Salute.", 15, "2003-01"),
            ("e6",  "regSicilia","minsalute",  "MEMBRO_DI",     "Regione Sicilia recepisce LEA e piani nazionali SSN.", 20, "2001-01"),
            ("e7",  "asp_me",    "regSicilia", "CONTROLLA",     "ASP Messina è sotto il controllo della Regione Sicilia.", 25, "2009-01"),
            ("e8",  "aospme",    "regSicilia", "CONTROLLA",     "AO Papardo dipende dall'assessorato alla salute siciliano.", 22, "2009-01"),
            ("e9",  "pfizer",    "aifa",       "REGOLA",        "AIFA monitora e autorizza i farmaci Pfizer in Italia.", 12, "2004-01"),
            ("e10", "consip",    "pfizer",     "VINCE_APPALTO", "Pfizer aggiudicataria di gare CONSIP per vaccini e antibiotici.", 30, "2023-01"),
            ("e11", "regSicilia","agenas",     "RISCHIO_PER",   "Sicilia sotto piano di rientro: monitorata da AGENAS per LEA.", 68, "2019-01"),
            ("e12", "humanitas", "aifa",       "REGOLA",        "AIFA certifica i centri Humanitas per sperimentazioni cliniche.", 15, "2010-01"),
            ("e13", "gvm",       "regSicilia", "VINCE_APPALTO", "GVM ha strutture accreditate con SSR siciliano.", 35, "2020-01"),
        ]
        await conn.executemany(
            """INSERT INTO nodes
                   (id,label,type,domain,region,description,risk_score,created_at,updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT DO NOTHING""",
            [(n[0], n[1], n[2], n[3], n[4], n[5], n[6], now, now) for n in nodes]
        )
        await conn.executemany(
            """INSERT INTO edges
                   (id,source,target,type,fact,risk_score,source_doc,date,created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT DO NOTHING""",
            [(e[0], e[1], e[2], e[3], e[4], e[5], "", e[6], now) for e in edges]
        )

    async def get_nodes(self, domain: Optional[str] = None) -> List[Dict]:
        async with self.pool.acquire() as conn:
            if domain:
                rows = await conn.fetch(
                    "SELECT * FROM nodes WHERE domain=$1 ORDER BY risk_score DESC", domain
                )
            else:
                rows = await conn.fetch("SELECT * FROM nodes ORDER BY risk_score DESC")
            return [dict(r) for r in rows]

    async def get_edges(self, domain: Optional[str] = None) -> List[Dict]:
        async with self.pool.acquire() as conn:
            if domain:
                rows = await conn.fetch("""
                    SELECT e.* FROM edges e
                    JOIN nodes n ON e.source = n.id
                    WHERE n.domain = $1
                """, domain)
            else:
                rows = await conn.fetch("SELECT * FROM edges ORDER BY risk_score DESC")
            return [dict(r) for r in rows]

    async def get_node(self, node_id: str) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM nodes WHERE id=$1", node_id)
            return dict(row) if row else None

    async def get_node_relations(self, node_id: str) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT e.*,
                    ns.label as source_label, ns.type as source_type,
                    nt.label as target_label, nt.type as target_type
                FROM edges e
                JOIN nodes ns ON e.source = ns.id
                JOIN nodes nt ON e.target = nt.id
                WHERE e.source=$1 OR e.target=$1
                ORDER BY e.risk_score DESC
            """, node_id)
            return [dict(r) for r in rows]

    async def get_alerts(self, severity: Optional[str] = None) -> List[Dict]:
        async with self.pool.acquire() as conn:
            if severity:
                rows = await conn.fetch(
                    "SELECT * FROM alerts WHERE severity=$1 ORDER BY created_at DESC", severity
                )
            else:
                rows = await conn.fetch("SELECT * FROM alerts ORDER BY created_at DESC LIMIT 50")
            return [dict(r) for r in rows]

    async def get_risk_scores(self) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, label, type, region, risk_score
                FROM nodes ORDER BY risk_score DESC LIMIT 20
            """)
            return [dict(r) for r in rows]

    async def get_stats(self) -> Dict:
        async with self.pool.acquire() as conn:
            n  = await conn.fetchval("SELECT COUNT(*) FROM nodes")
            e  = await conn.fetchval("SELECT COUNT(*) FROM edges")
            a  = await conn.fetchval("SELECT COUNT(*) FROM alerts WHERE is_read=0")
            cr = await conn.fetchval("SELECT COUNT(*) FROM nodes WHERE risk_score > 60")
            return {"nodes": n, "edges": e, "unread_alerts": a, "critical_nodes": cr}

    async def upsert_entities(self, entities: List[Dict]):
        now = datetime.utcnow().isoformat()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for e in entities:
                    await conn.execute("""
                        INSERT INTO nodes
                            (id,label,type,domain,region,description,risk_score,created_at,updated_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                        ON CONFLICT(id) DO UPDATE SET
                            risk_score = GREATEST(nodes.risk_score, EXCLUDED.risk_score),
                            updated_at = EXCLUDED.updated_at
                    """, e.get("id"), e.get("label"), e.get("type", "HospitalNetwork"),
                         "health", e.get("region"), e.get("description"),
                         e.get("risk_score", 0), now, now)

    async def upsert_relations(self, relations: List[Dict]):
        now = datetime.utcnow().isoformat()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for r in relations:
                    rid = f"{r.get('source')}_{r.get('target')}_{r.get('type')}"
                    await conn.execute("""
                        INSERT INTO edges
                            (id,source,target,type,fact,risk_score,source_doc,date,created_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                        ON CONFLICT(id) DO UPDATE SET
                            risk_score = GREATEST(edges.risk_score, EXCLUDED.risk_score)
                    """, rid, r.get("source"), r.get("target"), r.get("type", "COLLABORA_CON"),
                         r.get("fact"), r.get("risk_score", 0),
                         r.get("source_doc", ""), r.get("date"), now)

    async def upsert_alerts(self, alerts: List[Dict]):
        now = datetime.utcnow().isoformat()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for a in alerts:
                    await conn.execute("""
                        INSERT INTO alerts
                            (id,title,description,severity,entities_involved,predicted_impact,
                             timeframe,recommendation,created_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                        ON CONFLICT(id) DO UPDATE SET
                            description = EXCLUDED.description,
                            severity    = EXCLUDED.severity,
                            created_at  = EXCLUDED.created_at
                    """, a.get("id", f"alert_{now}"), a.get("title"), a.get("description"),
                         a.get("severity", "MEDIUM"),
                         json.dumps(a.get("entities_involved", [])),
                         a.get("predicted_impact"), a.get("timeframe"),
                         a.get("recommendation"), now)
