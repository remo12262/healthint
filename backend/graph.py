import json
from typing import List, Dict, Optional
from datetime import datetime


class GraphDB:
    def __init__(self):
        self.nodes: Dict[str, Dict] = {}
        self.edges: Dict[str, Dict] = {}
        self.alerts: Dict[str, Dict] = {}

    async def init(self):
        if not self.nodes:
            self._seed_baseline()

    def _seed_baseline(self):
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
        for n in nodes:
            self.nodes[n[0]] = {
                "id": n[0], "label": n[1], "type": n[2], "domain": n[3],
                "region": n[4], "description": n[5], "risk_score": n[6],
                "created_at": now, "updated_at": now,
            }
        for e in edges:
            self.edges[e[0]] = {
                "id": e[0], "source": e[1], "target": e[2], "type": e[3],
                "fact": e[4], "risk_score": e[5], "source_doc": "",
                "date": e[6], "created_at": now,
            }

    async def get_nodes(self, domain: Optional[str] = None) -> List[Dict]:
        nodes = list(self.nodes.values())
        if domain:
            nodes = [n for n in nodes if n.get("domain") == domain]
        return sorted(nodes, key=lambda n: n.get("risk_score", 0), reverse=True)

    async def get_edges(self, domain: Optional[str] = None) -> List[Dict]:
        edges = list(self.edges.values())
        if domain:
            edges = [e for e in edges if self.nodes.get(e["source"], {}).get("domain") == domain]
        return sorted(edges, key=lambda e: e.get("risk_score", 0), reverse=True)

    async def get_node(self, node_id: str) -> Optional[Dict]:
        return self.nodes.get(node_id)

    async def get_node_relations(self, node_id: str) -> List[Dict]:
        results = []
        for e in self.edges.values():
            if e["source"] == node_id or e["target"] == node_id:
                src = self.nodes.get(e["source"], {})
                tgt = self.nodes.get(e["target"], {})
                results.append({
                    **e,
                    "source_label": src.get("label", ""),
                    "source_type":  src.get("type", ""),
                    "target_label": tgt.get("label", ""),
                    "target_type":  tgt.get("type", ""),
                })
        return sorted(results, key=lambda e: e.get("risk_score", 0), reverse=True)

    async def get_alerts(self, severity: Optional[str] = None) -> List[Dict]:
        alerts = list(self.alerts.values())
        if severity:
            alerts = [a for a in alerts if a.get("severity") == severity]
        return sorted(alerts, key=lambda a: a.get("created_at", ""), reverse=True)[:50]

    async def get_risk_scores(self) -> List[Dict]:
        nodes = sorted(self.nodes.values(), key=lambda n: n.get("risk_score", 0), reverse=True)
        return [
            {"id": n["id"], "label": n["label"], "type": n["type"],
             "region": n.get("region"), "risk_score": n.get("risk_score", 0)}
            for n in nodes[:20]
        ]

    async def get_stats(self) -> Dict:
        unread = sum(1 for a in self.alerts.values() if not a.get("is_read"))
        critical = sum(1 for n in self.nodes.values() if n.get("risk_score", 0) > 60)
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "unread_alerts": unread,
            "critical_nodes": critical,
        }

    async def upsert_entities(self, entities: List[Dict]):
        now = datetime.utcnow().isoformat()
        for e in entities:
            eid = e.get("id")
            if not eid:
                continue
            if eid in self.nodes:
                self.nodes[eid]["risk_score"] = max(
                    self.nodes[eid].get("risk_score", 0), e.get("risk_score", 0)
                )
                self.nodes[eid]["updated_at"] = now
            else:
                self.nodes[eid] = {
                    "id": eid, "label": e.get("label", ""),
                    "type": e.get("type", "HospitalNetwork"), "domain": "health",
                    "region": e.get("region"), "description": e.get("description", ""),
                    "risk_score": e.get("risk_score", 0),
                    "created_at": now, "updated_at": now,
                }

    async def upsert_relations(self, relations: List[Dict]):
        now = datetime.utcnow().isoformat()
        for r in relations:
            rid = f"{r.get('source')}_{r.get('target')}_{r.get('type')}"
            if rid in self.edges:
                self.edges[rid]["risk_score"] = max(
                    self.edges[rid].get("risk_score", 0), r.get("risk_score", 0)
                )
            else:
                self.edges[rid] = {
                    "id": rid, "source": r.get("source"), "target": r.get("target"),
                    "type": r.get("type", "COLLABORA_CON"), "fact": r.get("fact"),
                    "risk_score": r.get("risk_score", 0),
                    "source_doc": r.get("source_doc", ""), "date": r.get("date"),
                    "created_at": now,
                }

    async def upsert_alerts(self, alerts: List[Dict]):
        now = datetime.utcnow().isoformat()
        for a in alerts:
            aid = a.get("id", f"alert_{now}")
            self.alerts[aid] = {
                "id": aid, "title": a.get("title"), "description": a.get("description"),
                "severity": a.get("severity", "MEDIUM"),
                "entities_involved": json.dumps(a.get("entities_involved", [])),
                "predicted_impact": a.get("predicted_impact"),
                "timeframe": a.get("timeframe"), "recommendation": a.get("recommendation"),
                "created_at": now, "is_read": False,
            }
