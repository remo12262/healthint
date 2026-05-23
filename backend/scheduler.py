import asyncio
from datetime import datetime

REFRESH_INTERVAL = 6 * 60 * 60  # 6 hours in seconds


class Scheduler:

    def __init__(self, scraper, extractor, db):
        self.scraper = scraper
        self.extractor = extractor
        self.db = db
        self.last_run = None

    async def run_once(self):
        print(f"[scheduler] Starting data refresh at {datetime.utcnow().isoformat()}")
        try:
            data = await self.scraper.fetch_all()
            print(f"[scheduler] Fetched: {len(data['news'])} news, {len(data['research'])} research, {len(data['procurement'])} procurement")

            if data["news"]:
                result = await self.extractor.extract_batch(data["news"], text_field="summary")
                await self.db.upsert_entities(result["entities"])
                await self.db.upsert_relations(result["relations"])
                print(f"[scheduler] Extracted {len(result['entities'])} entities, {len(result['relations'])} relations from news")

            if data["research"]:
                result = await self.extractor.extract_batch(data["research"], text_field="summary")
                await self.db.upsert_entities(result["entities"])
                await self.db.upsert_relations(result["relations"])

            nodes = await self.db.get_nodes()
            edges = await self.db.get_edges()
            alerts = await self.extractor.generate_alerts(nodes, edges)
            if alerts:
                await self.db.upsert_alerts(alerts)
                print(f"[scheduler] Generated {len(alerts)} alerts")

            self.last_run = datetime.utcnow().isoformat()
            print(f"[scheduler] Refresh complete at {self.last_run}")

        except Exception as e:
            print(f"[scheduler] Error during refresh: {e}")

    async def run(self):
        """Run forever, refreshing every REFRESH_INTERVAL seconds."""
        while True:
            await self.run_once()
            await asyncio.sleep(REFRESH_INTERVAL)
