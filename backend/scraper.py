import feedparser
import httpx
import json
import os
import re
import asyncio
from datetime import datetime, timedelta
from html import unescape
from typing import List, Dict, Optional

CACHE_FILE = os.environ.get("CACHE_FILE", "healthint_cache.json")
CACHE_TTL_HOURS = 24

OPENFDA_DRUG_URL = "https://api.fda.gov/drug/enforcement.json"
OPENFDA_DEVICE_URL = "https://api.fda.gov/device/enforcement.json"
# Il vecchio feed RSS (feeds/entity/csr/don) risponde 404: l'OMS pubblica le
# Disease Outbreak News tramite questa API OData
WHO_DON_API = "https://www.who.int/api/news/diseaseoutbreaknews"
WHO_DON_PAGE = "https://www.who.int/emergencies/disease-outbreak-news/item/"

# Fonti italiane. Il sito del Ministero della Salute blocca i client automatici (protezione
# anti-bot): i suoi atti arrivano dalla Gazzetta Ufficiale. L'ISS non ha feed RSS: si legge
# la pagina dei comunicati stampa. RespiVirNet pubblica solo la pagina del rapporto settimanale.
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
AIFA_FEED = ("https://www.aifa.gov.it/o/feedrss/rss?structureId=93604&groupId=20142&companyId=20115"
             "&basePortalURL=https://www.aifa.gov.it&locale=it_IT")
IT_FEEDS = [
    # chiave, URL, ente che pubblica, etichetta
    ("aifa_news", AIFA_FEED + "&size=10&excludeCategoryId=104878", "aifa", "AIFA – Notizie"),
    ("aifa_press", AIFA_FEED + "&size=6&categoryId=104878", "aifa", "AIFA – Comunicati stampa"),
    ("agenas", "https://www.agenas.gov.it/?format=feed&type=rss", "agenas", "AGENAS – Notizie"),
]
GU_FEED = "https://www.gazzettaufficiale.it/rss/SG"
# Enti sanitari nel titolo degli atti della Gazzetta Ufficiale -> nodo del grafo
GU_ISSUERS = {
    "MINISTERO DELLA SALUTE": "minsalute",
    "AGENZIA ITALIANA DEL FARMACO": "aifa",
    "ISTITUTO SUPERIORE DI SANITA": "iss",
    "AGENZIA NAZIONALE PER I SERVIZI SANITARI REGIONALI": "agenas",
}
ISS_PRESS = "https://www.iss.it/comunicati-stampa"
RESPIVIRNET = "https://respivirnet.iss.it/pagine/rapportoInflunet.aspx"
IT_MONTHS = {m: i for i, m in enumerate(["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
                                         "agosto", "settembre", "ottobre", "novembre", "dicembre"], 1)}

# Fonti mostrate nell'interfaccia
SOURCES = [
    {"key": "openfda_drug", "label": "openFDA – richiami farmaci (FDA USA)", "url": "https://open.fda.gov/apis/drug/enforcement/"},
    {"key": "openfda_device", "label": "openFDA – richiami dispositivi medici (FDA USA)", "url": "https://open.fda.gov/apis/device/enforcement/"},
    {"key": "who_outbreaks", "label": "OMS – Disease Outbreak News", "url": "https://www.who.int/emergencies/disease-outbreak-news"},
    {"key": "aifa", "label": "AIFA – notizie e comunicati (RSS)", "url": "https://www.aifa.gov.it/feed-rss"},
    {"key": "agenas", "label": "AGENAS (RSS)", "url": "https://www.agenas.gov.it/"},
    {"key": "iss", "label": "ISS – comunicati stampa", "url": ISS_PRESS},
    {"key": "respivirnet", "label": "ISS – RespiVirNet", "url": "https://respivirnet.iss.it/"},
    {"key": "gu_sanita", "label": "Gazzetta Ufficiale – atti di Ministero della Salute, AIFA, ISS, AGENAS (RSS)",
     "url": "https://www.gazzettaufficiale.it/"},
]


def _text(html: str) -> str:
    """Testo semplice da un frammento HTML."""
    html = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html or "", flags=re.S | re.I)
    t = unescape(re.sub(r"<[^>]+>", " ", html))
    return re.sub(r"\s+", " ", t).strip()


def _feed_date(entry) -> Optional[str]:
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    return f"{st.tm_year:04d}-{st.tm_mon:02d}-{st.tm_mday:02d}" if st else None


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
                # Record openFDA integrale, senza tagli né rielaborazioni (pannello "Record originale FDA")
                "raw": item,
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
                    "$select": "Title,Summary,PublicationDateAndTime,UrlName,DonId",
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
                "don_id": item.get("DonId") or "",
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

    async def _cached(self, key: str, force: bool, fetch) -> List[Dict]:
        """Esegue fetch() con la cache di 24 ore e registra l'esito della fonte."""
        cache = self._load_cache()
        if not force and self._is_fresh(cache, key):
            self.errors[key] = None
            return cache[key]["data"]
        try:
            items = await fetch()
            if not items:
                raise ValueError("nessun elemento ricevuto")
        except Exception as e:
            self.errors[key] = f"{type(e).__name__}: {e}"
            print(f"[scraper] ERRORE {key}: {self.errors[key]}")
            return []
        self._store(key, items)
        self.errors[key] = None
        print(f"[scraper] Fetched {len(items)} {key}")
        return items

    @staticmethod
    async def _get(client, url: str) -> httpx.Response:
        r = await client.get(url, headers={"User-Agent": BROWSER_UA, "Accept-Language": "it-IT,it;q=0.9"})
        r.raise_for_status()
        return r

    async def fetch_it_feed(self, key: str, url: str, publisher: str, label: str, force: bool = False) -> List[Dict]:
        async def fetch():
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                r = await self._get(client, url)
            feed = feedparser.parse(r.content)
            return [{
                "id": e.get("link", ""), "url": e.get("link", ""), "title": _text(e.get("title", "")),
                "summary": _text(e.get("summary", ""))[:1500], "published": _feed_date(e),
                "publisher": publisher, "source": label,
            } for e in feed.entries if e.get("link")]
        return await self._cached(key, force, fetch)

    async def fetch_gu_health(self, force: bool = False) -> List[Dict]:
        """Atti degli enti sanitari nell'ultima Serie Generale della Gazzetta Ufficiale."""
        async def fetch():
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                r = await self._get(client, GU_FEED)
            items = []
            for e in feedparser.parse(r.content).entries:
                title = _text(e.get("title", ""))
                issuer = next((nid for k, nid in GU_ISSUERS.items() if title.upper().startswith(k)), None)
                if not issuer:
                    continue
                link = e.get("link", "").replace("http://", "https://", 1)
                items.append({"id": link, "url": link, "title": title, "summary": _text(e.get("summary", ""))[:1500],
                              "published": _feed_date(e), "publisher": issuer, "source": "Gazzetta Ufficiale"})
            return items
        return await self._cached("gu_sanita", force, fetch)

    async def fetch_iss_press(self, force: bool = False, limit: int = 6) -> List[Dict]:
        """Ultimi comunicati stampa ISS: elenco dalla pagina, data e testo dalla pagina del comunicato."""
        async def fetch():
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                page = (await self._get(client, ISS_PRESS)).text
                links = list(dict.fromkeys(re.findall(
                    r'<a href="(https://www\.iss\.it/-/[^"]+)"[^>]*title="([^"]+)"', page)))[:limit]

                async def one(url, title):
                    try:
                        text = _text((await self._get(client, url)).text)
                    except Exception:
                        text = ""
                    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
                    date = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None
                    body = text[m.end():m.end() + 1500].strip() if m else ""
                    body = re.sub(r"^[-–\s]*(Modificato \d{1,2}/\d{1,2}/\d{4})?\s*", "", body)
                    return {"id": url, "url": url, "title": _text(title), "summary": body, "published": date,
                            "publisher": "iss", "source": "ISS – Comunicati stampa"}
                return list(await asyncio.gather(*(one(u, t) for u, t in links)))
        return await self._cached("iss_press", force, fetch)

    async def fetch_respivirnet(self, force: bool = False) -> List[Dict]:
        """Stato dell'ultimo rapporto RespiVirNet (sorveglianza dei virus respiratori)."""
        async def fetch():
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                text = _text((await self._get(client, RESPIVIRNET)).text)
            m = re.search(r"Aggiornamento del (\d{1,2}) (\w+) (\d{4})", text, re.I)
            if not m:
                raise ValueError("data del rapporto non trovata")
            date = f"{m.group(3)}-{IT_MONTHS.get(m.group(2).lower(), 1):02d}-{int(m.group(1)):02d}"
            k = text.find("Punti Chiave")
            summary = text[k + len("Punti Chiave"):k + 900].strip() if k >= 0 else text[m.end():m.end() + 900]
            return [{"id": f"respivirnet-{date}", "url": RESPIVIRNET,
                     "title": f"RespiVirNet: ultimo rapporto settimanale del {int(m.group(1))} {m.group(2)} {m.group(3)}",
                     "summary": summary, "published": date, "publisher": "iss", "source": "ISS – RespiVirNet"}]
        return await self._cached("respivirnet", force, fetch)

    async def fetch_italy(self, force: bool = False) -> List[Dict]:
        """Tutte le fonti italiane, dalla più recente."""
        results = await asyncio.gather(
            *(self.fetch_it_feed(k, u, p, l, force) for k, u, p, l in IT_FEEDS),
            self.fetch_gu_health(force), self.fetch_iss_press(force), self.fetch_respivirnet(force),
        )
        items = list({i["id"]: i for r in results for i in r}.values())
        return sorted(items, key=lambda i: i.get("published") or "", reverse=True)

    async def fetch_all(self, force: bool = False) -> Dict:
        """Scarica tutte le fonti. Con force=True ignora la cache di 24 ore."""
        drug_recalls, device_recalls, who_outbreaks, italy = await asyncio.gather(
            self.fetch_openfda_drug_recalls(force),
            self.fetch_openfda_device_recalls(force),
            self.fetch_who_outbreaks(force),
            self.fetch_italy(force),
        )
        return {
            "drug_recalls": drug_recalls,
            "device_recalls": device_recalls,
            "who_outbreaks": who_outbreaks,
            "italy": italy,
            "errors": {k: v for k, v in self.errors.items() if v},
            "fetched_at": datetime.utcnow().isoformat(),
        }
