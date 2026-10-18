"""Nucleo fisso italiano del grafo: enti nazionali, Regioni e Province autonome, centrali acquisti.

Sono nodi sempre presenti (GraphDB.ensure_nucleus), indipendenti dalle notizie.
Ogni nodo ha il sito istituzionale come fonte; ogni relazione la norma che la
fonda (Normattiva) o il sito dell'ente. Solo dati: nessuna chiamata esterna.
"""

NORMATTIVA = "https://www.normattiva.it/uri-res/N2Ls?"
LAW = {
    "dlgs502": (NORMATTIVA + "urn:nir:stato:decreto.legislativo:1992-12-30;502",
                "D.Lgs. 30 dicembre 1992, n. 502 – Riordino della disciplina in materia sanitaria (Normattiva)"),
    "dlgs281": (NORMATTIVA + "urn:nir:stato:decreto.legislativo:1997-08-28;281",
                "D.Lgs. 28 agosto 1997, n. 281 – Conferenza Stato-Regioni (Normattiva)"),
    "dl269": (NORMATTIVA + "urn:nir:stato:decreto.legge:2003-09-30;269~art48",
              "D.L. 30 settembre 2003, n. 269, art. 48 – istituzione dell'AIFA (Normattiva)"),
    "dlgs106": (NORMATTIVA + "urn:nir:stato:decreto.legislativo:2012-06-28;106",
                "D.Lgs. 28 giugno 2012, n. 106 – riorganizzazione degli enti vigilati dal Ministero della Salute (Normattiva)"),
    "dlgs266": (NORMATTIVA + "urn:nir:stato:decreto.legislativo:1993-06-30;266",
                "D.Lgs. 30 giugno 1993, n. 266 – Agenzia per i servizi sanitari regionali (Normattiva)"),
}

# Enti nazionali: id, etichetta, nome completo, tipo, sito
NATIONAL = [
    ("minsalute", "Ministero della Salute", "Ministero della Salute", "RegulatorAgency", "https://www.salute.gov.it/"),
    ("iss", "ISS", "Istituto Superiore di Sanità", "RegulatorAgency", "https://www.iss.it/"),
    ("aifa", "AIFA", "Agenzia Italiana del Farmaco", "RegulatorAgency", "https://www.aifa.gov.it/"),
    ("agenas", "AGENAS", "Agenzia Nazionale per i Servizi Sanitari Regionali", "RegulatorAgency", "https://www.agenas.gov.it/"),
    ("conferenza_sr", "Conferenza Stato-Regioni",
     "Conferenza permanente per i rapporti tra lo Stato, le Regioni e le Province autonome di Trento e di Bolzano",
     "RegulatorAgency", "https://www.statoregioni.it/"),
    ("consip", "Consip", "Consip S.p.A. – centrale acquisti nazionale", "ProcurementBody", "https://www.consip.it/"),
]

# Regioni e Province autonome: id, etichetta, nome per il campo regione, sito, alias (nome intero),
# menzioni riconosciute nei testi (oltre a "regione <nome>")
REGIONS = [
    ("reg_abruzzo", "Regione Abruzzo", "Abruzzo", "https://www.regione.abruzzo.it/", ["abruzzo"], ["abruzzo"]),
    ("reg_basilicata", "Regione Basilicata", "Basilicata", "https://www.regione.basilicata.it/", ["basilicata"], ["basilicata"]),
    ("reg_calabria", "Regione Calabria", "Calabria", "https://www.regione.calabria.it/", ["calabria"], ["calabria"]),
    ("reg_campania", "Regione Campania", "Campania", "https://www.regione.campania.it/", ["campania"], ["campania"]),
    ("reg_emilia_romagna", "Regione Emilia-Romagna", "Emilia-Romagna", "https://www.regione.emilia-romagna.it/",
     ["emilia romagna"], ["emilia romagna"]),
    ("reg_fvg", "Regione Friuli Venezia Giulia", "Friuli Venezia Giulia", "https://www.regione.fvg.it/",
     ["friuli venezia giulia", "regione autonoma friuli venezia giulia", "fvg"], ["friuli venezia giulia"]),
    ("reg_lazio", "Regione Lazio", "Lazio", "https://www.regione.lazio.it/", ["lazio"], ["lazio"]),
    ("reg_liguria", "Regione Liguria", "Liguria", "https://www.regione.liguria.it/", ["liguria"], ["liguria"]),
    ("reg_lombardia", "Regione Lombardia", "Lombardia", "https://www.regione.lombardia.it/", ["lombardia", "lombardy"], ["lombardia"]),
    ("reg_marche", "Regione Marche", "Marche", "https://www.regione.marche.it/", ["marche"], []),
    ("reg_molise", "Regione Molise", "Molise", "https://www.regione.molise.it/", ["molise"], ["molise"]),
    ("reg_piemonte", "Regione Piemonte", "Piemonte", "https://www.regione.piemonte.it/", ["piemonte", "piedmont"], ["piemonte"]),
    ("reg_puglia", "Regione Puglia", "Puglia", "https://www.regione.puglia.it/", ["puglia", "apulia"], ["puglia"]),
    ("reg_sardegna", "Regione Sardegna", "Sardegna", "https://www.regione.sardegna.it/",
     ["sardegna", "sardinia", "regione autonoma della sardegna"], ["sardegna"]),
    ("reg_sicilia", "Regione Siciliana", "Sicilia", "https://www.regione.sicilia.it/",
     ["sicilia", "sicily", "regione sicilia", "regione siciliana", "assessorato alla salute regione sicilia",
      "assessorato della salute regione siciliana"], ["sicilia", "regione siciliana"]),
    ("reg_toscana", "Regione Toscana", "Toscana", "https://www.regione.toscana.it/", ["toscana", "tuscany"], ["toscana"]),
    ("reg_umbria", "Regione Umbria", "Umbria", "https://www.regione.umbria.it/home", ["umbria"], ["umbria"]),
    ("reg_vda", "Regione Valle d'Aosta", "Valle d'Aosta", "https://www.regione.vda.it/",
     ["valle d aosta", "aosta valley", "regione autonoma valle d aosta"], ["valle d aosta"]),
    ("reg_veneto", "Regione Veneto", "Veneto", "https://www.regione.veneto.it/", ["veneto"], ["veneto"]),
    ("pa_bolzano", "Provincia autonoma di Bolzano", "Provincia autonoma di Bolzano", "https://www.provincia.bz.it/",
     ["provincia autonoma di bolzano", "pa bolzano", "alto adige", "south tyrol", "provincia di bolzano"],
     ["provincia autonoma di bolzano", "alto adige"]),
    ("pa_trento", "Provincia autonoma di Trento", "Provincia autonoma di Trento", "https://www.provincia.tn.it/",
     ["provincia autonoma di trento", "pa trento", "provincia di trento"], ["provincia autonoma di trento"]),
]

# Principali centrali acquisti regionali per la sanità: id, etichetta, nome completo, regione, sito
PROCUREMENT = [
    ("aria_lombardia", "ARIA S.p.A.", "Azienda Regionale per l'Innovazione e gli Acquisti (Lombardia)", "reg_lombardia",
     "https://www.ariaspa.it/"),
    ("intercent_er", "Intercent-ER", "Agenzia regionale di sviluppo dei mercati telematici (Emilia-Romagna)", "reg_emilia_romagna",
     "https://intercenter.regione.emilia-romagna.it/"),
    ("soresa", "So.Re.Sa.", "Società Regionale per la Sanità (Campania)", "reg_campania", "https://www.soresa.it/"),
    ("estar", "ESTAR", "Ente di Supporto Tecnico-Amministrativo Regionale (Toscana)", "reg_toscana", "https://www.estar.toscana.it/"),
    ("azienda_zero", "Azienda Zero", "Azienda Zero (Veneto)", "reg_veneto", "https://www.azero.veneto.it/"),
    ("scr_piemonte", "SCR Piemonte", "Società di Committenza Regione Piemonte", "reg_piemonte", "https://www.scr.piemonte.it/"),
    ("arcs_fvg", "ARCS", "Azienda Regionale di Coordinamento per la Salute (Friuli Venezia Giulia)", "reg_fvg",
     "https://arcs.sanita.fvg.it/"),
]

# Alias per riconoscere questi enti quando l'AI li estrae con un altro nome (nome intero)
ALIASES = {
    "conferenza_sr": ["conferenza stato regioni", "conferenza permanente per i rapporti tra lo stato le regioni e le province autonome",
                      "conferenza stato regioni e province autonome"],
    "aria_lombardia": ["aria", "aria spa", "aria s p a", "azienda regionale per l innovazione e gli acquisti"],
    "intercent_er": ["intercent er", "intercenter", "intercent"],
    "soresa": ["so re sa", "soresa", "societa regionale per la sanita"],
    "estar": ["estar", "estar toscana"],
    "azienda_zero": ["azienda zero", "azienda zero veneto"],
    "scr_piemonte": ["scr piemonte", "societa di committenza regione piemonte"],
    "arcs_fvg": ["arcs", "azienda regionale di coordinamento per la salute"],
}
for rid, label, _, _, aliases, _ in REGIONS:
    ALIASES[rid] = [label.lower().replace("'", " ").replace("-", " ")] + \
        [f"regione {a}" for a in aliases] + aliases + [f"servizio sanitario regionale {a}" for a in aliases]

REGION_NAMES = {name for _, _, name, _, _, _ in REGIONS}
ITALY_REGION_VALUES = REGION_NAMES | {"IT", "Italia", "Italy", "Sicilia", "Lombardia"}

# Menzioni nei testi delle fonti italiane: frase normalizzata -> id
MENTIONS = {
    "ministero della salute": "minsalute", "istituto superiore di sanita": "iss", "aifa": "aifa",
    "agenzia italiana del farmaco": "aifa", "agenas": "agenas", "conferenza stato regioni": "conferenza_sr",
    "consip": "consip", "intercent er": "intercent_er", "soresa": "soresa", "so re sa": "soresa",
    "azienda zero": "azienda_zero", "scr piemonte": "scr_piemonte", "estar": "estar", "aria spa": "aria_lombardia",
}
for rid, _, _, _, aliases, mentions in REGIONS:
    for a in aliases:
        MENTIONS[f"regione {a}"] = rid
    for m in mentions:
        MENTIONS[m] = rid


def nucleus():
    """Nodi e relazioni del nucleo fisso: (nodi, relazioni)."""
    nodes, edges = [], []
    for nid, label, full, typ, site in NATIONAL:
        nodes.append({"id": nid, "label": label, "full_name": full, "type": typ, "region": "IT", "website": site})
    for rid, label, name, site, _, _ in REGIONS:
        nodes.append({"id": rid, "label": label, "full_name": label, "type": "RegionalAuthority", "region": name,
                      "website": site})
    for pid, label, full, rid, site in PROCUREMENT:
        region = next(name for r, _, name, _, _, _ in REGIONS if r == rid)
        nodes.append({"id": pid, "label": label, "full_name": full, "type": "ProcurementBody", "region": region,
                      "website": site})

    def edge(src, tgt, typ, fact, doc_url, doc_title):
        edges.append({"id": f"{src}_{tgt}_{typ}", "source": src, "target": tgt, "type": typ, "fact": fact,
                      "risk_score": 10, "source_doc": doc_url, "doc_titles": {doc_url: doc_title}, "date": None})

    edge("minsalute", "aifa", "CONTROLLA", "L'AIFA opera sotto la vigilanza del Ministero della Salute (e del MEF).", *LAW["dl269"])
    edge("minsalute", "iss", "CONTROLLA", "L'ISS è un ente vigilato dal Ministero della Salute.", *LAW["dlgs106"])
    edge("minsalute", "agenas", "CONTROLLA", "AGENAS è un ente vigilato dal Ministero della Salute.", *LAW["dlgs266"])
    for rid, label, *_ in REGIONS:
        edge("minsalute", rid, "REGOLA",
             f"{label} organizza il servizio sanitario regionale nel quadro dei livelli essenziali di assistenza nazionali.",
             *LAW["dlgs502"])
        edge(rid, "conferenza_sr", "MEMBRO_DI",
             f"{label} partecipa alla Conferenza Stato-Regioni, sede delle intese sulla sanità.", *LAW["dlgs281"])
    for pid, label, full, rid, site in PROCUREMENT:
        edge(rid, pid, "CONTROLLA", f"{label} svolge acquisti centralizzati per il servizio sanitario della regione.",
             site, f"{full} – sito istituzionale")
    return nodes, edges


# Relazioni manuali del primo avvio sostituite da quelle con fonte del nucleo
SUPERSEDED_EDGES = {"e1", "e3", "e4"}


def is_italian(node: dict) -> bool:
    """Ente italiano: regione italiana, ambito nazionale "IT" o nodo del nucleo."""
    return node.get("region") in ITALY_REGION_VALUES or bool(node.get("italy"))
