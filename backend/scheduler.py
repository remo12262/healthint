import asyncio
from datetime import datetime


class Scheduler:
    """Aggiornamento dati su richiesta (solo via POST /api/refresh, mai automatico)."""

    def __init__(self, scraper, extractor, db):
        self.scraper = scraper
        self.extractor = extractor
        self.db = db
        self.last_run = None
        self.lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self.lock.locked()

    async def run_once(self):
        if self.lock.locked():
            print("[scheduler] Refresh già in corso: richiesta ignorata")
            return
        async with self.lock:
            await self._refresh()

    async def _refresh(self):
        print(f"[scheduler] Starting data refresh at {datetime.utcnow().isoformat()}")
        try:
            # 1. Fetch real data from OpenFDA and WHO (24h cached)
            data = await self.scraper.fetch_all()
            print(
                f"[scheduler] Fetched: {len(data['drug_recalls'])} drug recalls, "
                f"{len(data['device_recalls'])} device recalls, "
                f"{len(data['who_outbreaks'])} WHO outbreaks"
            )

            # 2. Process drug recalls directly into graph (no Claude)
            if data["drug_recalls"]:
                result = self.extractor.process_recalls(data["drug_recalls"])
                await self.db.upsert_entities(result["entities"])
                await self.db.upsert_relations(result["relations"])
                print(f"[scheduler] Drug recalls: {len(result['entities'])} entities, {len(result['relations'])} relations")

            # 3. Process medical device recalls directly into graph (no Claude)
            if data["device_recalls"]:
                result = self.extractor.process_recalls(data["device_recalls"])
                await self.db.upsert_entities(result["entities"])
                await self.db.upsert_relations(result["relations"])
                print(f"[scheduler] Device recalls: {len(result['entities'])} entities, {len(result['relations'])} relations")

            # 4. Claude analysis of WHO Disease Outbreak News for additional threat intel
            if data["who_outbreaks"]:
                result = await self.extractor.extract_batch(data["who_outbreaks"][:5], text_field="summary")
                await self.db.upsert_entities(result["entities"])
                await self.db.upsert_relations(result["relations"])
                print(f"[scheduler] WHO Claude extraction: {len(result['entities'])} entities, {len(result['relations'])} relations")

            # 5. Generate predictive alerts from the full graph
            nodes = await self.db.get_nodes()
            edges = await self.db.get_edges()
            alerts = await self.extractor.generate_alerts(nodes, edges)
            if alerts:
                await self.db.upsert_alerts(alerts)
                print(f"[scheduler] Generated {len(alerts)} alerts")

            self.last_run = datetime.utcnow().isoformat()
            self.db.updated_at = self.last_run
            print(f"[scheduler] Refresh complete at {self.last_run}")

        except Exception as e:
            print(f"[scheduler] Error during refresh: {e}")
