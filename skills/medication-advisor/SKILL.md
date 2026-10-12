---
name: medication-advisor
description: Use the "Medication Advisor / Orientador de Medicamentos" MCP server for bilingual (Spanish or English) guidance on symptoms, medicine information sheets, pediatric doses, interactions, contraindications, urgency triage, pharmacovigilance (openFDA API) and real pharmacies (OpenStreetMap API). Activate it when the user asks about medicines, drugs, doses, adverse effects, interactions, pharmacies or whether they should see a doctor. Usa el servidor MCP "Orientador de Medicamentos" para orientar (en español o inglés) sobre síntomas, fichas de medicamentos, dosis pediátricas, interacciones, contraindicaciones, triaje de urgencia, farmacovigilancia (API openFDA) y farmacias reales (API OpenStreetMap).
license: MIT
compatibility: opencode
metadata:
  audience: agents
  endpoint: https://orientador-mcp.onrender.com
  protocols: mcp, http-rest
---

# Medication Advisor — skill for agents

Skill that lets an agent use the MCP server of the **`langchain-tool`** project without
reinventing logic: the server exposes 10 tools, 6 resources and 3 prompts over HTTP,
**with no authentication** (no API key, no login, open CORS).

## When to use it

- The user asks about a medicine, symptom, dose, interaction, contraindication,
  urgency/triage, adverse effects or pharmacies.
- Bilingual (ES/EN) general guidance with a medical disclaimer is needed.

Do not use it for: diagnoses, prescriptions, or prescribing antibiotics / Rx-only medicines.

## How to connect (no credentials)

The server is at `https://orientador-mcp.onrender.com` (locally: `http://127.0.0.1:8000`).

1. **MCP (recommended)** — `POST /mcp` endpoint (MCP protocol JSON-RPC,
   flat JSON responses, stateless, no session).
2. **REST** — `POST /chat` with `{"input": "...", "session_id": "optional", "language": "es|en|auto"}`.
3. **Discovery** — `GET /` (status), `GET /tools`, `GET /resources`, `GET /prompts`.

Quick verification:

```bash
curl -s https://orientador-mcp.onrender.com/ | jq .tools_total   # -> 10
curl -s -X POST https://orientador-mcp.onrender.com/chat \
  -H 'Content-Type: application/json' \
  -d '{"input":"¿Qué es el ibuprofeno?","session_id":"demo"}'
```

If the server is asleep (Render free plan), the first request takes ~1 minute.

## The 10 tools

| Tool | Type | Use |
|---|---|---|
| `analyze_symptoms` | local | free-text symptoms → causes, OTC, red flags |
| `search_medication` | local | info sheet by brand or active ingredient |
| `calculate_dose` | local | pediatric dose by weight (mg/kg) |
| `check_interaction` | local | interaction between 2 drugs |
| `check_contraindication` | local | drug + clinical condition |
| `assess_urgency` | local | triage: 🟢 self-care / 🟡 doctor / 🔴 112 |
| `find_pharmacy` | local | sample pharmacies (simulated data) |
| `calculate` | local | safe arithmetic (mg, ml, doses) |
| `query_pharmacovigilance` | **internet API #1** | adverse-reaction reports from **openFDA / FAERS (NIH)** |
| `find_real_pharmacy` | **internet API #2** | real pharmacies from **OpenStreetMap** (Nominatim + Overpass) |

Both API tools are public and **carry no authentication**; if the network fails,
they return a notice and suggest the local fallback (`find_pharmacy`).

## MCP prompts (to consume the internet APIs)

- `openfda_pharmacovigilance(medication)` → drafts the openFDA call.
- `osm_real_pharmacies(location)` → drafts the OpenStreetMap call.
- `internet_lookup(medication, location)` → chains both APIs.

## MCP resources (6)

`medications://dataset`, `symptoms://dataset`, `interactions://dataset`,
`contraindications://dataset`, `pharmacies://dataset` (full JSON files) and
`medication-advisor://guide` (Markdown catalog of tools/prompts/endpoints).

## Safety rules the agent must follow

1. This is **general guidance**: never a diagnosis or a prescription. Do not prescribe
   antibiotics or Rx-only medicines.
2. On red flags (chest pain, breathing difficulty, heavy bleeding, loss of
   consciousness, tongue/lip swelling, suicidal ideation) → **112 / emergency**.
3. Pregnancy, breastfeeding, children under 2 or chronic disease: be conservative and
   refer to a pharmacist/doctor.
4. **Always** end every answer with the disclaimer in the current language:
   - ES: `⚠️ Orientación general, no sustituye al médico o farmacéutico.`
   - EN: `⚠️ General guidance, does not replace your doctor or pharmacist.`
5. External APIs are reference data (FAERS = spontaneous reports, OSM =
   collaborative data): warn that they may be incomplete or outdated.

## Answer format

Reply in the user's language (detect ES/EN), with short lists, stating whether the
data comes from an API (`openFDA`, `OpenStreetMap`) or from the local dataset.
