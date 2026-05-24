import anthropic
import json
import os
import re
from typing import Dict, List

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

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
}}"""


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

            relations.append({
                "source": firm_slug,
                "target": target,
                "type": "RISCHIO_PER",
                "fact": f"[{classification}] {recall_id}: {reason}",
                "risk_score": risk_score,
                "date": recall.get("report_date", "")[:7] or None,
            })

        return {"entities": list(entities.values()), "relations": relations}

    async def extract(self, text: str, source_id: str = "") -> Dict:
        """Extract entities and relations from text using Claude claude-sonnet-4-6."""
        if not text or len(text.strip()) < 50:
            return {"entities": [], "relations": []}
        try:
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": EXTRACT_PROMPT.format(text=text[:3000])
                }]
            )
            raw = message.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw)
            for e in result.get("entities", []):
                if not e.get("id"):
                    e["id"] = self._make_slug(e.get("label", "unknown"))
            for r in result.get("relations", []):
                r["source_doc"] = source_id
            return result
        except Exception as e:
            print(f"[extractor] Error: {e}")
            return {"entities": [], "relations": []}

    async def extract_batch(self, items: List[Dict], text_field: str = "summary") -> Dict:
        """Extract from multiple items and merge results."""
        import asyncio
        all_entities: Dict[str, Dict] = {}
        all_relations: List[Dict] = []

        tasks = [
            self.extract(
                item.get(text_field, "") + " " + item.get("title", ""),
                source_id=item.get("id", "")
            )
            for item in items[:10]
        ]
        results = await asyncio.gather(*tasks)

        for result in results:
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

        return {"entities": list(all_entities.values()), "relations": all_relations}

    async def generate_alerts(self, entities: List[Dict], relations: List[Dict]) -> List[Dict]:
        """Use Claude claude-sonnet-4-6 to generate predictive risk alerts from the health graph."""
        if not entities:
            return []

        graph_summary = json.dumps({
            "high_risk_entities": [e for e in entities if e.get("risk_score", 0) > 60][:10],
            "high_risk_relations": [r for r in relations if r.get("risk_score", 0) > 60][:10],
        }, indent=2)

        try:
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1500,
                messages=[{
                    "role": "user",
                    "content": f"""Analizza questo knowledge graph del sistema sanitario e genera alert predittivi.

{graph_summary}

Genera 3-5 alert predittivi in formato JSON:
[
  {{
    "id": "alert_slug",
    "title": "Titolo breve alert",
    "description": "Descrizione dettagliata del rischio e previsione",
    "severity": "CRITICAL|HIGH|MEDIUM|LOW",
    "entities_involved": ["id1", "id2"],
    "predicted_impact": "descrizione impatto atteso su SSN/pazienti",
    "timeframe": "es. 3-6 mesi",
    "recommendation": "azione consigliata per autorità sanitarie"
  }}
]

Rispondi SOLO con JSON valido."""
                }]
            )
            raw = message.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw)
        except Exception as e:
            print(f"[extractor] Alert generation error: {e}")
            return []
