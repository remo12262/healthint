import httpx
import feedparser
import json
import os
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict

CACHE_FILE = os.environ.get("CACHE_FILE", "healthint_cache.json")
CACHE_TTL_HOURS = 24

OPENFDA_DRUG_URL = "https://api.fda.gov/drug/enforcement.json"
OPENFDA_DEVICE_URL = "https://api.fda.gov/device/enforcement.json"
WHO_OUTBREAK_RSS = "https://www.who.int/feeds/entity/csr/don/en/rss.xml"


class DataScraper:

    def _load_cache(self) -> Dict:
        try:
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_cache(self, cache: Dict):
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump(cache, f)
        except Exception as e:
            print(f"[scraper] Cache save error: {e}")

    def _is_fresh(self, cache: Dict, key: str) -> bool:
        entry = cache.get(key, {})
        fetched_at = entry.get("fetched_at")
        if not fetched_at:
            return False
        age = datetime.utcnow() - datetime.fromisoformat(fetched_at)
        return age < timedelta(hours=CACHE_TTL_HOURS)

    def get_cache_info(self) -> Dict:
        cache = self._load_cache()
        return {
            key: {
                "fetched_at": val.get("fetched_at"),
                "count": len(val.get("data", [])),
                "fresh": self._is_fresh(cache, key),
            }
            for key, val in cache.items()
        }

    def _parse_openfda_recalls(self, results: List[Dict], product_type: str) -> List[Dict]:
        classification_risk = {"Class I": 85, "Class II": 55, "Class III": 25}
        recalls = []
        for item in results:
            classification = item.get("classification", "")
            recalls.append({
                "id": item.get("recall_number", ""),
                "recalling_firm": item.get("recalling_firm", "").strip(),
                "product_description": item.get("product_description", "")[:200],
                "reason_for_recall": item.get("reason_for_recall", "")[:200],
                "classification": classification,
                "risk_score": classification_risk.get(classification, 40),
                "distribution_pattern": item.get("distribution_pattern", ""),
                "country": item.get("country", ""),
                "report_date": item.get("report_date", ""),
                "status": item.get("status", ""),
                "product_type": product_type,
            })
        return recalls

    async def fetch_openfda_drug_recalls(self) -> List[Dict]:
        """Fetch drug recall enforcement actions from OpenFDA distributed in Italy/EU, with 24h cache."""
        cache = self._load_cache()
        cache_key = "openfda_drug"
        if self._is_fresh(cache, cache_key):
            print(f"[scraper] Cache hit: OpenFDA drug recalls ({len(cache[cache_key]['data'])} entries)")
            return cache[cache_key]["data"]

        results = []
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Primary: recalls distributed in Italy
                r = await client.get(OPENFDA_DRUG_URL, params={
                    "search": "distribution_pattern:Italy",
                    "limit": 40,
                    "sort": "report_date:desc",
                })
                r.raise_for_status()
                results = r.json().get("results", [])

                # Supplement with worldwide Class I recalls if few Italy-specific results
                if len(results) < 10:
                    r2 = await client.get(OPENFDA_DRUG_URL, params={
                        "search": 'distribution_pattern:"Worldwide" AND classification:"Class I"',
                        "limit": 20,
                        "sort": "report_date:desc",
                    })
                    if r2.status_code == 200:
                        results.extend(r2.json().get("results", []))
        except Exception as e:
            print(f"[scraper] OpenFDA drug error: {e}")
            return cache.get(cache_key, {}).get("data", [])

        recalls = self._parse_openfda_recalls(results, "drug")
        cache[cache_key] = {"data": recalls, "fetched_at": datetime.utcnow().isoformat()}
        self._save_cache(cache)
        print(f"[scraper] Fetched {len(recalls)} drug recalls from OpenFDA")
        return recalls

    async def fetch_openfda_device_recalls(self) -> List[Dict]:
        """Fetch medical device recall enforcement actions from OpenFDA distributed in Italy/EU, with 24h cache."""
        cache = self._load_cache()
        cache_key = "openfda_device"
        if self._is_fresh(cache, cache_key):
            print(f"[scraper] Cache hit: OpenFDA device recalls ({len(cache[cache_key]['data'])} entries)")
            return cache[cache_key]["data"]

        results = []
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(OPENFDA_DEVICE_URL, params={
                    "search": "distribution_pattern:Italy",
                    "limit": 40,
                    "sort": "report_date:desc",
                })
                r.raise_for_status()
                results = r.json().get("results", [])

                if len(results) < 10:
                    r2 = await client.get(OPENFDA_DEVICE_URL, params={
                        "search": 'distribution_pattern:"Worldwide" AND classification:"Class I"',
                        "limit": 20,
                        "sort": "report_date:desc",
                    })
                    if r2.status_code == 200:
                        results.extend(r2.json().get("results", []))
        except Exception as e:
            print(f"[scraper] OpenFDA device error: {e}")
            return cache.get(cache_key, {}).get("data", [])

        recalls = self._parse_openfda_recalls(results, "device")
        cache[cache_key] = {"data": recalls, "fetched_at": datetime.utcnow().isoformat()}
        self._save_cache(cache)
        print(f"[scraper] Fetched {len(recalls)} device recalls from OpenFDA")
        return recalls

    async def fetch_who_outbreaks(self) -> List[Dict]:
        """Fetch WHO Disease Outbreak News from RSS with 24h cache."""
        cache = self._load_cache()
        cache_key = "who_outbreaks"
        if self._is_fresh(cache, cache_key):
            print(f"[scraper] Cache hit: WHO outbreaks ({len(cache[cache_key]['data'])} entries)")
            return cache[cache_key]["data"]

        try:
            feed = feedparser.parse(WHO_OUTBREAK_RSS)
            outbreaks = []
            for entry in feed.entries[:20]:
                outbreaks.append({
                    "id": entry.get("id", entry.get("link", "")),
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:500],
                    "url": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "source": "WHO Disease Outbreak News",
                })
            cache[cache_key] = {"data": outbreaks, "fetched_at": datetime.utcnow().isoformat()}
            self._save_cache(cache)
            print(f"[scraper] Fetched {len(outbreaks)} WHO outbreak entries")
            return outbreaks
        except Exception as e:
            print(f"[scraper] WHO outbreak error: {e}")
            return cache.get(cache_key, {}).get("data", [])

    async def fetch_all(self) -> Dict:
        """Fetch all data sources with 24h caching."""
        drug_recalls, device_recalls, who_outbreaks = await asyncio.gather(
            self.fetch_openfda_drug_recalls(),
            self.fetch_openfda_device_recalls(),
            self.fetch_who_outbreaks(),
        )
        return {
            "drug_recalls": drug_recalls,
            "device_recalls": device_recalls,
            "who_outbreaks": who_outbreaks,
            "fetched_at": datetime.utcnow().isoformat(),
        }
