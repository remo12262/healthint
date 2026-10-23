"""Migrazione una tantum del seed: collegamento aggiuntivo ad AIFA per i richiami FDA mondiali che citano l'Italia.

Fino al 23/10/2026 un richiamo con distribuzione "worldwide/europe/international" era collegato solo a EMA,
anche se la distribuzione nominava l'Italia. Ora (extractor.process_recalls) riceve anche la relazione
recall_<numero>_it verso AIFA. Questo script fa lo stesso per i richiami già nel grafo: legge da openFDA
la distribuzione dei richiami collegati a EMA e, se cita l'Italia, aggiunge la relazione verso AIFA.
Non toglie né modifica nessuna relazione esistente; rieseguirlo non aggiunge doppioni.

Uso (dalla cartella backend): python migrate_italy_routing.py [--dry-run]
"""
import copy
import json
import sys
import time

import httpx

from extractor import ITALY_RE

SEED = "data/seed.json"
FDA_API = {"D": "https://api.fda.gov/drug/enforcement.json", "Z": "https://api.fda.gov/device/enforcement.json"}


def distributions(numbers):
    """Campo distribution_pattern di openFDA per numero di richiamo."""
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
                    out[rec["recall_number"]] = rec.get("distribution_pattern", "")
                time.sleep(0.5)
    return out


def main(dry_run: bool):
    seed = json.load(open(SEED, encoding="utf-8"))
    edges = {e["id"]: e for e in seed["edges"]}
    ema = {k[7:]: e for k, e in edges.items() if k.startswith("recall_") and not k.endswith("_it") and e["target"] == "ema"}
    dist = distributions(ema)
    print(f"Richiami collegati a EMA: {len(ema)}; distribuzione letta da openFDA: {len(dist)}")
    missing = sorted(set(ema) - set(dist))
    if missing:
        print(f"  non trovati su openFDA (restano come sono): {missing}")
    added = []
    for n, e in ema.items():
        rid = f"recall_{n}_it"
        if rid in edges or not ITALY_RE.search(dist.get(n, "").lower()):
            continue
        new = copy.deepcopy(e)
        new["id"], new["target"] = rid, "aifa"
        seed["edges"].append(new)
        added.append(n)
    print(f"Relazioni aggiunte verso AIFA: {len(added)}")
    if dry_run:
        print("Prova: nessun file scritto")
        return
    with open(SEED, "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"Scritto {SEED}")


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
