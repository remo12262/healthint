import copy
import re
import json
import os
from typing import List, Dict, Optional
from datetime import datetime

import italy
import normalize

SEED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "seed.json")
SEED_VERSION = 1
CLASS_RISK = {"I": 85, "II": 55, "III": 25}
NUCLEUS_BASIS = "Ente del nucleo fisso italiano: rischio non stimato"
# Documenti delle fonti ricordati come già analizzati (i più recenti)
MAX_PROCESSED_DOCS = 1000


class GraphDB:
    def __init__(self):
        self.nodes: Dict[str, Dict] = {}
        self.edges: Dict[str, Dict] = {}
        self.alerts: Dict[str, Dict] = {}
        self.updated_at: Optional[str] = None
        # Esito dell'ultimo aggiornamento riuscito (errori fonti/alert), salvato nel seed
        self.refresh_info: Dict = {}
        # Segnalazioni dalle fonti (ultimi focolai OMS, richiami FDA recenti), senza AI
        self.signals: Dict = {}
        # Documenti già passati a Claude: non si rianalizzano a ogni aggiornamento
        self.processed_docs: List[str] = []

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
            self.signals = seed.get("signals") or {}
            self.processed_docs = seed.get("processed_docs") or sorted(
                {d for e in self.edges.values() for d in self._edge_docs(e) if not str(e.get("id", "")).startswith("recall_")})
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
            "signals": self.signals,
            "processed_docs": self.processed_docs,
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
            ("e6",   "minsalute", "regSicilia", "REGOLA",        "La Regione Sicilia recepisce i LEA e i piani nazionali definiti dal Ministero della Salute.", 20, "2001-01"),
            ("e7",  "regSicilia","asp_me",     "CONTROLLA",     "La Regione Sicilia controlla l'ASP di Messina.", 25, "2009-01"),
            ("e8",  "regSicilia","aospme",     "CONTROLLA",     "L'AO Papardo di Messina dipende dall'assessorato alla salute siciliano.", 22, "2009-01"),
            ("e9",  "pfizer",    "aifa",       "REGOLA",        "AIFA monitora e autorizza i farmaci Pfizer in Italia.", 12, "2004-01"),
            ("e10", "consip",    "pfizer",     "VINCE_APPALTO", "Pfizer aggiudicataria di gare CONSIP per vaccini e antibiotici.", 30, "2023-01"),
            ("e11",  "agenas",    "regSicilia", "CONTROLLA",     "La Sicilia è in piano di rientro dal disavanzo sanitario: AGENAS monitora l'erogazione dei LEA.", 68, None),
            ("e12", "humanitas", "aifa",       "REGOLA",        "AIFA certifica i centri Humanitas per sperimentazioni cliniche.", 15, "2010-01"),
            ("e13", "regSicilia","gvm",        "ACCREDITA",     "GVM ha strutture accreditate con il servizio sanitario regionale siciliano.", 35, "2020-01"),
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
                              "updated_at": self.updated_at, "refresh_info": self.refresh_info,
                              "signals": self.signals, "processed_docs": self.processed_docs})

    def restore(self, snap: Dict):
        self.nodes, self.edges, self.alerts = snap["nodes"], snap["edges"], snap["alerts"]
        self.updated_at, self.refresh_info = snap["updated_at"], snap["refresh_info"]
        self.signals = snap.get("signals", {})
        self.processed_docs = snap.get("processed_docs", [])

    def mark_processed(self, docs: List[str]):
        self.processed_docs = (self.processed_docs + [d for d in docs if d and d not in self.processed_docs])[-MAX_PROCESSED_DOCS:]

    def ensure_nucleus(self) -> int:
        """Nucleo fisso italiano sempre presente (italy.py); restituisce i nodi aggiunti.

        Da chiamare dopo merge_duplicates: i vecchi nodi (es. "Regione Sicilia") sono già
        confluiti nell'id del nucleo e qui ricevono sito, nome completo e fonti.
        """
        now = datetime.utcnow().isoformat()
        nodes, edges = italy.nucleus()
        for k in italy.SUPERSEDED_EDGES:
            self.edges.pop(k, None)
        added = 0
        for n in nodes:
            cur = self.nodes.get(n["id"])
            if cur is None:
                self.nodes[n["id"]] = {**n, "domain": "health", "description": n["full_name"], "risk_score": 10,
                                       "risk_basis": NUCLEUS_BASIS, "italy": True, "created_at": now, "updated_at": now}
                added += 1
                continue
            if cur.get("label") != n["label"]:
                cur["aliases"] = sorted((set(cur.get("aliases", [])) | {cur["label"]}) - {n["label"]})
                cur["label"] = n["label"]
            cur.update({k: n[k] for k in ("full_name", "type", "region", "website")}, italy=True)
            if not cur.get("description"):
                cur["description"] = n["full_name"]
            if not cur.get("risk_basis"):
                cur["risk_basis"] = NUCLEUS_BASIS
        for e in edges:
            if e["id"] in self.edges:
                self._absorb_edge(self.edges[e["id"]], e)
                self.edges[e["id"]]["fact"] = e["fact"]
            else:
                self.edges[e["id"]] = {**e, "created_at": now}
        return added

    def drop_legacy_recall_edges(self) -> int:
        """Relazioni di richiamo del vecchio formato (una per azienda): sostituite da una per richiamo."""
        legacy = [k for k, e in self.edges.items()
                  if e.get("type") == "RISCHIO_PER" and not k.startswith("recall_")
                  and str(e.get("fact", "")).startswith("[Class")]
        for k in legacy:
            del self.edges[k]
        return len(legacy)

    def recompute_recall_risk(self, today: Optional[datetime] = None) -> int:
        """Rischio delle aziende con richiami FDA: gravità della classe x recenza del richiamo.

        Ricalcolato a ogni aggiornamento (non solo in aumento): un richiamo vecchio pesa meno.
        Classe I 85, II 55, III 25; peso 100% entro 90 giorni, 75% entro un anno, 50% oltre.
        """
        today = today or datetime.utcnow()
        best: Dict[str, tuple] = {}
        for k, e in self.edges.items():
            if not k.startswith("recall_"):
                continue
            m = re.match(r"\[Class (I{1,3})\]", str(e.get("fact", "")))
            if not m:
                continue
            cls = m.group(1)
            try:
                when = datetime.strptime(e.get("date") or "", "%Y-%m-%d")
                age = (today - when).days
                factor = 1.0 if age <= 90 else 0.75 if age <= 365 else 0.5
                day = when.strftime("%d/%m/%Y")
            except ValueError:
                factor, day = 0.5, "data non indicata"
            score = round(CLASS_RISK[cls] * factor)
            basis = f"Richiamo FDA {e.get('source_doc') or k[7:]} di classe {cls} del {day}"
            if e["source"] not in best or score > best[e["source"]][0]:
                best[e["source"]] = (score, basis)
        for nid, (score, basis) in best.items():
            if nid in self.nodes:
                self.nodes[nid]["risk_score"] = score
                self.nodes[nid]["risk_basis"] = basis
        for n in self.nodes.values():
            n.setdefault("risk_basis", "Valore assegnato manualmente")
        return len(best)

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

    def _italy_flags(self) -> Dict[str, tuple]:
        """Per ogni nodo: (ente italiano, legato all'Italia da un richiamo FDA distribuito in Italia)."""
        recalls_it = {e["source"] for k, e in self.edges.items() if k.startswith("recall_") and e.get("target") == "aifa"}
        flags = {}
        for nid, n in self.nodes.items():
            it = italy.is_italian(n) or normalize.find_country(n.get("region") or "") == "it"
            flags[nid] = (it, nid in recalls_it)
        return flags

    async def get_nodes(self, domain: Optional[str] = None) -> List[Dict]:
        flags = self._italy_flags()
        nodes = [{**n, "italy": flags[n["id"]][0], "italy_related": flags[n["id"]][1]} for n in self.nodes.values()]
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
        """Classifica come nella scheda Risk Score: solo punteggi dalla formula FDA o stimati dall'AI
        (mai valori assegnati a mano o di origine sconosciuta), senza enti regolatori e di risposta."""
        ranked = [n for n in self.nodes.values() if n.get("type") != "RegulatorAgency"
                  and str(n.get("risk_basis") or "").startswith(("Richiamo FDA", "Stima dell'AI"))]
        nodes = sorted(ranked, key=lambda n: n.get("risk_score", 0), reverse=True)
        return [
            {"id": n["id"], "label": n["label"], "type": n["type"],
             "region": n.get("region"), "risk_score": n.get("risk_score", 0),
             "risk_basis": n.get("risk_basis")}
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

    # --- Nodi e relazioni: inserimento con normalizzazione dei nomi (senza AI)

    def _events(self) -> Dict[str, str]:
        """Eventi epidemici già presenti: id -> malattia."""
        return {nid: n["disease"] for nid, n in self.nodes.items() if n.get("disease")}

    def _resolve(self, label: str, etype: str = "", region: Optional[str] = None, events=None) -> Dict:
        return normalize.resolve(label, etype, region, self._events() if events is None else events)

    def _canonical_id(self, e: Dict, key_index: Dict[str, str]) -> tuple:
        """Id canonico di un'entità in arrivo e risultato della normalizzazione."""
        r = self._resolve(e.get("label") or e.get("id", ""), e.get("type", ""), e.get("region"))
        if not r["key"].startswith("name:"):
            return r["id"], r
        if r["key"] in key_index:
            return key_index[r["key"]], r
        cid = e.get("id") or r["id"]
        # Id già usato da un'entità diversa (l'AI riusa slug generici): se ne crea uno nuovo
        if cid in self.nodes:
            cid = r["id"]
            base, i = cid, 2
            while cid in self.nodes:
                cid, i = f"{base}_{i}", i + 1
        return cid, r

    def _key_index(self) -> Dict[str, str]:
        return {self._resolve(n.get("label", ""), n.get("type", ""), n.get("region"))["key"]: nid
                for nid, n in self.nodes.items()}

    @staticmethod
    def _absorb(node: Dict, other: Dict):
        """Unisce in node le informazioni di other (stessa entità con un altro nome)."""
        aliases = set(node.get("aliases", [])) | set(other.get("aliases", []))
        if other.get("label"):
            aliases.add(other["label"])
        aliases.discard(node.get("label"))
        if aliases:
            node["aliases"] = sorted(aliases)
        if other.get("risk_score", 0) > node.get("risk_score", 0):
            node["risk_score"] = other["risk_score"]
            if other.get("risk_basis"):
                node["risk_basis"] = other["risk_basis"]
        if not node.get("risk_basis") and other.get("risk_basis"):
            node["risk_basis"] = other["risk_basis"]
        if not node.get("region") and other.get("region"):
            node["region"] = other["region"]
        # La descrizione scritta a mano degli enti di base non si sostituisce
        if len(other.get("description") or "") > len(node.get("description") or "") and \
                node.get("risk_basis") != "Valore assegnato manualmente":
            node["description"] = other["description"]
        node["created_at"] = min(filter(None, [node.get("created_at"), other.get("created_at")]), default=None)
        node["updated_at"] = max(filter(None, [node.get("updated_at"), other.get("updated_at")]), default=None)

    @staticmethod
    def _apply_canonical(node: Dict, r: Dict):
        """Nome, tipo e regione canonici per le entità riconosciute (enti, eventi, paesi...)."""
        if r.get("label") and r["label"] != node.get("label"):
            aliases = set(node.get("aliases", []))
            if node.get("label"):
                aliases.add(node["label"])
            aliases.discard(r["label"])
            node["label"] = r["label"]
            if aliases:
                node["aliases"] = sorted(aliases)
            else:
                node.pop("aliases", None)
        for k in ("type", "region", "full_name", "disease"):
            if r.get(k):
                node[k] = r[k]

    async def upsert_entities(self, entities: List[Dict]):
        """Inserisce o aggiorna le entità, accorpando i nomi diversi della stessa entità.

        La corrispondenza id dell'estrazione -> id canonico serve a upsert_relations
        per le relazioni dello stesso lotto.
        """
        now = datetime.utcnow().isoformat()
        key_index = self._key_index()
        self._batch_ids = {}
        for e in entities:
            if not e.get("id") and not e.get("label"):
                continue
            cid, r = self._canonical_id(e, key_index)
            if e.get("id"):
                self._batch_ids[e["id"]] = cid
            incoming = {
                "id": cid, "label": e.get("label") or e.get("id"),
                "type": e.get("type", "HospitalNetwork"), "domain": "health",
                "region": e.get("region"), "description": e.get("description", ""),
                "risk_score": e.get("risk_score", 0),
                "created_at": now, "updated_at": now,
            }
            if e.get("risk_basis"):
                incoming["risk_basis"] = e["risk_basis"]
            if cid in self.nodes:
                self._absorb(self.nodes[cid], incoming)
                self.nodes[cid]["updated_at"] = now
            else:
                self.nodes[cid] = incoming
            self._apply_canonical(self.nodes[cid], r)
            key_index[r["key"]] = cid

    @staticmethod
    def _edge_docs(e: Dict) -> List[str]:
        docs = [d for d in [e.get("source_doc")] + list(e.get("source_docs") or []) if d]
        return list(dict.fromkeys(docs))

    @classmethod
    def _absorb_edge(cls, edge: Dict, other: Dict):
        """Stessa relazione da un'altra fonte: si conservano tutte le fonti."""
        docs = list(dict.fromkeys(cls._edge_docs(edge) + cls._edge_docs(other)))
        if other.get("risk_score", 0) > edge.get("risk_score", 0):
            edge["risk_score"] = other["risk_score"]
            if other.get("fact"):
                edge["fact"] = other["fact"]
        if not edge.get("fact") and other.get("fact"):
            edge["fact"] = other["fact"]
        if not edge.get("date") and other.get("date"):
            edge["date"] = other["date"]
        edge["source_doc"] = docs[0] if docs else ""
        if len(docs) > 1:
            edge["source_docs"] = docs
        titles = {**(other.get("doc_titles") or {}), **(edge.get("doc_titles") or {})}
        if titles:
            edge["doc_titles"] = titles
        edge["created_at"] = min(filter(None, [edge.get("created_at"), other.get("created_at")]), default=None)

    async def upsert_relations(self, relations: List[Dict]):
        now = datetime.utcnow().isoformat()
        ids = getattr(self, "_batch_ids", {})
        for r in relations:
            src = ids.get(r.get("source"), r.get("source"))
            tgt = ids.get(r.get("target"), r.get("target"))
            if not src or not tgt or src == tgt:
                continue
            rtype = r.get("type", "COLLABORA_CON")
            rid = r.get("id") or f"{src}_{tgt}_{rtype}"
            incoming = {
                "id": rid, "source": src, "target": tgt, "type": rtype,
                "fact": r.get("fact"), "risk_score": r.get("risk_score", 0),
                "source_doc": r.get("source_doc", ""), "date": r.get("date"),
                "created_at": now,
            }
            if r.get("doc_titles"):
                incoming["doc_titles"] = r["doc_titles"]
            if rid in self.edges:
                self._absorb_edge(self.edges[rid], incoming)
            else:
                self.edges[rid] = incoming

    def merge_duplicates(self) -> Dict:
        """Accorpa i nodi che sono la stessa entità con nomi diversi (vedi normalize.py).

        Le relazioni passano al nodo accorpato; quelle uguali (stessi nodi e tipo) si
        uniscono conservando tutte le fonti; le relazioni di un nodo con sé stesso si
        eliminano. I richiami FDA restano uno per relazione. Restituisce un resoconto.
        """
        # 1. Chiave canonica di ogni nodo; gli eventi senza paese si agganciano,
        #    se c'è, all'unico evento della stessa malattia con paese
        res = {nid: self._resolve(n.get("label", ""), n.get("type", ""), n.get("region"), events={})
               for nid, n in self.nodes.items()}
        events = {r["id"]: r["disease"] for r in res.values()
                  if r.get("disease") and r["id"] != f"evt_{r['disease']}"}
        for nid, r in list(res.items()):
            if r.get("disease") and r["id"] == f"evt_{r['disease']}":
                n = self.nodes[nid]
                res[nid] = self._resolve(n.get("label", ""), n.get("type", ""), n.get("region"), events=events)

        groups: Dict[str, List[str]] = {}
        for nid, r in res.items():
            groups.setdefault(r["key"], []).append(nid)

        degree: Dict[str, int] = {}
        for e in self.edges.values():
            for end in (e.get("source"), e.get("target")):
                degree[end] = degree.get(end, 0) + 1

        # 2. Nodo che resta per ogni gruppo: id canonico per le entità riconosciute,
        #    altrimenti l'ente di base inserito a mano o il nodo con più relazioni
        mapping: Dict[str, str] = {}
        new_nodes: Dict[str, Dict] = {}
        report = []
        for key, members in groups.items():
            r = res[members[0]]
            members.sort(key=lambda m: (self.nodes[m].get("risk_basis") != "Valore assegnato manualmente",
                                        -degree.get(m, 0), len(m), m))
            target = members[0] if key.startswith("name:") else r["id"]
            base, i = target, 2
            while target in new_nodes:
                target, i = f"{base}_{i}", i + 1
            node = copy.deepcopy(self.nodes[members[0]])
            node["id"] = target
            for m in members[1:]:
                self._absorb(node, self.nodes[m])
            types = [self.nodes[m].get("type") for m in members]
            if not r.get("type"):
                node["type"] = max(set(types), key=lambda t: (types.count(t), t == node.get("type")))
            self._apply_canonical(node, r)
            if not node.get("description") and node.get("full_name"):
                node["description"] = node["full_name"]
            new_nodes[target] = node
            for m in members:
                mapping[m] = target
            if len(members) > 1 or target != members[0]:
                report.append({"id": target, "label": node["label"],
                               "merged": [(m, self.nodes[m].get("label")) for m in members]})

        # 3. Relazioni sui nodi accorpati, senza doppioni né anelli
        new_edges: Dict[str, Dict] = {}
        self_loops = 0
        for k, e in self.edges.items():
            e = copy.deepcopy(e)
            e["source"] = mapping.get(e.get("source"), e.get("source"))
            e["target"] = mapping.get(e.get("target"), e.get("target"))
            if e["source"] == e["target"]:
                self_loops += 1
                continue
            rid = k if k.startswith("recall_") else f"{e['source']}_{e['target']}_{e.get('type')}"
            e["id"] = rid
            if rid in new_edges:
                self._absorb_edge(new_edges[rid], e)
            else:
                docs = self._edge_docs(e)
                e["source_doc"] = docs[0] if docs else ""
                if len(docs) > 1:
                    e["source_docs"] = docs
                new_edges[rid] = e

        # 4. Gli alert citano i nodi per id
        for a in self.alerts.values():
            try:
                ids = json.loads(a.get("entities_involved") or "[]")
                a["entities_involved"] = json.dumps(list(dict.fromkeys(mapping.get(i, i) for i in ids)))
            except (TypeError, ValueError):
                pass

        summary = {"nodes_before": len(self.nodes), "nodes_after": len(new_nodes),
                   "edges_before": len(self.edges), "edges_after": len(new_edges),
                   "self_loops_dropped": self_loops, "groups": report}
        self.nodes, self.edges = new_nodes, new_edges
        return summary

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
                "italy_relevance": (a.get("italy_relevance") or "").upper() or None,
                "italy_impact": a.get("italy_impact"),
                "timeframe": a.get("timeframe"), "recommendation": a.get("recommendation"),
                "created_at": now, "is_read": False,
            }
