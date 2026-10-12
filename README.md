# langchain-tools — Medication Advisor (LangChain + Gemini + MCP)

Repository with a bilingual (ES/EN) conversational agent that provides guidance
on medications, published as an **MCP server + HTTP API with no authentication**
so that any client (agents, chat connectors, scripts) can consume it.

## Repository contents

| Path | What it is |
|---|---|
| [`langchain-tool/`](langchain-tool/README.md) | The project: agent, 10 tools, MCP server, Gradio interface, data and Dockerfile |
| [`langchain-tool/docs/`](langchain-tool/docs) | Documentation: [`api.md`](langchain-tool/docs/api.md), [`deployment.md`](langchain-tool/docs/deployment.md), [`architecture.md`](langchain-tool/docs/architecture.md) |
| [`skills/medication-advisor/`](skills/medication-advisor/SKILL.md) | Skill for agents (auto-discovered by OpenCode/Claude Code) |
| [`render.yaml`](render.yaml) | Render Blueprint (2 services, `rootDir: langchain-tool`) |
| [`.python-version`](.python-version) | Pins Python 3.14 locally and in deployment |
| [`coding-assistance/`](coding-assistance/README.md) | Traceability of AI-assisted development (agents, models and prompts used) |

## Quick start

```bash
cd langchain-tool
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app.py            # web interface  → http://127.0.0.1:7860
python mcp_server.py     # API + MCP      → http://127.0.0.1:8000
```

Without `GOOGLE_API_KEY` everything works in demo mode (no credentials are
needed, neither to use the agent nor to consume its API).

## Requirements covered

- ✅ **3 resources** → 6 MCP resources (`GET /resources`).
- ✅ **5 tools**, two of them consuming internet APIs from **different clouds**:
  **openFDA/FAERS** (`query_pharmacovigilance`) and **OpenStreetMap**
  (`find_real_pharmacy`); 10 tools in total.
- ✅ **2 prompts** to consume those APIs → `openfda_pharmacovigilance` and
  `osm_real_pharmacies` (plus `internet_lookup`), via `GET /prompts`.
- ✅ **Deployable and consumable from any client** → `render.yaml`
  (Blueprint), `Dockerfile`, MCP endpoint `POST /mcp`, REST `POST /chat`,
  flat JSON responses and CORS `*`.
- ✅ **No authentication** → no endpoint requires user, password or API key.
- ✅ **Skill for agents** → `skills/medication-advisor/SKILL.md`.
- ✅ **Documentation** → READMEs, `langchain-tool/docs/` and this page.
- ✅ **AI traceability** → `coding-assistance/README.md` + `prompts.json`.

## Security

General guidance for educational purposes: it does not diagnose or prescribe.
In case of warning signs (chest pain, difficulty breathing, heavy bleeding,
loss of consciousness) call **112**.
