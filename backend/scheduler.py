import asyncio
from datetime import datetime

from extractor import AIError, RISK_WORDS_IT
import normalize

# Testi passati a Claude per aggiornamento (una chiamata ciascuno), come prima delle fonti italiane:
# solo documenti mai analizzati, prima le notizie OMS nuove (max 3), poi le italiane più rilevanti
AI_TEXTS_PER_REFRESH = 5
AI_WHO_MAX = 3
# Atti di routine della Gazzetta (autorizzazioni dei singoli medicinali): solo come segnalazioni
ROUTINE_IT = ("modifica dell autorizzazione", "classificazione ai sensi", "decadenza", "rettifica",
              "aggiornamento sezione", "liste di trasparenza", "diario di bordo")


class Scheduler:
    """Aggiornamento dati su richiesta: POST /api/refresh (GitHub Actions, 2 volte al giorno)
    o POST /api/refresh/manual (pulsante "Aggiorna dati", al massimo una volta all'ora)."""

    def __init__(self, scraper, extractor, db):
        self.scraper = scraper
        self.extractor = extractor
        self.db = db
        self.lock = asyncio.Lock()
        self.last_attempt = None
        self.last_error = None

    @property
    def running(self) -> bool:
        return self.lock.locked()

    async def run_once(self) -> bool:
        """Esegue un aggiornamento completo. True se i dati sono stati aggiornati."""
        if self.lock.locked():
            print("[scheduler] Refresh già in corso: richiesta ignorata")
            return False
        async with self.lock:
            return await self._refresh()

    async def _refresh(self) -> bool:
        started = datetime.utcnow().isoformat()
        self.last_attempt = started
        print(f"[scheduler] Starting data refresh at {started}")
        # Ultima versione funzionante: si ripristina se l'aggiornamento produce dati non validi
        snap = self.db.snapshot()
        try:
            # 1. Fonti esterne, senza cache: openFDA, OMS e fonti italiane
            data = await self.scraper.fetch_all(force=True)
            source_errors = data["errors"]
            counts = {
                "openfda_drug": len(data["drug_recalls"]),
                "openfda_device": len(data["device_recalls"]),
                "who_outbreaks": len(data["who_outbreaks"]),
                "italy": len(data["italy"]),
            }
            print(f"[scheduler] Fetched: {counts}; errori fonti: {source_errors or 'nessuno'}")
            if not any(counts.values()):
                raise RuntimeError("nessuna fonte raggiungibile: " + "; ".join(
                    f"{k}: {v}" for k, v in source_errors.items()))

            # Fonti che hanno davvero portato dati nel grafo: senza almeno una,
            # l'aggiornamento non conta come riuscito e la data non cambia
            contributed = []

            # 2. Richiami openFDA direttamente nel grafo (senza Claude), uno per relazione.
            # Le relazioni del vecchio formato si tolgono solo se arrivano entrambe le liste
            if data["drug_recalls"] and data["device_recalls"]:
                self.db.drop_legacy_recall_edges()
            for key, source in (("drug_recalls", "openfda_drug"), ("device_recalls", "openfda_device")):
                if data[key]:
                    result = self.extractor.process_recalls(data[key])
                    await self.db.upsert_entities(result["entities"])
                    await self.db.upsert_relations(result["relations"])
                    contributed.append(source)

            # 3. Fonti italiane collegate in codice ai nodi del nucleo (senza Claude)
            it_relations = self.extractor.process_italy(data["italy"])
            await self.db.upsert_relations(it_relations)
            if data["italy"]:
                contributed.append("italy")
            print(f"[scheduler] Fonti italiane: {len(data['italy'])} documenti, {len(it_relations)} relazioni con il nucleo")

            # 4. Claude solo sui documenti mai analizzati, entro AI_TEXTS_PER_REFRESH testi
            done = set(self.db.processed_docs)
            # Come prima: solo le 5 notizie OMS più recenti; quelle già analizzate non si ripetono
            who_new = [o for o in data["who_outbreaks"][:AI_TEXTS_PER_REFRESH] if o.get("id") and o["id"] not in done]
            it_new = [i for i in data["italy"] if i["id"] not in done and self._relevant_it(i)]
            who_pick = who_new[:AI_WHO_MAX]
            it_pick = it_new[:AI_TEXTS_PER_REFRESH - len(who_pick)]
            who_pick += who_new[len(who_pick):len(who_pick) + AI_TEXTS_PER_REFRESH - len(who_pick) - len(it_pick)]
            for items, basis, key in ((who_pick, "Stima dell'AI dalle notizie OMS", "who_outbreaks"),
                                      (it_pick, "Stima dell'AI dalle fonti italiane", "italy")):
                if not items:
                    continue
                result = await self.extractor.extract_batch(items, text_field="summary")
                titles = {i["id"]: f"{i.get('source', 'OMS')} – {i['title']}" for i in items}
                for ent in result["entities"]:
                    ent["risk_basis"] = basis
                for rel in result["relations"]:
                    if str(rel.get("source_doc", "")).startswith("http"):
                        rel["doc_titles"] = {rel["source_doc"]: titles.get(rel["source_doc"], "")}
                await self.db.upsert_entities(result["entities"])
                await self.db.upsert_relations(result["relations"])
                print(f"[scheduler] Claude ({key}): {len(items)} testi, {len(result['entities'])} entità, "
                      f"{len(result['relations'])} relazioni, {len(result['errors'])} errori")
                if result["errors"] and len(result["errors"]) == len(items):
                    source_errors[f"{key}_analysis"] = "analisi AI non riuscita: " + result["errors"][0]
                else:
                    self.db.mark_processed([i["id"] for i in items])
                    if key not in contributed:
                        contributed.append(key)

            if not contributed:
                raise RuntimeError("nessun dato nuovo è entrato nel grafo: " + "; ".join(
                    f"{k}: {str(v).splitlines()[0][:160]}" for k, v in source_errors.items()))

            # Stessa entità con nomi diversi (WHO/OMS, province, eventi...): un solo nodo, in codice
            merged = self.db.merge_duplicates()
            if merged["nodes_after"] < merged["nodes_before"]:
                print(f"[scheduler] Accorpati doppioni: nodi {merged['nodes_before']} -> {merged['nodes_after']}, "
                      f"relazioni {merged['edges_before']} -> {merged['edges_after']}")

            # Nucleo fisso italiano sempre presente, con le sue fonti
            self.db.ensure_nucleus()

            # Rischio delle aziende ricalcolato da gravità e recenza dei richiami
            self.db.recompute_recall_risk()

            # Segnalazioni dalle fonti, senza AI: se una fonte non risponde restano le precedenti
            self.db.signals = self._signals(data, snap.get("signals") or {})

            # 4. Verifica: relazioni orfane eliminate, grafo non valido -> si scarta tutto
            orphans = self.db.drop_orphan_edges()
            if orphans:
                print(f"[scheduler] Scartate {orphans} relazioni che puntavano a nodi inesistenti")
            problems = self.db.validate(len(snap["nodes"]))
            if problems:
                raise ValueError("dati nuovi non validi, mantenuta la versione precedente: " + "; ".join(problems))

            # 5. Alert generati dall'AI: se falliscono restano quelli precedenti e l'errore è visibile
            nodes = await self.db.get_nodes()
            edges = await self.db.get_edges()
            alerts_error = None
            try:
                alerts = await self.extractor.generate_alerts(nodes, edges)
                await self.db.replace_alerts(alerts)
                print(f"[scheduler] Generated {len(alerts)} alerts")
            except AIError as e:
                alerts_error = str(e)
                print(f"[scheduler] ERRORE generazione alert: {alerts_error}")

            # Novità rispetto alla versione precedente e data del dato più recente alla fonte
            new = {
                "nodes": len(set(self.db.nodes) - set(snap["nodes"])),
                "edges": len(set(self.db.edges) - set(snap["edges"])),
                "alerts": len(set(self.db.alerts) - set(snap["alerts"])),
            }
            rd = lambda items: max((r.get("report_date", "") for r in items), default="")
            iso = lambda d: f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else None
            latest = {
                "openfda_drug": iso(rd(data["drug_recalls"])),
                "openfda_device": iso(rd(data["device_recalls"])),
                "who_outbreaks": max((o.get("published", "") for o in data["who_outbreaks"]), default="") or None,
                "italy": max((i.get("published") or "" for i in data["italy"]), default="") or None,
            }
            print(f"[scheduler] Novità: {new}; dato più recente alla fonte: {latest}")

            finished = datetime.utcnow().isoformat()
            self.db.updated_at = finished
            self.db.refresh_info = {
                "last_success": finished,
                "contributed": contributed,
                "new": new,
                "latest_at_source": latest,
                "counts": counts,
                "source_errors": source_errors,
                "alerts_error": alerts_error,
                "alerts_attempt": finished,
            }
            self.last_error = None
            print(f"[scheduler] Refresh complete at {finished}")
            return True

        except Exception as e:
            self.db.restore(snap)
            self.last_error = f"{type(e).__name__}: {e}"
            print(f"[scheduler] ERRORE durante il refresh, ripristinata l'ultima versione funzionante: {self.last_error}")
            return False

    @staticmethod
    def _signals(data: dict, previous: dict) -> dict:
        def iso(d):
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d or "") == 8 else None

        who = [{"title": o["title"], "date": o.get("published"), "url": o.get("url")}
               for o in data["who_outbreaks"][:8]] or previous.get("who", [])
        recalls = []
        for key, kind in (("drug_recalls", "drug"), ("device_recalls", "device")):
            for r in data[key]:
                recalls.append({
                    "recall": r.get("id"), "class": r.get("classification"), "firm": r.get("recalling_firm"),
                    "product": r.get("product_description", "")[:160], "reason": r.get("reason_for_recall", "")[:200],
                    "date": iso(r.get("report_date", "")), "kind": kind,
                    "url": f"https://api.fda.gov/{kind}/enforcement.json?search=recall_number:%22{r.get('id')}%22",
                })
        recalls.sort(key=lambda r: r["date"] or "", reverse=True)
        if not recalls:
            recalls = previous.get("recalls", [])
        italy = [{"title": i["title"], "date": i.get("published"), "url": i["url"], "source": i.get("source"),
                  "summary": (i.get("summary") or "")[:280]}
                 for i in data.get("italy", [])[:20]] or previous.get("italy", [])
        return {"generated_at": datetime.utcnow().isoformat(), "who": who, "recalls": recalls[:12], "italy": italy}

    @staticmethod
    def _relevant_it(item: dict) -> bool:
        """Documento italiano da far leggere a Claude: non di routine, con un tema di rischio."""
        if item.get("source") == "ISS – RespiVirNet":
            return False
        text = f" {normalize.norm(item.get('title', '') + ' ' + item.get('summary', ''))} "
        if any(r in text for r in ROUTINE_IT) or len(text) < 80:
            return False
        return any(f" {w}" in text for w in RISK_WORDS_IT)

    def status(self) -> dict:
        info = self.db.refresh_info or {}
        return {
            "running": self.running,
            "updated_at": self.db.updated_at,
            "last_attempt": self.last_attempt,
            "last_error": self.last_error,
            "source_errors": info.get("source_errors") or {},
            "alerts_error": info.get("alerts_error"),
            "alerts_attempt": info.get("alerts_attempt"),
            "counts": info.get("counts") or {},
            "new": info.get("new"),
            "latest_at_source": info.get("latest_at_source") or {},
        }
