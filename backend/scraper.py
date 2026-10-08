import httpx
import json
import os
import re
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional

CACHE_FILE = os.environ.get("CACHE_FILE", "healthint_cache.json")
CACHE_TTL_HOURS = 24

OPENFDA_DRUG_URL = "https://api.fda.gov/drug/enforcement.json"
OPENFDA_DEVICE_URL = "https://api.fda.gov/device/enforcement.json"
# Il vecchio feed RSS (feeds/entity/csr/don) risponde 404: l'OMS pubblica le
# Disease Outbreak News tramite questa API OData
WHO_DON_API = "https://www.who.int/api/news/diseaseoutbreaknews"
WHO_DON_PAGE = "https://www.who.int/emergencies/disease-outbreak-news/item/"

# Fonti mostrate nell'interfaccia
SOURCES = [
    {"key": "openfda_drug", "label": "openFDA – richiami farmaci (FDA USA)", "url": "https://open.fda.gov/apis/drug/enforcement/"},
    {"key": "openfda_device", "label": "openFDA – richiami dispositivi medici (FDA USA)", "url": "https://open.fda.gov/apis/device/enforcement/"},
    {"key": "who_outbreaks", "label": "OMS – Disease Outbreak News", "url": "https://www.who.int/emergencies/disease-outbreak-news"},
]


class DataScraper:

    def __init__(self):
        # Esito dell'ultimo tentativo per fonte: None se ok, altrimenti il messaggio d'errore
        self.errors: Dict[str, Optional[str]] = {}

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

    def _store(self, key: str, data: List[Dict]):
        cache = self._load_cache()
        cache[key] = {"data": data, "fetched_at": datetime.utcnow().isoformat()}
        self._save_cache(cache)

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

    async def _fetch_openfda(self, key: str, url: str, product_type: str, force: bool) -> List[Dict]:
        """Richiami distribuiti in Italia da openFDA, integrati con i Class I mondiali se pochi."""
        cache = self._load_cache()
        if not force and self._is_fresh(cache, key):
            print(f"[scraper] Cache hit: {key} ({len(cache[key]['data'])} entries)")
            self.errors[key] = None
            return cache[key]["data"]

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(url, params={
                    "search": "distribution_pattern:Italy",
                    "limit": 40,
                    "sort": "report_date:desc",
                })
                r.raise_for_status()
                results = r.json().get("results", [])

                if len(results) < 10:
                    r2 = await client.get(url, params={
                        "search": 'distribution_pattern:"Worldwide" AND classification:"Class I"',
                        "limit": 20,
                        "sort": "report_date:desc",
                    })
                    if r2.status_code == 200:
                        results.extend(r2.json().get("results", []))
        except Exception as e:
            self.errors[key] = f"{type(e).__name__}: {e}"
            print(f"[scraper] ERRORE {key}: {self.errors[key]}")
            return []

        recalls = self._parse_openfda_recalls(results, product_type)
        self._store(key, recalls)
        self.errors[key] = None
        print(f"[scraper] Fetched {len(recalls)} {product_type} recalls from OpenFDA")
        return recalls

    async def fetch_openfda_drug_recalls(self, force: bool = False) -> List[Dict]:
        return await self._fetch_openfda("openfda_drug", OPENFDA_DRUG_URL, "drug", force)

    async def fetch_openfda_device_recalls(self, force: bool = False) -> List[Dict]:
        return await self._fetch_openfda("openfda_device", OPENFDA_DEVICE_URL, "device", force)

    async def fetch_who_outbreaks(self, force: bool = False) -> List[Dict]:
        """Ultime Disease Outbreak News dell'OMS."""
        key = "who_outbreaks"
        cache = self._load_cache()
        if not force and self._is_fresh(cache, key):
            print(f"[scraper] Cache hit: WHO outbreaks ({len(cache[key]['data'])} entries)")
            self.errors[key] = None
            return cache[key]["data"]

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(WHO_DON_API, params={
                    "$orderby": "PublicationDateAndTime desc",
                    "$top": 20,
                    "$select": "Title,Summary,PublicationDateAndTime,UrlName",
                })
                r.raise_for_status()
                items = r.json().get("value", [])
            if not items:
                raise ValueError("risposta senza notizie")
        except Exception as e:
            self.errors[key] = f"{type(e).__name__}: {e}"
            print(f"[scraper] ERRORE {key}: {self.errors[key]}")
            return []

        outbreaks = []
        for item in items:
            summary = re.sub(r"<[^>]+>", " ", item.get("Summary") or "")
            summary = re.sub(r"\s+", " ", summary).strip()
            outbreaks.append({
                "id": item.get("UrlName", ""),
                "title": item.get("Title", ""),
                "summary": summary[:1500],
                "url": WHO_DON_PAGE + item.get("UrlName", ""),
                "published": (item.get("PublicationDateAndTime") or "")[:10],
                "source": "WHO Disease Outbreak News",
            })
        self._store(key, outbreaks)
        self.errors[key] = None
        print(f"[scraper] Fetched {len(outbreaks)} WHO outbreak entries")
        return outbreaks

    async def fetch_all(self, force: bool = False) -> Dict:
        """Scarica tutte le fonti. Con force=True ignora la cache di 24 ore."""
        drug_recalls, device_recalls, who_outbreaks = await asyncio.gather(
            self.fetch_openfda_drug_recalls(force),
            self.fetch_openfda_device_recalls(force),
            self.fetch_who_outbreaks(force),
        )
        return {
            "drug_recalls": drug_recalls,
            "device_recalls": device_recalls,
            "who_outbreaks": who_outbreaks,
            "errors": {k: v for k, v in self.errors.items() if v},
            "fetched_at": datetime.utcnow().isoformat(),
        }
