import aiosqlite
import json
import os
from typing import List, Dict, Optional
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "healthint.db")


class GraphDB:

    async def init(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.executescript("""
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
                );
                CREATE TABLE IF NOT EXISTS edges (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    type TEXT NOT NULL,
                    fact TEXT,
                    risk_score INTEGER DEFAULT 0,
                    source_doc TEXT,
                    date TEXT,
                    created_at TEXT,
                    FOREIGN KEY(source) REFERENCES nodes(id),
                    FOREIGN KEY(target) REFERENCES nodes(id)
                );
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
                );
                CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
                CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
                CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
                CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
            """)
            await db.commit()
            cursor = await db.execute("SELECT COUNT(*) FROM nodes")
            count = (await cursor.fetchone())[0]
            if count == 0:
                await self._seed_baseline(db)

    async def _seed_baseline(self, db):
        """Seed with baseline entities in the Italian health system."""
        now = datetime.utcnow().isoformat()
        nodes = [
            ("aifa",       "AIFA",                   "RegulatorAgency",  "health", "IT",          "Agenzia Italiana del Farmaco. Autorizza e monitora farmaci in Italia.", 10),
            ("ema",        "EMA",                    "RegulatorAgency",  "health", "EU",           "European Medicines Agency. Autorizzazione farmaci a livello europeo.", 10),
            ("iss",        "ISS",                    "RegulatorAgency",  "health", "IT",           "Istituto Superiore di Sanità. Ricerca e sorveglianza epidemiologica.", 10),
            ("minsalute",  "Ministero della Salute", "RegulatorAgency",  "health", "IT",           "Ministero della Salute italiano. Definisce LEA e politiche sanitarie.", 10),
            ("agenas",     "AGENAS",                 "RegulatorAgency",  "health", "IT",           "Agenzia Nazionale per i Servizi Sanitari Regionali. Monitoraggio SSN.", 12),
            ("consip",     "CONSIP",                 "ProcurementBody",  "health", "IT",           "Centrale acquisti nazionale. Gestisce gare farmaci e dispositivi per SSN.", 20),
            ("regSicilia", "Regione Sicilia",         "RegionalAuthority","health", "Sicilia",      "Assessorato alla Salute Regione Sicilia. Gestione SSR siciliano.", 35),
            ("aospme",     "AO Papardo Messina",      "HospitalNetwork",  "health", "Sicilia",      "Azienda Ospedaliera Papardo di Messina.", 25),
            ("aouMe",      "AOU G. Martino Messina",  "HospitalNetwork",  "health", "Sicilia",      "Azienda Ospedaliera Universitaria di Messina.", 20),
            ("asp_me",     "ASP Messina",             "HospitalNetwork",  "health", "Sicilia",      "Azienda Sanitaria Provinciale di Messina.", 30),
            ("pfizer",     "Pfizer",                  "PharmaCompany",    "health", "US",           "Multinazionale farmaceutica. Vaccini, oncologia, cardiologia.", 30),
            ("roche",      "Roche",                   "PharmaCompany",    "health", "CH",           "Farmaceutica svizzera leader in oncologia e diagnostica.", 28),
            ("farmindustria","Farmindustria",          "ProcurementBody",  "health", "IT",           "Associazione industria farmaceutica italiana.", 20),
            ("humanitas",  "Humanitas",               "PrivateGroup",     "health", "Lombardia",    "Gruppo ospedaliero privato. Ricerca e clinica ad alta specializzazione.", 22),
            ("gvm",        "GVM Care & Research",     "PrivateGroup",     "health", "IT",           "Gruppo privato ospedaliero italiano. Presenza in più regioni.", 28),
        ]
        edges = [
            ("e1",  "aifa",      "minsalute",  "MEMBRO_DI",      "AIFA opera sotto vigilanza del Ministero della Salute.", 8,  "2004-01"),
            ("e2",  "aifa",      "ema",        "COLLABORA_CON",  "AIFA collabora con EMA per autorizzazioni centralizzate.", 10, "2004-11"),
            ("e3",  "iss",       "minsalute",  "COLLABORA_CON",  "ISS fornisce supporto scientifico al Ministero della Salute.", 8,  "1958-01"),
            ("e4",  "agenas",    "minsalute",  "MEMBRO_DI",      "AGENAS è agenzia tecnica del Ministero della Salute.", 10, "2003-01"),
            ("e5",  "consip",    "minsalute",  "COLLABORA_CON",  "CONSIP gestisce gare nazionali farmaci per conto del MEF/Salute.", 15, "2003-01"),
            ("e6",  "regSicilia","minsalute",  "MEMBRO_DI",      "Regione Sicilia recepisce LEA e piani nazionali SSN.", 20, "2001-01"),
            ("e7",  "asp_me",    "regSicilia", "CONTROLLA",      "ASP Messina è sotto il controllo della Regione Sicilia.", 25, "2009-01"),
            ("e8",  "aospme",    "regSicilia", "CONTROLLA",      "AO Papardo dipende dall'assessorato alla salute siciliano.", 22, "2009-01"),
            ("e9",  "pfizer",    "aifa",       "REGOLA",         "AIFA monitora e autorizza i farmaci Pfizer in Italia.", 12, "2004-01"),
            ("e10", "consip",    "pfizer",     "VINCE_APPALTO",  "Pfizer aggiudicataria di gare CONSIP per vaccini e antibiotici.", 30, "2023-01"),
            ("e11", "regSicilia","agenas",     "RISCHIO_PER",    "Sicilia sotto piano di rientro: monitorata da AGENAS per LEA.", 68, "2019-01"),
            ("e12", "humanitas", "aifa",       "REGOLA",         "AIFA certifica i centri Humanitas per sperimentazioni cliniche.", 15, "2010-01"),
            ("e13", "gvm",       "regSicilia", "VINCE_APPALTO",  "GVM ha strutture accreditate con SSR siciliano.", 35, "2020-01"),
        ]
        await db.executemany(
            "INSERT OR IGNORE INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
            [(n[0], n[1], n[2], n[3], n[4], n[5], n[6], now, now) for n in nodes]
        )
        await db.executemany(
            "INSERT OR IGNORE INTO edges VALUES (?,?,?,?,?,?,?,?,?)",
            [(e[0], e[1], e[2], e[3], e[4], e[5], "", e[6], now) for e in edges]
        )
        await db.commit()

    async def get_nodes(self, domain: Optional[str] = None) -> List[Dict]:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            if domain:
                cursor = await db.execute("SELECT * FROM nodes WHERE domain=? ORDER BY risk_score DESC", (domain,))
            else:
                cursor = await db.execute("SELECT * FROM nodes ORDER BY risk_score DESC")
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_edges(self, domain: Optional[str] = None) -> List[Dict]:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            if domain:
                cursor = await db.execute("""
                    SELECT e.* FROM edges e
                    JOIN nodes n ON e.source = n.id
                    WHERE n.domain = ?
                """, (domain,))
            else:
                cursor = await db.execute("SELECT * FROM edges ORDER BY risk_score DESC")
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_node(self, node_id: str) -> Optional[Dict]:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM nodes WHERE id=?", (node_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_node_relations(self, node_id: str) -> List[Dict]:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT e.*,
                    ns.label as source_label, ns.type as source_type,
                    nt.label as target_label, nt.type as target_type
                FROM edges e
                JOIN nodes ns ON e.source = ns.id
                JOIN nodes nt ON e.target = nt.id
                WHERE e.source=? OR e.target=?
                ORDER BY e.risk_score DESC
            """, (node_id, node_id))
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_alerts(self, severity: Optional[str] = None) -> List[Dict]:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            if severity:
                cursor = await db.execute("SELECT * FROM alerts WHERE severity=? ORDER BY created_at DESC", (severity,))
            else:
                cursor = await db.execute("SELECT * FROM alerts ORDER BY created_at DESC LIMIT 50")
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_risk_scores(self) -> List[Dict]:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT id, label, type, region, risk_score
                FROM nodes ORDER BY risk_score DESC LIMIT 20
            """)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_stats(self) -> Dict:
        async with aiosqlite.connect(DB_PATH) as db:
            n = (await (await db.execute("SELECT COUNT(*) FROM nodes")).fetchone())[0]
            e = (await (await db.execute("SELECT COUNT(*) FROM edges")).fetchone())[0]
            a = (await (await db.execute("SELECT COUNT(*) FROM alerts WHERE is_read=0")).fetchone())[0]
            cr = (await (await db.execute("SELECT COUNT(*) FROM nodes WHERE risk_score > 60")).fetchone())[0]
            return {"nodes": n, "edges": e, "unread_alerts": a, "critical_nodes": cr}

    async def upsert_entities(self, entities: List[Dict]):
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            for e in entities:
                await db.execute("""
                    INSERT INTO nodes (id, label, type, domain, region, description, risk_score, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        risk_score = MAX(risk_score, excluded.risk_score),
                        updated_at = excluded.updated_at
                """, (
                    e.get("id"), e.get("label"), e.get("type", "HospitalNetwork"),
                    "health", e.get("region"), e.get("description"),
                    e.get("risk_score", 0), now, now
                ))
            await db.commit()

    async def upsert_relations(self, relations: List[Dict]):
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            for r in relations:
                rid = f"{r.get('source')}_{r.get('target')}_{r.get('type')}"
                await db.execute("""
                    INSERT INTO edges (id, source, target, type, fact, risk_score, source_doc, date, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        risk_score = MAX(risk_score, excluded.risk_score)
                """, (
                    rid, r.get("source"), r.get("target"), r.get("type", "COLLABORA_CON"),
                    r.get("fact"), r.get("risk_score", 0),
                    r.get("source_doc", ""), r.get("date"), now
                ))
            await db.commit()

    async def upsert_alerts(self, alerts: List[Dict]):
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            for a in alerts:
                await db.execute("""
                    INSERT OR REPLACE INTO alerts
                    (id, title, description, severity, entities_involved, predicted_impact, timeframe, recommendation, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (
                    a.get("id", f"alert_{now}"), a.get("title"), a.get("description"),
                    a.get("severity", "MEDIUM"),
                    json.dumps(a.get("entities_involved", [])),
                    a.get("predicted_impact"), a.get("timeframe"),
                    a.get("recommendation"), now
                ))
            await db.commit()
