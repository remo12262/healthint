"""Migrazione una tantum: accorpa i nodi doppi già presenti in data/seed.json.

I dati di HEALTHINT vivono in memoria sul server e sono salvati in data/seed.json
(esportati due volte al giorno da GitHub Actions): pulire il seed e ripubblicare il
servizio basta a pulire i dati. Nessuna chiamata a Claude.

Uso:
    python migrate_dedup.py            # anteprima: cosa verrebbe accorpato, nessuna scrittura
    python migrate_dedup.py --apply    # scrive il seed pulito (copia del vecchio in data/)

Lo script è idempotente: rieseguito su dati già puliti non cambia nulla.
"""
import argparse
import asyncio
import json
import os
import shutil
import sys
from datetime import datetime

import graph
from graph import GraphDB, SEED_FILE


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="scrive il seed pulito (altrimenti solo anteprima)")
    ap.add_argument("--seed", default=SEED_FILE, help="file seed da pulire")
    args = ap.parse_args()

    graph.SEED_FILE = args.seed
    db = GraphDB()
    asyncio.run(db.init())
    sources_before = {k: set(db._edge_docs(e)) for k, e in db.edges.items()}
    all_docs_before = set().union(*sources_before.values()) if sources_before else set()

    report = db.merge_duplicates()
    db.recompute_recall_risk()
    orphans = db.drop_orphan_edges()
    problems = db.validate(0)

    print(f"Nodi: {report['nodes_before']} -> {report['nodes_after']}")
    print(f"Relazioni: {report['edges_before']} -> {report['edges_after']} "
          f"(relazioni di un nodo con sé stesso eliminate: {report['self_loops_dropped']}, orfane: {orphans})")
    print(f"\nGruppi accorpati o rinominati ({len(report['groups'])}):")
    for g in sorted(report["groups"], key=lambda g: -len(g["merged"])):
        print(f"\n  {g['label']}  [{g['id']}]  <- {len(g['merged'])} nodi")
        for mid, label in g["merged"]:
            print(f"      - {label}  [{mid}]")

    # Controllo: nessuna fonte deve andare persa
    all_docs_after = set().union(*(set(db._edge_docs(e)) for e in db.edges.values())) if db.edges else set()
    lost = all_docs_before - all_docs_after
    print(f"\nFonti distinte sulle relazioni: prima {len(all_docs_before)}, dopo {len(all_docs_after)}"
          + (f" — PERSE: {sorted(lost)}" if lost else " — nessuna persa"))
    if problems:
        print("PROBLEMI:", "; ".join(problems))
        sys.exit(1)

    if not args.apply:
        print("\nAnteprima: nessun file modificato. Per scrivere: python migrate_dedup.py --apply")
        return
    backup = os.path.join(os.path.dirname(args.seed), f"seed.backup-{datetime.utcnow():%Y%m%d-%H%M%S}.json")
    shutil.copyfile(args.seed, backup)
    with open(args.seed, "w", encoding="utf-8") as f:
        json.dump(db.export(), f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"\nSeed pulito scritto in {args.seed} (copia del precedente: {backup})")


if __name__ == "__main__":
    main()
