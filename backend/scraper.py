import httpx
import feedparser
import os
from datetime import datetime, timedelta
from typing import List, Dict

NEWS_SOURCES = [
    "https://www.who.int/rss-feeds/news-english.xml",
    "https://www.ema.europa.eu/en/news/news.rss",
    "https://www.epicentro.iss.it/feed/rss.asp",
    "https://www.salute.gov.it/portale/news/rssNews.jsp",
]

KEYWORDS = [
    "farmaco", "drug", "ospedale", "hospital", "SSN", "NHS",
    "AIFA", "EMA", "WHO", "ISS", "sanità", "healthcare",
    "appalto", "procurement", "gara", "fornitura", "supply",
    "carenza", "shortage", "vaccino", "vaccine", "dispositivo medico",
    "corruzione", "frode", "audit", "accreditamento", "ASL", "AO",
    "IRCCS", "DRG", "LEA", "PNRR", "salute digitale", "digital health",
]


class DataScraper:

    async def fetch_news(self) -> List[Dict]:
        """Fetch articles from health RSS feeds filtered by keywords."""
        articles = []
        for url in NEWS_SOURCES:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:20]:
                    title = entry.get("title", "")
                    summary = entry.get("summary", "")
                    text = f"{title} {summary}".lower()
                    if any(kw.lower() in text for kw in KEYWORDS):
                        articles.append({
                            "id": entry.get("id", entry.get("link", "")),
                            "title": title,
                            "summary": summary,
                            "url": entry.get("link", ""),
                            "published": entry.get("published", ""),
                            "source": feed.feed.get("title", url),
                        })
            except Exception as e:
                print(f"[scraper] RSS error {url}: {e}")
        return articles

    async def fetch_ema_medicines(self) -> List[Dict]:
        """Fetch recent EMA medicine decisions."""
        url = "https://www.ema.europa.eu/en/medicines/download-medicine-data"
        # Use public EMA search API
        api_url = "https://www.ema.europa.eu/en/medicines/field_ema_web_categories%253Aname_field/Human/ema_group_types/ema_medicine?search_api_views_fulltext=&page=0"
        results = []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                    params={
                        "db": "pubmed",
                        "term": "Italian+healthcare+system+OR+SSN+Italy+OR+AIFA+drug+approval",
                        "retmax": 15,
                        "sort": "date",
                        "retmode": "json",
                    }
                )
                data = r.json()
                ids = data.get("esearchresult", {}).get("idlist", [])
                for pmid in ids[:10]:
                    results.append({
                        "id": f"pubmed_{pmid}",
                        "title": f"PubMed article {pmid}",
                        "summary": f"Health research article PMID:{pmid}",
                        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        "published": datetime.utcnow().isoformat(),
                    })
        except Exception as e:
            print(f"[scraper] PubMed error: {e}")
        return results

    async def fetch_procurement_notices(self) -> List[Dict]:
        """Fetch public health procurement notices from TED (EU)."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    "https://ted.europa.eu/api/v3.0/notices/search",
                    params={
                        "q": "CPV:85100000 AND (Italy OR Italia)",
                        "pageNum": 1,
                        "pageSize": 10,
                        "fields": "ND,TI,PD,IA",
                    }
                )
                data = r.json()
                notices = []
                for item in data.get("results", []):
                    notices.append({
                        "id": item.get("ND", ""),
                        "title": item.get("TI", {}).get("IT", item.get("TI", {}).get("EN", "")),
                        "summary": f"Gara EU sanità: {item.get('IA', '')}",
                        "published": item.get("PD", ""),
                    })
                return notices
        except Exception as e:
            print(f"[scraper] TED procurement error: {e}")
            return []

    async def fetch_all(self) -> Dict:
        """Run all scrapers and return combined results."""
        import asyncio
        news, research, procurement = await asyncio.gather(
            self.fetch_news(),
            self.fetch_ema_medicines(),
            self.fetch_procurement_notices(),
        )
        return {
            "news": news,
            "research": research,
            "procurement": procurement,
            "fetched_at": datetime.utcnow().isoformat(),
        }
