import anthropic
import asyncio
import json
import os
import re
from typing import Dict, List, Optional

from limits import try_consume_ai_call
import costs
import italy
import normalize

# Parole che segnalano un rischio nei testi delle fonti italiane (inizio di parola, testo normalizzato)
RISK_WORDS_IT = ["carenz", "ritir", "richiam", "revoc", "sospens", "allert", "focola", "epidemi", "emergenz",
                 "casi confermati", "decessi", "contraffa", "infezion", "west nile", "dengue", "morbillo"]

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

ALERT_PROMPT = """Analizza questi dati di un knowledge graph sanitario e genera alert per chi lavora nel Servizio Sanitario Nazionale italiano.
{focus}

{data}

Per ogni alert valuta in modo esplicito l'impatto sull'Italia e sul SSN:
- per un focolaio all'estero indica le vie concrete con cui potrebbe riguardare l'Italia (viaggi e voli, rientri di operatori sanitari o cooperanti, sorveglianza ai punti di ingresso, preparazione di ospedali e laboratori di riferimento) e dì chiaramente se il rischio per l'Italia è basso;
- per un richiamo di farmaci o dispositivi distribuiti in Italia indica quali strutture o pazienti italiani potrebbero essere coinvolti e cosa dovrebbero verificare farmacie ospedaliere e ingegneria clinica;
- non inventare numeri, casi o date che non siano nei dati; se un'informazione manca, dillo.

Genera da 1 a 3 alert, con testi brevi: "title" al massimo 12 parole, "description", "italy_impact" e "recommendation" al massimo 40 parole ciascuno, "predicted_impact" al massimo 25 parole, al massimo 4 "entities_involved".
Formato JSON:
[
  {{
    "id": "alert_slug",
    "title": "Titolo breve alert",
    "description": "Descrizione del rischio basata sui dati",
    "severity": "CRITICAL|HIGH|MEDIUM|LOW",
    "entities_involved": ["id1", "id2"],
    "italy_relevance": "ALTA|MEDIA|BASSA|NESSUNA",
    "italy_impact": "impatto concreto per l'Italia e il SSN, con le vie di esposizione",
    "predicted_impact": "impatto atteso su pazienti e servizi",
    "timeframe": "es. 3-6 mesi",
    "recommendation": "azione consigliata alle autorità e alle aziende sanitarie italiane"
  }}
]

Rispondi SOLO con JSON valido."""


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

            # Route to EMA for worldwide/European distribution, else AIFA
            dist = recall.get("distribution_pattern", "").lower()
            target = "ema" if any(kw in dist for kw in ("europe", "worldwide", "international")) else "aifa"

            classification = recall.get("classification", "")
            reason = recall.get("reason_for_recall", "")[:120]
            recall_id = recall.get("id", "")

            # Una relazione per richiamo: un nuovo richiamo di un'azienda già nota resta visibile
            rd = recall.get("report_date", "")
            relations.append({
                "id": f"recall_{recall_id}" if recall_id else None,
                "source": firm_slug,
                "target": target,
                "type": "RISCHIO_PER",
                "fact": f"[{classification}] {recall_id}: {reason}",
                "risk_score": risk_score,
                "source_doc": recall_id,
                "date": f"{rd[:4]}-{rd[4:6]}-{rd[6:8]}" if len(rd) == 8 else None,
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
                if eid not in all_entities:
                    all_entities[eid] = entity
                else:
                    all_entities[eid]["risk_score"] = max(
                        all_entities[eid].get("risk_score", 0),
                        entity.get("risk_score", 0)
                    )
            all_relations.extend(result.get("relations", []))

        return {"entities": list(all_entities.values()), "relations": all_relations, "errors": errors}

    async def generate_alerts(self, entities: List[Dict], relations: List[Dict]) -> List[Dict]:
        """Genera alert dal grafo con la valutazione dell'impatto sull'Italia. Solleva AIError se non riesce.

        Due chiamate piccole invece di una grande (eventi sanitari, richiami distribuiti in Italia):
        la risposta resta corta e non si tronca. Se una delle due fallisce si solleva AIError e
        restano gli alert dell'aggiornamento precedente, mai un insieme a metà.
        """
        if not entities:
            raise AIError("grafo vuoto: nessuna entità da analizzare")

        # Richiami FDA più recenti con distribuzione in Italia (relazioni verso AIFA)
        italy_recalls = sorted(
            [r for r in relations if str(r.get("id", "")).startswith("recall_") and r.get("target") == "aifa"],
            key=lambda r: r.get("date") or "", reverse=True,
        )[:ALERT_MAX_ITEMS]
        # Eventi e focolai: entità e relazioni ad alto rischio che non vengono dai richiami
        events = {
            "high_risk_entities": [
                {k: e.get(k) for k in ("id", "label", "type", "region", "risk_score")}
                for e in entities if e.get("risk_score", 0) > 60 and e.get("type") != "PharmaCompany"
            ][:ALERT_MAX_ITEMS],
            "high_risk_relations": [
                {"source": r.get("source"), "target": r.get("target"), "type": r.get("type"),
                 "fact": (r.get("fact") or "")[:200], "date": r.get("date")}
                for r in relations if r.get("risk_score", 0) > 60 and not str(r.get("id", "")).startswith("recall_")
            ][:ALERT_MAX_ITEMS],
        }
        groups = []
        if events["high_risk_entities"] or events["high_risk_relations"]:
            groups.append(("Concentrati su focolai ed eventi sanitari.", events))
        if italy_recalls:
            groups.append(("Concentrati sui richiami FDA di farmaci e dispositivi distribuiti in Italia.", {
                "recent_recalls_distributed_in_italy": [
                    {"firm": r.get("source"), "date": r.get("date"), "fact": (r.get("fact") or "")[:200]}
                    for r in italy_recalls
                ]}))
        if not groups:
            raise AIError("nessun dato ad alto rischio da analizzare")

        alerts: List[Dict] = []
        for focus, data in groups:
            prompt = ALERT_PROMPT.format(focus=focus, data=json.dumps(data, indent=1, ensure_ascii=False))
            result = self._parse_json(await self._ask(prompt, ALERT_MAX_TOKENS))
            if not isinstance(result, list):
                raise AIError(f"attesa una lista di alert, ricevuto {type(result).__name__}")
            alerts += [a for a in result if isinstance(a, dict) and a.get("title")]
        if not alerts:
            raise AIError("la risposta non contiene alert validi")
        # Id unici anche se le due chiamate ne propongono uno uguale
        seen = set()
        for a in alerts:
            aid, i = a.get("id") or "alert", 2
            while a.get("id") in seen or not a.get("id"):
                a["id"], i = f"{aid}_{i}", i + 1
            seen.add(a["id"])
        return alerts
