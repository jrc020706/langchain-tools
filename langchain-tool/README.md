# 💊 Medication Advisor Agent (LangChain + Gemini + MCP)

Bilingual (ES/EN) conversational agent that provides guidance on medications based on symptoms:
analyzes symptoms, provides medication fact sheets, calculates pediatric doses by weight,
checks interactions and contraindications, performs urgency triage, queries
**real pharmacovigilance (openFDA)** and searches **real pharmacies (OpenStreetMap)**.

> ⚠️ General educational guidance: **it does not diagnose or prescribe**. In case of
> warning signs (chest pain, difficulty breathing, heavy bleeding, loss of
> consciousness) call **112**.

---

## Project requirements and how they are met

| Requirement | Where it is met |
|---|---|
| At least **3 resources** | 6 MCP resources (`GET /resources`): 5 JSON datasets + 1 Markdown guide |
| At least **5 tools** (2 consuming internet APIs from **different clouds**) | 10 tools; `query_pharmacovigilance` → **openFDA/FAERS (NIH)** and `find_real_pharmacy` → **OpenStreetMap (Nominatim + Overpass)** |
| At least **2 prompts** to consume those APIs | 3 MCP prompts (`GET /prompts`): `openfda_pharmacovigilance`, `osm_real_pharmacies`, `internet_lookup` |
| **Deployed and consumable from any client** | `render.yaml` at the repo root (2 services) + `Dockerfile`; MCP HTTP endpoint `POST /mcp` and REST `POST /chat`, with CORS `*` and flat JSON responses |
| **No authentication** | No endpoint requires user, password or API key; `GOOGLE_API_KEY` is optional (without it, it works in demo mode) |
| At least **1 skill for agents** | [`skills/medication-advisor/SKILL.md`](../skills/medication-advisor/SKILL.md) (linked in `.opencode/skills/` and `.claude/skills/`) |
| **Documentation** | This README + [`docs/`](docs/) (`api.md`, `deployment.md`, `architecture.md`) |
| AI development traceability | [`../coding-assistance/README.md`](../coding-assistance/README.md) and [`../coding-assistance/prompts.json`](../coding-assistance/prompts.json) |

---

## Structure

```
langchain-tools/                    # repository root
├── render.yaml                     # Render Blueprint (2 services, rootDir: langchain-tool)
├── .python-version                 # 3.14 -> same version locally and in deployment
├── skills/medication-advisor/      # agent skill (SKILL.md)
├── .opencode/skills/…  and  .claude/skills/…   # links for self-discovery
├── coding-assistance/              # code assistant traceability
└── langchain-tool/
    ├── agent.py                    # agent: Gemini + AgentExecutor + per-session memory
    ├── tools.py                    # the 10 tools (8 local + 2 that consume APIs)
    ├── app.py                      # Gradio web interface (http://localhost:7860)
    ├── main.py                     # interactive terminal chat
    ├── fastmcp/server.py           # MCP HTTP server: tools + resources + prompts
    ├── mcp_server.py               # FastMCP startup alias
    ├── Dockerfile / .dockerignore  # alternative container deployment
    ├── data/
    │   ├── medications.json        # 18 common drugs in Spain
    │   ├── symptoms.json           # 24 symptom groups
    │   ├── interactions.json       # 26 common interactions
    │   ├── contraindications.json  # 12 conditions (pregnancy, hypertension, kidney…)
    │   └── pharmacies.json         # 10 sample pharmacies (simulated)
    ├── docs/                       # extended documentation
    ├── .env.example                # configuration template
    ├── requirements.txt            # pinned dependencies
    └── README.md                   # this file
```

## Installation

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional: set your GOOGLE_API_KEY (free at https://aistudio.google.com)
```

The versions in `requirements.txt` are **pinned** to those tested with
**Python 3.14** (the same one pinned by `.python-version`), so the local
installation and the deployment one resolve to the same thing.

Without an API key it still works in **simulated mode** (demo).

## Usage

```bash
python main.py                 # interactive terminal chat
python app.py                  # web interface at http://localhost:7860
python mcp_server.py           # MCP server + HTTP API at http://localhost:8000
python fastmcp/server.py       # identical to the previous one
```

In the terminal chat, type `/help`, `/history`, `/clear` or `/exit` (the Spanish
aliases `/ayuda`, `/historial`, `/limpiar` and `/salir` are also accepted).

---

## 🌐 MCP server and HTTP API (no authentication)

`mcp_server.py` listens on `127.0.0.1:8000` by default (in deployment,
`HOST=0.0.0.0` and `PORT` are injected by the provider). It publishes:

| Method | Route | What it does |
|---|---|---|
| `GET` | `/` | status, counts (`tools_total`, `resources_total`, `prompts_total`) and the APIs used |
| `GET` | `/tools` | the **10 tools** with their schemas |
| `GET` | `/resources` | the **6 resources** (URI, name, description) |
| `GET` | `/prompts` | the **3 prompts** with their arguments |
| `POST` | `/chat` | runs the agent: `{"input", "session_id", "language"}` |
| `GET` | `/history?session_id=x` | session history |
| `POST` | `/mcp` | **JSON-RPC of the MCP protocol** (tools, resources and prompts) |

Flat JSON responses (`stateless` + `json_response`) and **CORS `*`**, so that
any client can consume it: Claude, OpenCode, Cursor, ChatGPT Connectors,
`curl`, Python/JS scripts… **no API key, no login, no auth headers.**

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"input":"¿Qué es el paracetamol?","session_id":"demo"}'
```

To continue a conversation, reuse the same `session_id`. The history lives
in memory and is lost when the server stops.

Full guide with MCP and REST examples: [`docs/api.md`](docs/api.md).

---

## The 10 tools

| # | Tool | Input → Output | Source |
|---|---|---|---|
| 1 | `analyze_symptoms` | Free text → possible causes + OTC + warning signs | `data/symptoms.json` |
| 2 | `search_medication` | Brand or active ingredient name → full fact sheet | `data/medications.json` + fuzzy suggestions |
| 3 | `calculate_dose` | Medication + weight kg → mg per dose and interval | mg/kg rule in Python |
| 4 | `check_interaction` | 2 drugs → severity + recommendation | `data/interactions.json` |
| 5 | `check_contraindication` | Drug + condition → 🔴🟡🟢 + alternatives | `data/contraindications.json` |
| 6 | `assess_urgency` | Symptoms → 🟢 self-care / 🟡 doctor / 🔴 112 | Triage rules |
| 7 | `find_pharmacy` | Location → pharmacies (simulated data) | `data/pharmacies.json` |
| 8 | `calculate` | Expression → result | `numexpr` (safe parser) |
| 9 | `query_pharmacovigilance` | Drug → cases, common reactions and outcomes | 🔵 **Internet API #1:** openFDA/FAERS (NIH) |
| 10 | `find_real_pharmacy` | Location → real pharmacies with distance, address and opening hours | 🟢 **Internet API #2:** OpenStreetMap (Nominatim + Overpass) |

The last two are the ones that **consume internet APIs**; they are public, do not
require authentication and degrade with a clear notice if the network fails
(`find_real_pharmacy` falls back to the local tool `find_pharmacy`).

### MCP resources (6)

| URI | Content |
|---|---|
| `medications://dataset` | full `medications.json` |
| `symptoms://dataset` | full `symptoms.json` |
| `interactions://dataset` | full `interactions.json` |
| `contraindications://dataset` | full `contraindications.json` |
| `pharmacies://dataset` | `pharmacies.json` (simulated sample) |
| `medication-advisor://guide` | Markdown catalog of tools/prompts/endpoints and of the APIs used |

### MCP prompts (3)

| Prompt | Arguments | Purpose |
|---|---|---|
| `openfda_pharmacovigilance` | `medication` | consumes the **openFDA** API and explains how to interpret the reports |
| `osm_real_pharmacies` | `location` | consumes the **OpenStreetMap** APIs and lists nearby pharmacies |
| `internet_lookup` | `medication`, `location` | chains both APIs into a single guidance |

---

## 🚀 Deployment

Everything is prepared to deploy **without touching code**:

- **`render.yaml` at the repo root** with `rootDir: langchain-tool` → Render
  detects it automatically when creating a Blueprint (it used to be inside the
  folder and had to be set manually).
- **`.python-version` = `3.14`** at the root → the same Python version locally and
  on Render (no wheel problems when installing).
- **`requirements.txt` with pinned versions** → reproducible build.
- **`Dockerfile`** in case you prefer any other platform (Railway, Fly, AWS…).

Steps on Render: push the repo to GitHub → https://dashboard.render.com →
**New → Blueprint** → connect the repo → create the two services → (optionally)
add the `GOOGLE_API_KEY` secret. **No service requires credentials to be
consumed.**

| Service | Startup | What it exposes |
|---|---|---|
| `orientador-web` | `python app.py` | Gradio interface |
| `orientador-mcp` | `python mcp_server.py` | HTTP API + MCP server |

Details, alternatives (Docker, NGrok, Cloudflare) and troubleshooting:
[`docs/deployment.md`](docs/deployment.md).

> Free plan: services go to sleep after ~15 min without traffic; the first
> request afterwards takes ~1 min to wake them up.

---

## 🤖 Skill for agents

[`skills/medication-advisor/SKILL.md`](../skills/medication-advisor/SKILL.md)
defines when and how an agent should use this server (endpoint, tools, prompts,
resources, safety rules and disclaimer). It is linked in
`.opencode/skills/` and `.claude/skills/`, so OpenCode and Claude Code
discover it automatically when working inside the repo.

---

## Security

- The system prompt enforces: general guidance (no diagnoses or prescriptions),
  not prescribing antibiotics or prescription drugs, escalating to 112 on warning
  signs and closing every response with the disclaimer.
- The endpoints are open **on purpose** (requirement: no authentication): they
  expose no personal data, only educational datasets and public APIs. Do not put
  secrets in the code; `GOOGLE_API_KEY` goes in `.env` or in the secrets manager.
- The data from external APIs is for reference: FAERS consists of spontaneous
  reports and OpenStreetMap is collaborative; it is good practice to always
  say so.

## 📚 Documentation

- [`docs/api.md`](docs/api.md) — HTTP endpoints and MCP protocol (tools, resources, prompts).
- [`docs/deployment.md`](docs/deployment.md) — Render, Docker, tunnels and versions.
- [`docs/architecture.md`](docs/architecture.md) — hexagonal architecture and data flow.
- [`../coding-assistance/`](../coding-assistance/README.md) — AI development traceability.

## Extend

- **More medications/symptoms**: add entries to the JSON files (without touching code).
- **More APIs**: add a tool in `tools.py` following the pattern of
  `query_pharmacovigilance` and register it in `TOOLS`.
- **Persistent memory**: replace the dict in `agent.py` with Redis/Postgres.
