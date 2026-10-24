import anthropic
import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from limits import try_consume_ai_call
import costs
import italy
import normalize

# Parole che segnalano un rischio nei testi delle fonti italiane (inizio di parola, testo normalizzato)
RISK_WORDS_IT = ["carenz", "ritir", "richiam", "revoc", "sospens", "allert", "focola", "epidemi", "emergenz",
                 "casi confermati", "decessi", "contraffa", "infezion", "west nile", "dengue", "morbillo"]

# Italia citata nella distribuzione di un richiamo FDA, senza distinguere maiuscole e minuscole:
# "Italy", "ITALY", "Italy/San Marino", "Italia"
ITALY_RE = re.compile(r"\bital(y|ia|ian)\b", re.IGNORECASE)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


class AIError(Exception):
    """Chiamata a Claude non riuscita o risposta inutilizzabile."""

SYSTEM_PROMPT = """Sei un sistema di intelligence per il sistema sanitario italiano ed europeo.
Il tuo compito è estrarre entità e relazioni da testi per costruire un knowledge graph sanitario.

Tipi di entità:
- HospitalNetwork: aziende ospedaliere, ASL, AO, IRCCS, policlinici
- PharmaCompany: aziende farmaceutiche, produttori dispositivi medici
- RegulatorAgency: AIFA, EMA, ISS, Ministero della Salute, AGENAS, WHO, ECDC
- RegionalAuthority: regioni, assessorati alla salute
- ProcurementBody: centrali acquisto (CONSIP, INTERCENT-ER, SORESA, ESTAR)
- ResearchInstitute: istituti di ricerca, università mediche
- Person: direttori generali, ministri, primari, dirigenti
- PrivateGroup: gruppi sanitari privati (Humanitas, GVM, Banca Medica)
- InsuranceBody: enti mutualistici, fondi sanitari integrativi

Tipi di relazione:
- FORNISCE: A fornisce farmaci/servizi a B
- CONTROLLA: A controlla/supervisiona B
- FINANZIA: A finanzia B
- ACCREDITA: A accredita B
- COLLABORA_CON: A collabora con B
- RISCHIO_PER: A rappresenta un rischio per B
- MEMBRO_DI: A è membro di B
- REGOLA: A regola B
- VINCE_APPALTO: A vince appalto da B
- INDAGA_SU: A indaga su B

Per ogni relazione calcola un risk_score da 0 a 100:
- 0-30: basso rischio
- 31-60: rischio moderato
- 61-80: rischio alto
- 81-100: rischio critico

Rischio alto se coinvolge: focolai epidemici attivi, carenze farmaci, frodi appalti,
conflitti di interesse, infiltrazioni criminalità organizzata, anomalie nei DRG, mancato rispetto LEA.

Rispondi SOLO con JSON valido, nessun testo extra."""

EXTRACT_PROMPT = """Analizza questo testo ed estrai entità e relazioni dal sistema sanitario.

Testo:
{text}

Rispondi con questo JSON esatto:
{{
  "entities": [
    {{
      "id": "slug_univoco",
      "label": "Nome Entità",
      "type": "TipoEntità",
      "region": "Sicilia/Lombardia/EU/etc o null",
      "description": "breve descrizione",
      "risk_score": 0
    }}
  ],
  "relations": [
    {{
      "source": "id_entità_1",
      "target": "id_entità_2",
      "type": "TIPO_RELAZIONE",
      "fact": "descrizione concisa della relazione",
      "risk_score": 0,
      "date": "YYYY-MM o null"
    }}
  ]
}}

Sii sintetico: al massimo 10 entità e 12 relazioni (le più importanti), "description" e "fact" in una frase breve (massimo 20 parole)."""

# Token di risposta: con un tetto basso le notizie OMS lunghe venivano troncate
EXTRACT_MAX_TOKENS = 4000
ALERT_MAX_TOKENS = 6000
# Dati passati al modello per ciascuna chiamata degli alert
ALERT_MAX_ITEMS = 8

ALERT_PROMPT = """Genera alert per chi lavora nel Servizio Sanitario Nazionale italiano a partire da questi record.

RECORD:
{data}

REGOLA GENERALE, con precedenza su ogni altra indicazione: ogni affermazione di fatto deve essere riconducibile
a un campo di uno dei record qui sopra. Dove il record non dice una cosa, non la scrivi. Non ampliare mai la
portata di un dato: non generalizzare il tipo di prodotto, non dedurre reparti, setting di cura, popolazioni di
pazienti, aree geografiche, numeri, date o urgenze che il record non nomina.

Descrizione e impatto per l'Italia li compone il sistema con il testo del record tra virgolette: tu scrivi solo
le chiavi qui sotto.
{rules}

Genera un alert per ciascun record, uno solo per record. Per ogni alert:
- "source_id": l'id esatto del record da cui nasce (uno solo);
- "title": al massimo 12 parole, solo fatti scritti nel record;
- "severity": CRITICAL|HIGH|MEDIUM|LOW;
- "italy_relevance": ALTA|MEDIA|BASSA|NESSUNA;
- "recommendation": al massimo 30 parole, verifiche concrete che usano solo i campi del record, senza nominare
  reparti, esami, setting o popolazioni che il record non nomina;
Rispondi SOLO con JSON valido: una lista di oggetti con queste chiavi."""

ALERT_RULES_RECALLS = """I record sono richiami FDA di farmaci e dispositivi con l'Italia nella distribuzione.
- Nel titolo usa il nome del prodotto come è scritto in product_description, non una categoria più ampia.
- In "recommendation" indica di verificare la presenza del prodotto con i codici del campo code_info."""

ALERT_RULES_WHO = """I record sono le notizie OMS Disease Outbreak News più recenti, una per evento: usa solo il campo summary.
- Aggiungi la chiave "quotes": una o due frasi del summary copiate identiche, carattere per carattere e senza
  tradurle, che contengono i fatti principali. Il sistema scarta l'alert se una frase non è nel summary."""

# Impatto per l'Italia composto dal sistema: solo ciò che il record dice
ITALY_IMPACT_RECALL = "La distribuzione indicata nel record FDA (campo distribution_pattern) include l'Italia."
ITALY_IMPACT_WHO = "Il documento OMS non nomina l'Italia."
QUOTE_CHARS = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})


class EntityExtractor:

    def _make_slug(self, text: str) -> str:
        return re.sub(r'[^a-z0-9_]', '', text.lower().replace(' ', '_').replace('-', '_'))[:32]

    def process_recalls(self, recalls: List[Dict]) -> Dict:
        """Convert OpenFDA enforcement recalls directly into graph entities (no Claude required).

        One PharmaCompany node per unique recalling firm; edges to AIFA or EMA
        based on distribution pattern. DB upsert keeps the max risk score, so
        multiple recalls from the same firm collapse to a single high-risk node.
        """
        entities: Dict[str, Dict] = {}
        relations: List[Dict] = []

        for recall in recalls:
            firm = recall.get("recalling_firm", "").strip()
            if not firm or len(firm) < 3:
                continue

            risk_score = recall.get("risk_score", 40)
            firm_slug = self._make_slug(firm)
            product_type = recall.get("product_type", "drug")
            product_label = "farmaceutica" if product_type == "drug" else "dispositivi medici"

            if firm_slug not in entities:
                entities[firm_slug] = {
                    "id": firm_slug,
                    "label": firm,
                    "type": "PharmaCompany",
                    "region": recall.get("country", "") or None,
                    "description": (
                        f"Azienda {product_label} con recall in Italia/UE. "
                        f"Prodotto: {recall.get('product_description', '')[:120]}"
                    ),
                    "risk_score": 0,
                }
            entities[firm_slug]["risk_score"] = max(entities[firm_slug]["risk_score"], risk_score)

            # Distribuzione europea o mondiale: EMA. Italia citata nella distribuzione: anche AIFA,
            # come collegamento aggiuntivo (un richiamo mondiale riguarda entrambe le autorità).
            # Senza nessuna delle due indicazioni: AIFA, come prima
            dist = recall.get("distribution_pattern", "").lower()
            worldwide = any(kw in dist for kw in ("europe", "worldwide", "international"))
            targets = (["ema"] if worldwide else []) + (["aifa"] if ITALY_RE.search(dist) or not worldwide else [])

            classification = recall.get("classification", "")
            reason = recall.get("reason_for_recall", "")[:120]
            recall_id = recall.get("id", "")

            # Una relazione per richiamo e autorità: un nuovo richiamo di un'azienda già nota resta visibile.
            # La prima ha id recall_<numero>; quella aggiuntiva verso AIFA recall_<numero>_it
            rd = recall.get("report_date", "")
            for i, target in enumerate(targets):
                relations.append({
                    "id": (f"recall_{recall_id}" + ("_it" if i else "")) if recall_id else None,
                    "source": firm_slug,
                    "target": target,
                    "type": "RISCHIO_PER",
                    "fact": f"[{classification}] {recall_id}: {reason}",
                    "risk_score": risk_score,
                    "source_doc": recall_id,
                    "date": f"{rd[:4]}-{rd[4:6]}-{rd[6:8]}" if len(rd) == 8 else None,
                    "record": recall.get("raw"),
                })

        return {"entities": list(entities.values()), "relations": relations}

    def process_italy(self, items: List[Dict]) -> List[Dict]:
        """Atti e comunicati delle fonti italiane collegati ai nodi del nucleo fisso (senza Claude).

        Relazione COMUNICA_SU dall'ente che pubblica a ogni ente del nucleo citato nel testo
        (Regioni, Ministero, ISS, AIFA, AGENAS, centrali acquisti), con il documento come fonte.
        """
        relations = []
        for it in items:
            pub = it.get("publisher")
            text = f" {normalize.norm(it.get('title', '') + ' ' + it.get('summary', ''))} "
            targets = {nid for phrase, nid in italy.MENTIONS.items() if f" {phrase} " in text} - {pub}
            if not pub or not targets:
                continue
            risky = any(f" {w}" in text for w in RISK_WORDS_IT)
            title = it.get("title", "")
            subject = (it.get("summary") or "")[:220] if it.get("source") == "Gazzetta Ufficiale" else ""
            for t in sorted(targets):
                relations.append({
                    "source": pub, "target": t, "type": "COMUNICA_SU",
                    "fact": f"{title}{': ' + subject if subject else ''}"[:300],
                    "risk_score": 40 if risky else 15,
                    "source_doc": it["url"] if it.get("url", "").startswith("http") else it.get("id", ""),
                    "doc_titles": {it.get("url") or it.get("id"): f"{it.get('source')} – {title}"},
                    "date": it.get("published"),
                })
        return relations

    async def _ask(self, prompt: str, max_tokens: int, system: Optional[str] = None) -> str:
        """Chiama Claude (senza ricerca web) e restituisce il testo della risposta.

        Solleva AIError se il tetto giornaliero è raggiunto o la chiamata fallisce.
        """
        if not try_consume_ai_call():
            raise AIError("tetto giornaliero di chiamate AI raggiunto")
        kwargs = {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        try:
            # Il client è sincrono: lo si esegue in un thread per non bloccare il server
            message = await asyncio.to_thread(client.messages.create, **kwargs)
        except anthropic.APIError as e:
            raise AIError(f"errore API Anthropic: {e}") from e
        costs.record(kwargs["model"], message, "healthint")
        if message.stop_reason == "max_tokens":
            raise AIError("risposta troncata (max_tokens)")
        return "".join(b.text for b in message.content if getattr(b, "type", "") == "text")

    @staticmethod
    def _parse_json(raw: str):
        """Primo valore JSON nel testo, anche se racchiuso in ```json ... ``` o preceduto da testo."""
        starts = [i for i in (raw.find("["), raw.find("{")) if i >= 0]
        if not starts:
            raise AIError(f"nessun JSON nella risposta: {raw[:200]!r}")
        try:
            value, _ = json.JSONDecoder().raw_decode(raw[min(starts):])
        except json.JSONDecodeError as e:
            raise AIError(f"JSON non valido ({e}): {raw[:200]!r}") from e
        return value

    async def extract(self, text: str, source_id: str = "") -> Dict:
        """Estrae entità e relazioni da un testo. In caso di errore restituisce la chiave "error"."""
        if not text or len(text.strip()) < 50:
            return {"entities": [], "relations": []}
        try:
            raw = await self._ask(EXTRACT_PROMPT.format(text=text[:3000]), EXTRACT_MAX_TOKENS, SYSTEM_PROMPT)
            result = self._parse_json(raw)
            if not isinstance(result, dict):
                raise AIError(f"atteso un oggetto JSON, ricevuto {type(result).__name__}")
        except AIError as e:
            print(f"[extractor] ERRORE estrazione {source_id}: {e}")
            return {"entities": [], "relations": [], "error": str(e)}
        for e in result.get("entities", []):
            if not e.get("id"):
                e["id"] = self._make_slug(e.get("label", "unknown"))
            # Documento da cui deriva la stima del punteggio
            e["risk_doc"] = source_id
        for r in result.get("relations", []):
            r["source_doc"] = source_id
        return {"entities": result.get("entities", []), "relations": result.get("relations", [])}

    async def extract_batch(self, items: List[Dict], text_field: str = "summary") -> Dict:
        """Estrae da più testi in parallelo e unisce i risultati; "errors" elenca i testi falliti."""
        all_entities: Dict[str, Dict] = {}
        all_relations: List[Dict] = []
        errors: List[str] = []

        tasks = [
            self.extract(
                item.get("title", "") + ". " + item.get(text_field, ""),
                source_id=item.get("id", "")
            )
            for item in items[:10]
        ]
        results = await asyncio.gather(*tasks)

        for result in results:
            if result.get("error"):
                errors.append(result["error"])
            for entity in result.get("entities", []):
                eid = entity["id"]
                # La stessa entità in più testi: vale il punteggio più alto, con il suo documento
                if eid not in all_entities or entity.get("risk_score", 0) > all_entities[eid].get("risk_score", 0):
                    all_entities[eid] = entity
            all_relations.extend(result.get("relations", []))

        return {"entities": list(all_entities.values()), "relations": all_relations, "errors": errors}

    def _discard(self, reason: str):
        """Citazione o alert scartato dal controllo sul record: nei log e nello stato dell'aggiornamento."""
        print(f"[extractor] {reason}")
        self.discarded.append(reason)

    @staticmethod
    def _latest_who(docs: List[Dict]) -> List[Dict]:
        """Ultima notizia OMS per evento: i bollettini precedenti sullo stesso evento sono superati.

        Solo notizie degli ultimi 45 giorni rispetto alla più recente. L'evento è la parte del titolo prima del paese ("Ebola disease caused by Bundibugyo virus, ..."/" - ...").
        """
        latest: Dict[str, Dict] = {}
        newest = max((d.get("published") or "" for d in docs), default="")
        oldest = (datetime.fromisoformat(newest) - timedelta(days=45)).date().isoformat() if newest else ""
        for d in sorted(docs, key=lambda d: d.get("published") or "", reverse=True):
            event = re.split(r" [-–] |, ", d.get("title", ""), maxsplit=1)[0].strip().lower()
            if event and event not in latest and d.get("summary") and (d.get("published") or "") >= oldest:
                latest[event] = d
        return list(latest.values())[:4]

    async def generate_alerts(self, entities: List[Dict], relations: List[Dict],
                              who_docs: Optional[List[Dict]] = None) -> List[Dict]:
        """Genera alert dai record delle fonti (richiami FDA, notizie OMS). Solleva AIError se non riesce.

        Al modello vanno i record originali, non le relazioni del grafo estratte dall'AI. Un alert resta solo
        se nasce da un record passato; il sistema aggiunge tra virgolette il testo del record (product_description
        del richiamo, frase del documento OMS indicata dal modello e verificata) e toglie l'orizzonte temporale
        perché nessun record ne indica uno. Due chiamate piccole (richiami, notizie OMS): se una fallisce si solleva
        AIError e restano gli alert dell'aggiornamento precedente, mai un insieme a metà.
        """
        self.discarded = []
        if not entities:
            raise AIError("grafo vuoto: nessuna entità da analizzare")

        # Richiami FDA più recenti con distribuzione in Italia (relazioni verso AIFA), con il record openFDA
        italy_recalls = sorted(
            [r for r in relations if str(r.get("id", "")).startswith("recall_") and r.get("target") == "aifa"
             and isinstance(r.get("record"), dict) and r["record"].get("product_description")],
            key=lambda r: r.get("date") or "", reverse=True,
        )[:ALERT_MAX_ITEMS]
        recalls = {}
        for r in italy_recalls:
            rec = r["record"]
            recalls[rec.get("recall_number") or r.get("source_doc")] = {
                "firm_id": r.get("source"),
                "code_info": (rec.get("code_info") or "")[:300],
                "record": {k: rec.get(k) for k in ("recall_number", "recalling_firm", "classification", "product_type",
                                                    "product_description", "reason_for_recall")},
            }
        who = {d["id"]: d for d in self._latest_who(who_docs or [])}

        groups = []
        if who:
            groups.append(("who", ALERT_RULES_WHO, [
                {"id": d["id"], "title": d.get("title"), "published": d.get("published"), "summary": d.get("summary")}
                for d in who.values()]))
        if recalls:
            groups.append(("recall", ALERT_RULES_RECALLS, [{"id": k, **v["record"], "code_info": v["code_info"]}
                                                                 for k, v in recalls.items()]))
        if not groups:
            raise AIError("nessun record da analizzare")

        squash = lambda t: re.sub(r"\s+", " ", t or "").strip()
        alerts: List[Dict] = []
        for kind, rules, records in groups:
            prompt = ALERT_PROMPT.format(rules=rules, data=json.dumps(records, indent=1, ensure_ascii=False))
            result = self._parse_json(await self._ask(prompt, ALERT_MAX_TOKENS))
            if not isinstance(result, list):
                raise AIError(f"attesa una lista di alert, ricevuto {type(result).__name__}")
            for a in result:
                if not isinstance(a, dict) or not a.get("title"):
                    continue
                sid = a.get("source_id")
                if kind == "recall" and sid in recalls:
                    rec = recalls[sid]["record"]
                    source_text = squash(json.dumps(rec, ensure_ascii=False))
                    a["description"] = (f"Richiamo FDA {sid}. Prodotto: \"{squash(rec['product_description'])}\" "
                                        f"Motivo: \"{squash(rec.get('reason_for_recall'))}\"")
                    a["italy_impact"] = ITALY_IMPACT_RECALL
                    a["entities_involved"] = [recalls[sid]["firm_id"]]
                elif kind == "who" and sid in who:
                    doc = who[sid]
                    source_text = squash(doc["summary"])
                    raw = a.pop("quotes", None) or a.pop("quote", None) or []
                    raw = [raw] if isinstance(raw, str) else raw
                    # Confronto senza distinguere apostrofi e virgolette tipografiche (sostituzione carattere per
                    # carattere): nell'alert va il testo preso dal documento, non quello scritto dal modello
                    plain = lambda t: t.translate(QUOTE_CHARS)
                    quotes = []
                    for q in raw[:2]:
                        q = squash(q) if isinstance(q, str) else ""
                        pos = plain(source_text).find(plain(q)) if len(q) >= 20 else -1
                        if pos < 0:
                            self._discard(f"citazione non presente nel documento {sid}: {q[:120]!r}")
                        else:
                            quotes.append(source_text[pos:pos + len(q)])
                    if not quotes:
                        self._discard(f"alert scartato, nessuna citazione verificata nel documento {sid}")
                        continue
                    a["description"] = (f"OMS, Disease Outbreak News {sid} del {doc.get('published')}: "
                                        + " ".join(f"\"{q}\"" for q in quotes))
                    a["italy_impact"] = (ITALY_IMPACT_WHO if not ITALY_RE.search(source_text)
                                         else "Il documento OMS nomina l'Italia: vedi il testo citato e la fonte.")
                    a["entities_involved"] = []
                else:
                    self._discard(f"alert scartato, record di origine sconosciuto {sid!r} ({a.get('title')!r})")
                    continue
                # Nessun record (richiamo o notizia OMS) indica un orizzonte futuro: un periodo citato nel
                # record ("Between 1 January and 5 October") è il periodo dei dati, non un orizzonte
                a["timeframe"] = None
                a.pop("predicted_impact", None)
                a["id"] = self._make_slug(f"{kind}_{sid}") or "alert"
                alerts.append(a)
        if not alerts:
            raise AIError("la risposta non contiene alert validi")
        # Id unici anche se due alert nascono dallo stesso record
        seen = set()
        for a in alerts:
            aid, i = a["id"], 2
            while a["id"] in seen:
                a["id"], i = f"{aid}_{i}", i + 1
            seen.add(a["id"])
        return alerts
