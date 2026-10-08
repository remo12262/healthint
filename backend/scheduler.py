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

            # 2. Richiami openFDA direttamente nel grafo (senza Claude)
            for key in ("drug_recalls", "device_recalls"):
                if data[key]:
                    result = self.extractor.process_recalls(data[key])
                    await self.db.upsert_entities(result["entities"])
                    await self.db.upsert_relations(result["relations"])

            # 3. Notizie OMS analizzate da Claude
            if data["who_outbreaks"]:
                result = await self.extractor.extract_batch(data["who_outbreaks"][:5], text_field="summary")
                await self.db.upsert_entities(result["entities"])
                await self.db.upsert_relations(result["relations"])
                print(f"[scheduler] WHO Claude extraction: {len(result['entities'])} entities, "
                      f"{len(result['relations'])} relations, {len(result['errors'])} errori")
                if result["errors"] and len(result["errors"]) == min(5, len(data["who_outbreaks"])):
                    source_errors["who_analysis"] = "analisi AI delle notizie OMS non riuscita: " + result["errors"][0]

            # 4. Alert predittivi: se falliscono restano quelli precedenti e l'errore è visibile
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

            finished = datetime.utcnow().isoformat()
            self.db.updated_at = finished
            self.db.refresh_info = {
                "last_success": finished,
                "counts": counts,
                "source_errors": source_errors,
                "alerts_error": alerts_error,
                "alerts_attempt": finished,
            }
            self.last_error = None
            print(f"[scheduler] Refresh complete at {finished}")
            return True

        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            print(f"[scheduler] ERRORE durante il refresh: {self.last_error}")
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
        }
