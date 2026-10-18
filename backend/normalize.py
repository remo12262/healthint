"""Normalizzazione dei nomi delle entità, senza AI.

Claude estrae dalle notizie la stessa entità con nomi diversi ("WHO", "World Health
Organization", "OMS - Organizzazione Mondiale della Sanità") e con id diversi a ogni
aggiornamento. Qui si ricava per ogni entità una chiave canonica, così che i doppioni
confluiscano in un solo nodo:

1. eventi epidemici: malattia + paese ("Bundibugyo Virus Outbreak DRC" = "Epidemia Ebola RDC 2026");
2. enti noti, per sigla o nome completo in più lingue (OMS, EMA, ECDC, AIFA, ISS, ...);
3. punti focali nazionali RSI e ministeri della salute di un paese;
4. zone sanitarie e province (per ora quelle della RDC, dove si concentrano i focolai);
5. paesi e "sistema sanitario" di un paese;
6. tutto il resto: nome senza accenti, punteggiatura e forme societarie (Inc, LLC, GmbH, ...).

resolve() restituisce l'id canonico e, per le entità note, nome, tipo e regione da usare.
"""
import re
import unicodedata
from typing import Dict, Optional

import italy

# --- Testo normalizzato -------------------------------------------------------------------

def norm(text: str) -> str:
    """Minuscolo, senza accenti né punteggiatura, spazi singoli."""
    t = unicodedata.normalize("NFKD", str(text or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = t.replace("&", " and ").replace("'", " ").replace("’", " ")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def slug(text: str) -> str:
    return norm(text).replace(" ", "_")[:48]


# Forme societarie in coda al nome: "Philips North America" = "Philips North America LLC"
CORPORATE = {"inc", "llc", "ltd", "limited", "gmbh", "sarl", "sas", "corp", "corporation", "co",
             "kk", "spa", "srl", "sa", "ag", "plc", "bv", "nv", "lp", "company", "the"}


def generic_key(label: str) -> str:
    words = norm(label).split()
    while len(words) > 1 and words[-1] in CORPORATE:
        words.pop()
    while len(words) > 1 and words[0] == "the":
        words.pop(0)
    return " ".join(words)


# --- Paesi --------------------------------------------------------------------------------

# codice -> (nome italiano, sigla breve per le etichette, alias)
COUNTRIES = {
    "cd": ("Repubblica Democratica del Congo", "RDC",
           ["democratic republic of the congo", "democratic republic of congo", "repubblica democratica del congo",
            "dr congo", "drc", "rdc", "congo"]),
    "ke": ("Kenya", "Kenya", ["kenya"]),
    "ug": ("Uganda", "Uganda", ["uganda"]),
    "ss": ("Sud Sudan", "Sud Sudan", ["south sudan", "sud sudan", "sudan del sud"]),
    "sa": ("Arabia Saudita", "Arabia Saudita",
           ["kingdom of saudi arabia", "saudi arabia", "arabia saudita", "regno dell arabia saudita", "ksa"]),
    "ru": ("Federazione Russa", "Russia", ["russian federation", "federazione russa", "russia"]),
    "it": ("Italia", "Italia", ["italy", "italia", "repubblica italiana"]),
    "us": ("Stati Uniti", "USA", ["united states of america", "united states", "stati uniti", "usa"]),
    "cn": ("Cina", "Cina", ["people s republic of china", "china", "cina"]),
    "in": ("India", "India", ["india"]),
    "bd": ("Bangladesh", "Bangladesh", ["bangladesh"]),
    "rw": ("Ruanda", "Ruanda", ["rwanda", "ruanda"]),
    "bi": ("Burundi", "Burundi", ["burundi"]),
    "tz": ("Tanzania", "Tanzania", ["united republic of tanzania", "tanzania"]),
    "et": ("Etiopia", "Etiopia", ["ethiopia", "etiopia"]),
}
# Alias più lunghi per primi: "south sudan" prima di "sudan", "democratic republic of the congo" prima di "congo"
_COUNTRY_ALIASES = sorted(((a, cc) for cc, (_, _, al) in COUNTRIES.items() for a in al), key=lambda x: -len(x[0]))


def find_country(text: str) -> Optional[str]:
    t = f" {norm(text)} "
    for alias, cc in _COUNTRY_ALIASES:
        if f" {alias} " in t:
            return cc
    return None


def country_of(label: str, region: Optional[str]) -> Optional[str]:
    """Paese nominato nell'etichetta o, in mancanza, nella regione."""
    return find_country(label) or (find_country(region) if region else None)


# --- Enti noti ----------------------------------------------------------------------------

# id -> etichetta breve (per il grafo), nome completo, tipo, regione, alias
# (gli alias si confrontano con il nome normalizzato intero)
AGENCIES = {
    "who": ("OMS", "Organizzazione Mondiale della Sanità (WHO)", "RegulatorAgency", "Globale",
            ["who", "oms", "world health organization", "world health organisation",
             "organizzazione mondiale della sanita", "who headquarters", "who geneva", "who hq",
             "organisation mondiale de la sante"]),
    "who_afro": ("OMS – Ufficio per l'Africa", "Ufficio Regionale dell'OMS per l'Africa (WHO AFRO)", "RegulatorAgency", "Africa",
                 ["who afro", "who regional office for africa", "ufficio regionale per l africa",
                  "who ufficio regionale per l africa", "oms ufficio regionale per l africa"]),
    "who_emergency_committee": ("Comitato di emergenza OMS", "Comitato di emergenza del Regolamento sanitario internazionale (OMS)",
                                "RegulatorAgency", "Globale",
                                ["who emergency committee", "emergency committee who", "ihr emergency committee",
                                 "comitato di emergenza dell oms", "comitato di emergenza oms"]),
    "ema": ("EMA", "Agenzia europea per i medicinali (European Medicines Agency)", "RegulatorAgency", "EU",
            ["ema", "european medicines agency", "agenzia europea per i medicinali", "emea"]),
    "ecdc": ("ECDC", "Centro europeo per la prevenzione e il controllo delle malattie", "RegulatorAgency", "EU",
             ["ecdc", "european centre for disease prevention and control",
              "european center for disease prevention and control",
              "centro europeo per la prevenzione e il controllo delle malattie"]),
    "efsa": ("EFSA", "Autorità europea per la sicurezza alimentare", "RegulatorAgency", "EU",
             ["efsa", "european food safety authority", "autorita europea per la sicurezza alimentare"]),
    "hera": ("HERA", "Autorità europea per la preparazione e la risposta alle emergenze sanitarie", "RegulatorAgency", "EU",
             ["hera", "dg hera", "health emergency preparedness and response authority",
              "health emergency preparedness and response"]),
    "aifa": ("AIFA", "Agenzia Italiana del Farmaco", "RegulatorAgency", "IT",
             ["aifa", "agenzia italiana del farmaco", "italian medicines agency"]),
    "iss": ("ISS", "Istituto Superiore di Sanità", "RegulatorAgency", "IT",
            ["iss", "istituto superiore di sanita", "italian national institute of health"]),
    "minsalute": ("Ministero della Salute", "Ministero della Salute (Italia)", "RegulatorAgency", "IT",
                  ["ministero della salute", "italian ministry of health", "ministry of health italy",
                   "ministero della salute italiano", "ministero della salute italia"]),
    "agenas": ("AGENAS", "Agenzia Nazionale per i Servizi Sanitari Regionali", "RegulatorAgency", "IT",
               ["agenas", "agenzia nazionale per i servizi sanitari regionali"]),
    "consip": ("Consip", "Consip S.p.A. – centrale acquisti nazionale", "ProcurementBody", "IT", ["consip"]),
    "fda": ("FDA (USA)", "Food and Drug Administration (Stati Uniti)", "RegulatorAgency", "US",
            ["fda", "us fda", "food and drug administration", "u s food and drug administration",
             "us food and drug administration"]),
    "cdc": ("CDC (USA)", "Centers for Disease Control and Prevention (Stati Uniti)", "RegulatorAgency", "US",
            ["cdc", "us cdc", "centers for disease control and prevention"]),
    "africa_cdc": ("Africa CDC", "Africa Centres for Disease Control and Prevention", "RegulatorAgency", "Africa",
                   ["africa cdc", "africa centres for disease control and prevention",
                    "africa centers for disease control and prevention"]),
}
_AGENCY_ALIAS = {a: aid for aid, (*_, al) in AGENCIES.items() for a in al}

# Nucleo fisso italiano (Regioni, Conferenza Stato-Regioni, centrali acquisti): stessi criteri degli enti noti
_ITALY_NODES = {n["id"]: n for n in italy.nucleus()[0]}
for _nid, _aliases in italy.ALIASES.items():
    for _a in _aliases:
        _AGENCY_ALIAS.setdefault(norm(_a), _nid)


def match_agency(label: str) -> Optional[str]:
    """Ente noto se il nome intero, o ciascuna parte di "SIGLA - Nome esteso" / "Nome (SIGLA)", è un suo alias."""
    raw = str(label or "")
    whole = norm(raw)
    if whole in _AGENCY_ALIAS:
        return _AGENCY_ALIAS[whole]
    parts = [norm(p) for p in re.split(r"\s+[-–—]\s+|[()]", raw) if norm(p)]
    ids = {_AGENCY_ALIAS.get(p) for p in parts}
    if len(parts) > 1 and len(ids) == 1 and None not in ids:
        return ids.pop()
    return None


# --- Eventi epidemici ---------------------------------------------------------------------

DISEASES = {
    "ebola": ("Ebola", ["ebola", "bundibugyo", "evd", "bdbv"]),
    "marburg": ("Marburg", ["marburg"]),
    "mers": ("MERS-CoV", ["mers", "mers cov", "middle east respiratory syndrome"]),
    "cholera": ("colera", ["cholera", "colera"]),
    "mpox": ("mpox", ["mpox", "monkeypox", "vaiolo delle scimmie"]),
    "avian_flu": ("influenza aviaria", ["avian influenza", "influenza aviaria", "h5n1", "h5n6", "h7n9", "bird flu"]),
    "plague": ("peste", ["plague", "peste", "yersinia pestis"]),
    "dengue": ("dengue", ["dengue"]),
    "polio": ("poliomielite", ["polio", "poliomyelitis", "poliomielite", "cvdpv2", "poliovirus"]),
    "measles": ("morbillo", ["measles", "morbillo"]),
    "nipah": ("Nipah", ["nipah"]),
    "yellow_fever": ("febbre gialla", ["yellow fever", "febbre gialla"]),
    "chikungunya": ("chikungunya", ["chikungunya"]),
    "west_nile": ("West Nile", ["west nile"]),
    "anthrax": ("antrace", ["anthrax", "antrace"]),
}
EVENT_WORDS = ["outbreak", "epidemic", "epidemia", "focolaio", "focolai", "virus disease", "malattia da virus",
               "emergency", "emergenza", "cases", "casi", "infection", "infezione", "virus", "disease", "malattia"]


def find_disease(text: str) -> Optional[str]:
    t = f" {norm(text)} "
    for did, (_, words) in DISEASES.items():
        if any(f" {w} " in t for w in words):
            return did
    return None


def event_id(disease: str, cc: Optional[str]) -> str:
    return f"evt_{disease}_{cc}" if cc else f"evt_{disease}"


def event_label(disease: str, cc: Optional[str]) -> str:
    name = DISEASES[disease][0]
    return f"Epidemia di {name} – {COUNTRIES[cc][1]}" if cc else f"Epidemia di {name}"


def _is_event(label: str, etype: str) -> bool:
    t = f" {norm(label)} "
    if etype in ("EpidemicEvent", "HealthEvent", "HealthThreat"):
        return True
    return any(f" {w} " in t for w in EVENT_WORDS)


# --- Province e zone sanitarie (RDC) ------------------------------------------------------

PROVINCES_CD = {
    "bas_uele": ("Bas-Uélé", ["bas uele", "bas uelle", "bas uele province"]),
    "haut_uele": ("Haut-Uélé", ["haut uele", "haut uelle"]),
    "ituri": ("Ituri", ["ituri"]),
    "nord_kivu": ("Nord Kivu", ["north kivu", "nord kivu"]),
    "sud_kivu": ("Sud Kivu", ["south kivu", "sud kivu"]),
    "tshopo": ("Tshopo", ["tshopo"]),
    "sud_ubangi": ("Sud-Ubangi", ["sud ubangi", "south ubangi"]),
    "kinshasa": ("Kinshasa", ["kinshasa"]),
    "equateur": ("Équateur", ["equateur", "equator"]),
    "kasai": ("Kasai", ["kasai"]),
}
_PROVINCE_ALIAS = {a: pid for pid, (_, al) in PROVINCES_CD.items() for a in al}
# Parole che accompagnano il nome di una provincia senza cambiarne il significato
PLACE_NOISE = {"provincia", "province", "provincial", "region", "regione", "zone", "zona", "zones",
               "health", "sanitaria", "sanitarie", "hz", "di", "del", "della", "dell", "de", "du", "of", "the",
               "drc", "rdc", "congo", "democratic", "republic", "repubblica", "democratica"}


def match_province(label: str) -> Optional[str]:
    words = [w for w in norm(label).split() if w not in PLACE_NOISE]
    return _PROVINCE_ALIAS.get(" ".join(words))


def match_health_zone(label: str) -> Optional[str]:
    """ "Kayna Health Zone - North Kivu", "Zona Sanitaria di Buta" -> nome della zona ("Kayna", "Buta")."""
    head = re.split(r"\s+[-–—,]\s+", str(label or "").strip())[0]
    m = (re.fullmatch(r"(.+?)\s+health\s+zone", head, re.I)
         or re.fullmatch(r"zona\s+sanitaria\s+(?:di\s+|del\s+|della\s+)?(.+)", head, re.I))
    if not m or match_province(m.group(1)):
        return None
    return m.group(1).strip()


# --- Paesi e ministeri --------------------------------------------------------------------

COUNTRY_NOISE = r"(?:health system|healthcare system|health authority|health authorities|sistema sanitario(?: nazionale)?|national health system|autorita sanitarie?)"


def match_country_node(label: str) -> Optional[str]:
    """ "Kenya", "Kenya - Health System", "Healthcare System - DRC" -> paese."""
    t = norm(label)
    t = re.sub(rf"^{COUNTRY_NOISE} (?:of |del |della |dell )?", "", t)
    t = re.sub(rf" {COUNTRY_NOISE}$", "", t)
    for alias, cc in _COUNTRY_ALIASES:
        if t == alias:
            return cc
    return None


MINISTRY = r"(?:ministero della salute|ministry of health|health ministry|ministere de la sante|moh)"
NFP = r"(?:national focal point|punto focale nazionale|nfp)"


# --- Risoluzione --------------------------------------------------------------------------

def resolve(label: str, etype: str = "", region: Optional[str] = None, events: Optional[Dict[str, str]] = None) -> Dict:
    """Chiave canonica di un'entità.

    Restituisce {"id": ..., "key": ...} e, per le entità riconosciute, anche "label",
    "type" e "region" canonici. events: eventi già noti {id: malattia}, per agganciare
    un evento senza paese all'unico evento della stessa malattia.
    """
    t = norm(label)

    agency = match_agency(label)
    if agency in AGENCIES:
        name, full, typ, reg, _ = AGENCIES[agency]
        return {"id": agency, "key": f"agency:{agency}", "label": name, "type": typ, "region": reg, "full_name": full}
    if agency:
        n = _ITALY_NODES[agency]
        return {"id": agency, "key": f"agency:{agency}", "label": n["label"], "type": n["type"], "region": n["region"],
                "full_name": n["full_name"]}

    disease = find_disease(label)
    if disease and _is_event(label, etype):
        cc = country_of(label, region)
        if not cc and events:
            same = [eid for eid, d in events.items() if d == disease]
            if len(same) == 1:
                eid = same[0]
                return {"id": eid, "key": f"event:{eid}", "type": "EpidemicEvent", "disease": disease}
        eid = event_id(disease, cc)
        return {"id": eid, "key": f"event:{eid}", "label": event_label(disease, cc), "type": "EpidemicEvent",
                "region": COUNTRIES[cc][0] if cc else None, "disease": disease}

    if re.search(rf"\b{NFP}\b", t):
        cc = country_of(label, region)
        if cc:
            return {"id": f"nfp_{cc}", "key": f"nfp:{cc}", "label": f"Punto focale nazionale RSI – {COUNTRIES[cc][0]}",
                    "type": "RegulatorAgency", "region": COUNTRIES[cc][0]}

    if re.search(rf"\b{MINISTRY}\b", t):
        cc = country_of(label, region)
        if cc and cc != "it":
            return {"id": f"moh_{cc}", "key": f"moh:{cc}", "label": f"Ministero della Salute – {COUNTRIES[cc][0]}",
                    "type": "RegulatorAgency", "region": COUNTRIES[cc][0]}

    hz = match_health_zone(label)
    if hz:
        hid = "hz_" + slug(hz)
        return {"id": hid, "key": f"hz:{hid}", "label": f"Zona sanitaria di {hz}", "type": "HospitalNetwork"}

    prov = match_province(label)
    if prov and (country_of(label, region) in (None, "cd")):
        return {"id": f"prov_cd_{prov}", "key": f"prov:cd:{prov}", "label": f"Provincia di {PROVINCES_CD[prov][0]} (RDC)",
                "type": "RegionalAuthority", "region": COUNTRIES["cd"][0]}

    cc = match_country_node(label)
    if cc:
        return {"id": f"country_{cc}", "key": f"country:{cc}", "label": COUNTRIES[cc][0],
                "type": "RegionalAuthority", "region": COUNTRIES[cc][0]}

    key = generic_key(label)
    return {"id": slug(key) or "entita", "key": f"name:{key}"}
