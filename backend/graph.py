import copy
import json
import os
from typing import List, Dict, Optional
from datetime import datetime

SEED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "seed.json")
SEED_VERSION = 1


class GraphDB:
    def __init__(self):
        self.nodes: Dict[str, Dict] = {}
        self.edges: Dict[str, Dict] = {}
        self.alerts: Dict[str, Dict] = {}
        self.updated_at: Optional[str] = None
        # Esito dell'ultimo aggiornamento riuscito (errori fonti/alert), salvato nel seed
        self.refresh_info: Dict = {}

    async def init(self):
        if not self.nodes:
            if not self._load_seed():
                self._seed_baseline()

    def _load_seed(self) -> bool:
        """Carica l'istantanea data/seed.json. False se manca o non è valida."""
        try:
            with open(SEED_FILE, encoding="utf-8") as f:
                seed = json.load(f)
            nodes, edges = seed.get("nodes", []), seed.get("edges", [])
            if not nodes:
                return False
            self.nodes = {n["id"]: n for n in nodes}
            self.edges = {e["id"]: e for e in edges}
            self.alerts = {a["id"]: a for a in seed.get("alerts", [])}
            self.updated_at = seed.get("data_updated_at") or seed.get("exported_at")
            self.refresh_info = seed.get("refresh_info") or {}
            print(f"[graph] Seed caricato: {len(self.nodes)} nodi, {len(self.edges)} relazioni, {len(self.alerts)} alert")
            return True
        except FileNotFoundError:
            print(f"[graph] Seed non trovato ({SEED_FILE}): uso la baseline")
        except Exception as e:
            print(f"[graph] Seed non valido: {e}: uso la baseline")
        return False

    def export(self) -> Dict:
        """Istantanea completa nello stesso formato di data/seed.json."""
        return {
            "version": SEED_VERSION,
            "exported_at": datetime.utcnow().isoformat(),
            "data_updated_at": self.updated_at,
            "refresh_info": self.refresh_info,
            "nodes": list(self.nodes.values()),
            "edges": list(self.edges.values()),
            "alerts": list(self.alerts.values()),
        }

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

    # --- Protezione dell'aggiornamento: istantanea, verifica, ripristino

    def snapshot(self) -> Dict:
        return copy.deepcopy({"nodes": self.nodes, "edges": self.edges, "alerts": self.alerts,
                              "updated_at": self.updated_at, "refresh_info": self.refresh_info})

    def restore(self, snap: Dict):
        self.nodes, self.edges, self.alerts = snap["nodes"], snap["edges"], snap["alerts"]
        self.updated_at, self.refresh_info = snap["updated_at"], snap["refresh_info"]

    def drop_legacy_recall_edges(self) -> int:
        """Relazioni di richiamo del vecchio formato (una per azienda): sostituite da una per richiamo."""
        legacy = [k for k, e in self.edges.items()
                  if e.get("type") == "RISCHIO_PER" and not k.startswith("recall_")
                  and str(e.get("fact", "")).startswith("[Class")]
        for k in legacy:
            del self.edges[k]
        return len(legacy)

    def drop_orphan_edges(self) -> int:
        """Elimina le relazioni che puntano a nodi inesistenti; restituisce quante."""
        orphans = [k for k, e in self.edges.items()
                   if e.get("source") not in self.nodes or e.get("target") not in self.nodes]
        for k in orphans:
            del self.edges[k]
        return len(orphans)

    def validate(self, previous_nodes: int) -> List[str]:
        """Problemi che rendono il grafo inutilizzabile dal frontend (lista vuota = valido)."""
        problems = []
        if not self.nodes:
            problems.append("il grafo non contiene nodi")
        if previous_nodes and len(self.nodes) < previous_nodes // 2:
            problems.append(f"i nodi sono scesi da {previous_nodes} a {len(self.nodes)}")
        for nid, n in self.nodes.items():
            if not nid or n.get("id") != nid or not n.get("label") or not n.get("type"):
                problems.append(f"nodo {nid!r} senza id, etichetta o tipo")
            elif not isinstance(n.get("risk_score"), (int, float)) or not 0 <= n["risk_score"] <= 100:
                problems.append(f"nodo {nid!r} con risk_score non valido: {n.get('risk_score')!r}")
            if len(problems) >= 5:
                break
        for k, e in self.edges.items():
            if e.get("source") not in self.nodes or e.get("target") not in self.nodes:
                problems.append(f"relazione {k!r} verso nodi inesistenti")
                break
        return problems

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
            "updated_at": self.updated_at,
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
            rid = r.get("id") or f"{r.get('source')}_{r.get('target')}_{r.get('type')}"
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

    async def replace_alerts(self, alerts: List[Dict]):
        """Gli alert sono una previsione sul grafo attuale: ogni generazione sostituisce la precedente."""
        self.alerts = {}
        await self.upsert_alerts(alerts)

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
