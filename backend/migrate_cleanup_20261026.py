"""Migrazione una tantum (26/10/2026, prima del congelamento): pulizia manuale del grafo.

Toglie i nodi orfani e quelli che non sono entità reali, accorpa i doppioni (Congo,
Irkutsk, Zentiva) e traduce in italiano le etichette rimaste in inglese. Poi esegue
lo stesso percorso dell'avvio del server (merge_duplicates, ensure_nucleus, ...) per
controllare che il risultato resti stabile. Nessuna chiamata a Claude.

Uso:
    python migrate_cleanup_20261026.py            # anteprima, nessuna scrittura
    python migrate_cleanup_20261026.py --apply    # scrive il seed (copia del vecchio in data/)
"""
import argparse
import asyncio
import copy
import json
import os
import shutil
import sys
from datetime import datetime

import graph
from graph import GraphDB, SEED_FILE

# Nodi da togliere con le loro relazioni
REMOVE = {
    "gvm": "senza relazioni",
    "farmaco_orfano_nuovo": "non è un'entità (categoria di un comunicato AIFA)",
    "hiv1_terapia": "non è un'entità (categoria di un comunicato AIFA)",
    "estensioni_indicazione_pediatrico": "non è un'entità (stesso comunicato AIFA)",
    "farmaci_equivalenti": "non è un'entità (stesso comunicato AIFA)",
    "oncologia_terapia": "non è un'entità (stesso comunicato AIFA)",
    "salute_mentale_adolescenti": "non è un'entità (stesso comunicato AIFA)",
    "malattie_rare_terapia": "non è un'entità (stesso comunicato AIFA)",
    "kenya_treatment_center": "senza relazioni",
}
# Relazioni da togliere: Paracetamolo Zentiva Generics (GU 26A05440) è un altro medicinale,
# agganciato per errore a Paracetamolo Zentiva Italia; la fonte resta su aifa -> zentiva_generics
REMOVE_EDGES = {"zentiva_generics_paracetamolo_zentiva_FORNISCE"}

# Nodo che resta <- nodi accorpati, con etichetta (e descrizione) finali
MERGE = {
    "drc_health_zones": (["health_zones_drc", "north_kivu_health_zone"], "Zone sanitarie colpite – RDC",
                         "Zone sanitarie della Repubblica Democratica del Congo colpite dall'epidemia di Ebola "
                         "(virus Bundibugyo). Il numero di zone è riportato nelle singole relazioni, "
                         "con il documento OMS da cui proviene."),
    "affected_provinces_drc": (["drc_provinces_affected", "ituri_north_kivu_provinces"], "Province colpite – RDC",
                               "Province della Repubblica Democratica del Congo colpite dall'epidemia di Ebola "
                               "(virus Bundibugyo). Le province sono riportate nelle singole relazioni, "
                               "con il documento OMS da cui provengono."),
    "healthcare_settings_drc": (["health_facility_network_drc"], "Strutture sanitarie – RDC", None),
    "zentiva_italia": (["paracetamolo_zentiva"], "Zentiva Italia",
                       "Azienda farmaceutica, titolare del medicinale Paracetamolo Zentiva Italia "
                       "(autorizzazione revocata su rinuncia, Gazzetta Ufficiale del 21/10/2026)."),
    "hospital_irkutsk": (["healthcare_facility_irkutsk"], "Struttura ospedaliera – Irkutsk", None),
    "irkutsk_oblast_health": (["irkutsk_oblast_auth"], "Autorità sanitarie dell'oblast di Irkutsk", None),
    "deceased_employee": (["employee_apri"], "Dipendente APRI Irkutsk (deceduto)", None),
}

# Etichette ancora in inglese (o con il nome inglese del luogo)
RENAME = {
    "apri_irkutsk": "Istituto antipeste di Irkutsk (APRI)",
    "irkutsk_oblast": "Oblast di Irkutsk",
    "dromedary_camel_reservoir": "Dromedari (serbatoio animale)",
    "gpei": "Iniziativa globale per l'eradicazione della poliomielite (GPEI)",
    "nigeria_health": "Ministero della Salute – Nigeria",
    "nigeria_abuja_fc": "Territorio della Capitale Federale (Abuja)",
    "uganda_transit": "Punto di transito – Uganda",
    "riyadh_region": "Riad",
}
# Regioni in inglese non coperte dalla traduzione del frontend (COUNTRY_IT)
REGION = {"Congo": "Repubblica Democratica del Congo", "Irkutsk Oblast": "Federazione Russa"}


def rename(node, label):
    if node.get("label") and node["label"] != label:
        aliases = (set(node.get("aliases", [])) | {node["label"]}) - {label}
        node["aliases"] = sorted(aliases)
        node["label"] = label


def merge(db, keep, others):
    for o in others:
        db._absorb(db.nodes[keep], db.nodes.pop(o))
    for k, e in list(db.edges.items()):
        s = keep if e["source"] in others else e["source"]
        t = keep if e["target"] in others else e["target"]
        if (s, t) == (e["source"], e["target"]):
            continue
        del db.edges[k]
        if s == t:
            continue
        e = {**e, "source": s, "target": t}
        nk = k if k.startswith("recall_") else f"{s}_{t}_{e['type']}"
        e["id"] = nk
        if nk in db.edges:
            db._absorb_edge(db.edges[nk], e)
        else:
            db.edges[nk] = e


def degree(db):
    d = {nid: 0 for nid in db.nodes}
    for e in db.edges.values():
        d[e["source"]] += 1
        d[e["target"]] += 1
    return d


def startup_path(db):
    """Lo stesso percorso di main.startup()."""
    db.merge_duplicates()
    db.ensure_nucleus()
    db.recompute_recall_risk()
    db.drop_orphan_edges()


def counts(db, flags):
    """Nodi, relazioni e orfani: vista completa e vista Solo Italia (come il frontend)."""
    it = {nid for nid, (a, b) in flags.items() if a or b}
    out = {}
    for name, ids in (("completa", set(db.nodes)), ("italia", it)):
        edges = [e for e in db.edges.values() if e["source"] in ids and e["target"] in ids]
        linked = {x for e in edges for x in (e["source"], e["target"])}
        out[name] = (len(ids), len(edges), sorted(ids - linked))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--seed", default=SEED_FILE)
    args = ap.parse_args()

    graph.SEED_FILE = args.seed
    db = GraphDB()
    asyncio.run(db.init())
    nb, eb = len(db.nodes), len(db.edges)
    docs_before = set().union(*(db._edge_docs(e) for e in db.edges.values()))

    for k in REMOVE_EDGES:
        db.edges.pop(k)
    for keep, (others, label, desc) in MERGE.items():
        merge(db, keep, others)
        rename(db.nodes[keep], label)
        if desc:
            db.nodes[keep]["description"] = desc
    for nid, label in RENAME.items():
        rename(db.nodes[nid], label)
    for n in db.nodes.values():
        if n.get("region") in REGION:
            n["region"] = REGION[n["region"]]
    # Orfani rimasti (inclusi quelli da togliere esplicitamente)
    for nid in REMOVE:
        db.nodes.pop(nid)
    db.drop_orphan_edges()
    orphans = {nid: db.nodes[nid]["label"] for nid, d in degree(db).items() if d == 0}
    for nid in orphans:
        db.nodes.pop(nid)

    startup_path(db)
    after = copy.deepcopy((db.nodes, db.edges))
    startup_path(db)
    stable = after == (db.nodes, db.edges)
    problems = db.validate(nb)

    docs_after = set().union(*(db._edge_docs(e) for e in db.edges.values()))
    print(f"Nodi: {nb} -> {len(db.nodes)}   Relazioni: {eb} -> {len(db.edges)}")
    print("\nTolti:", *(f"  - {k}: {v}" for k, v in REMOVE.items()), sep="\n")
    print("Tolti perché orfani:", *(f"  - {k}: {v}" for k, v in orphans.items()), sep="\n")
    print("Accorpati:", *(f"  - {lab} [{k}] <- {', '.join(o)}" for k, (o, lab, _) in MERGE.items()), sep="\n")
    print("Rinominati:", *(f"  - {k}: {db.nodes[k].get('aliases')} -> {v}" for k, v in RENAME.items()), sep="\n")
    print(f"\nFonti perse: {sorted(docs_before - docs_after) or 'nessuna'}")
    print(f"Stabile al riavvio del server: {'sì' if stable else 'NO'}")
    c = counts(db, db._italy_flags())
    for name, (n, e, orph) in c.items():
        print(f"Vista {name}: {n} nodi, {e} relazioni, orfani: {orph or 'nessuno'}")
    who = [a for a in db.alerts.values() if a["id"].startswith("who_")]
    for a in who:
        print(f"Alert {a['id']}: {a['recommendation']}")
    if problems or not stable:
        print("PROBLEMI:", "; ".join(problems))
        sys.exit(1)

    if args.apply:
        backup = os.path.join(os.path.dirname(args.seed), f"seed.backup-{datetime.now():%Y%m%d-%H%M%S}.json")
        shutil.copy(args.seed, backup)
        with open(args.seed, encoding="utf-8") as f:
            seed = json.load(f)
        seed["nodes"], seed["edges"] = list(db.nodes.values()), list(db.edges.values())
        with open(args.seed, "w", encoding="utf-8") as f:
            json.dump(seed, f, ensure_ascii=False, indent=1)
        print(f"\nSeed scritto (copia del vecchio: {backup})")
    else:
        print("\nAnteprima: nessuna scrittura (usa --apply)")


if __name__ == "__main__":
    main()
