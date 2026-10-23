"""Migrazione una tantum del seed: record openFDA integrali e provenienza delle stime dell'AI.

Non cambia nessun punteggio: aggiunge solo dati di origine.

1. A ogni relazione di richiamo (recall_*) senza "record" si aggiunge il record openFDA
   integrale, scaricato per numero di richiamo (a blocchi, una volta sola).
2. A ogni nodo con punteggio stimato dall'AI si aggiungono, se ricostruibili:
   - risk_doc: documento da cui deriva la stima;
   - risk_doc_date: data di pubblicazione del documento (API OMS o data delle fonti italiane);
   - risk_assigned_at: quando il punteggio attuale è stato assegnato.
   La data di assegnazione è quella dell'aggiornamento da cui il punteggio non è più cambiato,
   cercata in tutta la cronologia git del seed (anche prima della deduplicazione, per nome o alias).
   Il documento si ricava dai documenti analizzati in quell'aggiornamento (processed_docs, dal 18/10);
   se non basta, dall'unico documento delle sue relazioni o dalla relazione con lo stesso punteggio.
   Altrimenti resta senza documento. La data del documento viene dall'API OMS, dall'indirizzo della
   Gazzetta Ufficiale o dalla pagina del documento (ISS, AIFA).

Uso (dalla cartella backend, nel clone git): python migrate_provenance.py [--dry-run]
"""
import json
import re
import subprocess
import sys
import time

import httpx

SEED = "data/seed.json"
WHO_API = "https://www.who.int/api/news/diseaseoutbreaknews"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
FDA_API = {"D": "https://api.fda.gov/drug/enforcement.json", "Z": "https://api.fda.gov/device/enforcement.json"}


def git(*args) -> str:
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout.decode("utf-8")


def history():
    """Tutte le versioni del seed nella cronologia git, dalla più vecchia."""
    snaps = []
    for c in git("log", "--reverse", "--format=%h", "HEAD", "--", SEED).split():
        try:
            snaps.append(json.loads(git("show", f"{c}:backend/{SEED}")))
        except (subprocess.CalledProcessError, ValueError):
            pass
    return snaps


def score_in(snap, node):
    """Punteggio del nodo in una versione del seed: per id o, prima della deduplicazione, per nome o alias."""
    names = {node["label"].lower()} | {a.lower() for a in node.get("aliases", [])}
    m = [x for x in snap["nodes"] if x["id"] == node["id"] or x.get("label", "").lower() in names]
    return max((x.get("risk_score", 0) for x in m), default=None)


def fetch_records(numbers):
    """Record openFDA integrali per numero di richiamo: {numero: record}."""
    out = {}
    with httpx.Client(timeout=60) as client:
        for prefix, url in FDA_API.items():
            todo = sorted(n for n in numbers if n.startswith(prefix + "-"))
            for i in range(0, len(todo), 25):
                block = todo[i:i + 25]
                r = client.get(url, params={"search": "recall_number:(" + " ".join(f'"{n}"' for n in block) + ")",
                                            "limit": 100})
                r.raise_for_status()
                for rec in r.json().get("results", []):
                    out[rec["recall_number"]] = rec
                time.sleep(0.5)
    return out


def who_dates(doc_ids):
    """Data di pubblicazione delle notizie OMS: {UrlName: AAAA-MM-GG}."""
    out = {}
    with httpx.Client(timeout=60) as client:
        for d in sorted(doc_ids):
            r = client.get(WHO_API, params={"$filter": f"UrlName eq '{d}' or DonId eq '{d}'",
                                            "$select": "UrlName,PublicationDateAndTime"})
            if r.status_code == 200 and r.json().get("value"):
                out[d] = r.json()["value"][0]["PublicationDateAndTime"][:10]
            time.sleep(0.3)
    return out


def page_dates(urls):
    """Data di pubblicazione dei documenti italiani: dall'indirizzo (Gazzetta) o dalla pagina (ISS, AIFA)."""
    out = {}
    with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": BROWSER_UA}) as client:
        for u in sorted(urls):
            m = re.search(r"gazzettaufficiale\.it/eli/id/(\d{4})/(\d{2})/(\d{2})/", u)
            if m:
                out[u] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                continue
            if not re.search(r"//www\.(iss|aifa)\.gov?\.?it/|//www\.iss\.it/", u):
                continue
            try:
                text = re.sub(r"<[^>]+>", " ", client.get(u).text)
            except httpx.HTTPError:
                continue
            m = re.search(r"(\d{1,2})/(\d{1,2})/(20\d{2})", text)
            if m:
                out[u] = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
            time.sleep(0.3)
    return out


def main(dry_run: bool):
    snaps = history()
    seed = json.load(open(SEED, encoding="utf-8"))
    assert seed["data_updated_at"] == snaps[-1]["data_updated_at"], "il seed su disco non è l'ultimo della cronologia git"

    # 1. Record openFDA
    # Un richiamo può avere due relazioni (EMA e AIFA: recall_<n> e recall_<n>_it), stesso record
    edges = {e["id"]: e for e in seed["edges"]}
    todo = [e for k, e in edges.items() if k.startswith("recall_") and not e.get("record")]
    missing = sorted({e.get("source_doc") for e in todo if e.get("source_doc")})
    records = fetch_records(missing)
    for e in todo:
        if e.get("source_doc") in records:
            e["record"] = records[e["source_doc"]]
    print(f"Record openFDA: {len(records)} recuperati su {len(missing)} richiami senza record ({len(todo)} relazioni)")
    lost = sorted(set(missing) - set(records))
    if lost:
        print(f"  non trovati su openFDA: {lost}")

    # 2. Provenienza delle stime dell'AI
    docs_of, rel_score = {}, {}
    doc_dates = {}
    for e in seed["edges"]:
        docs = [d for d in [e.get("source_doc")] + list(e.get("source_docs") or []) if d]
        if e.get("type") == "COMUNICA_SU":
            for d in docs:
                if e.get("date"):
                    doc_dates.setdefault(d, e["date"])
            continue
        if e["id"].startswith("recall_"):
            continue
        for end in (e["source"], e["target"]):
            for d in docs:
                docs_of.setdefault(end, set()).add(d)
                rel_score[(end, d)] = max(rel_score.get((end, d), 0), e.get("risk_score", 0))
    for s in (seed.get("signals") or {}).get("italy", []):
        if s.get("url") and s.get("date"):
            doc_dates.setdefault(s["url"], s["date"])

    methods = {}
    ai_nodes = [n for n in seed["nodes"] if (n.get("risk_basis") or "").startswith("Stima dell'AI")]
    for n in ai_nodes:
        if n.get("risk_doc"):
            methods["già presente"] = methods.get("già presente", 0) + 1
            continue
        # Primo aggiornamento da cui il punteggio attuale non è più cambiato
        k = len(snaps) - 1
        while k > 0 and score_in(snaps[k - 1], n) == n["risk_score"]:
            k -= 1
        mine = docs_of.get(n["id"], set())
        doc, method = None, None
        if k > 0:
            new = set(snaps[k].get("processed_docs") or []) - set(snaps[k - 1].get("processed_docs") or [])
            cand = sorted(new & mine)
            if cand:
                doc, method = cand[-1], "cronologia"
            n["risk_assigned_at"] = snaps[k].get("data_updated_at") or snaps[k].get("exported_at")
        else:
            n["risk_assigned_at"] = n.get("created_at")
        if not doc and len(mine) == 1:
            doc, method = next(iter(mine)), "unico documento"
        if not doc:
            same = sorted(d for d in mine if rel_score.get((n["id"], d)) == n["risk_score"])
            if len(same) == 1:
                doc, method = same[0], "relazione con lo stesso punteggio"
        if doc:
            n["risk_doc"] = doc
        methods[method or "nessun documento"] = methods.get(method or "nessun documento", 0) + 1

    docs = {n["risk_doc"] for n in ai_nodes if n.get("risk_doc")}
    doc_dates.update(who_dates({d for d in docs if not d.startswith("http")}))
    doc_dates.update(page_dates({d for d in docs if d.startswith("http") and d not in doc_dates}))
    dated = 0
    for n in ai_nodes:
        if n.get("risk_doc") and not n.get("risk_doc_date") and doc_dates.get(n["risk_doc"]):
            n["risk_doc_date"] = doc_dates[n["risk_doc"]]
        dated += bool(n.get("risk_doc_date"))
    print(f"Stime dell'AI: {len(ai_nodes)}; documento ricavato da: {methods}; con data del documento: {dated}")

    if dry_run:
        print("Prova: nessun file scritto")
        return
    with open(SEED, "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"Scritto {SEED}")


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
