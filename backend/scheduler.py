import asyncio
from datetime import datetime

from extractor import AIError


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
            # 1. Fonti esterne, senza cache: openFDA e OMS
            data = await self.scraper.fetch_all(force=True)
            source_errors = data["errors"]
            counts = {
                "openfda_drug": len(data["drug_recalls"]),
                "openfda_device": len(data["device_recalls"]),
                "who_outbreaks": len(data["who_outbreaks"]),
            }
            print(f"[scheduler] Fetched: {counts}; errori fonti: {source_errors or 'nessuno'}")
            if len(source_errors) == len(counts):
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

            # 3. Notizie OMS analizzate da Claude
            if data["who_outbreaks"]:
                result = await self.extractor.extract_batch(data["who_outbreaks"][:5], text_field="summary")
                await self.db.upsert_entities(result["entities"])
                await self.db.upsert_relations(result["relations"])
                print(f"[scheduler] WHO Claude extraction: {len(result['entities'])} entities, "
                      f"{len(result['relations'])} relations, {len(result['errors'])} errori")
                if result["errors"] and len(result["errors"]) == min(5, len(data["who_outbreaks"])):
                    source_errors["who_analysis"] = "analisi AI delle notizie OMS non riuscita: " + result["errors"][0]
                else:
                    contributed.append("who_outbreaks")

            if not contributed:
                raise RuntimeError("nessun dato nuovo è entrato nel grafo: " + "; ".join(
                    f"{k}: {str(v).splitlines()[0][:160]}" for k, v in source_errors.items()))

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
