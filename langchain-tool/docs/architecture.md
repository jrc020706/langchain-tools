# 🏗️ Architecture

## Overview

```
                       ┌────────────────────────────────────────────┐
 clients (no auth)     │            langchain-tool/                │
 ────────────────────► │                                            │
  browser (Gradio)     │  app.py ────────┐                          │
  curl (REST)          │  main.py ───────┤                          │
  agent (MCP)  ────────┼─ fastmcp/server.py (HTTP + MCP)            │
                       │                 │                          │
                       │                 ▼                          │
                       │      domain/use_cases/chat_use_case.py     │
                       │        (ReAct loop, bilingual, disclaimer) │
                       │                 │  depends on interfaces   │
                       │        ┌────────┴─────────┐                │
                       │        ▼                  ▼                │
                       │   ports/*.py         ports/*.py            │
                       │   (LlmPort,          (ToolPort,            │
                       │    MemoryPort)        MemoryPort)          │
                       │        │                  │                │
                       │        ▼                  ▼                │
                       │  adapters/llm_*      adapters/tool_adapter │
                       │  adapters/memory_*   tools.py (10 tools)   │
                       └────────────┬───────────────┬────────────────┘
                                    │               │
                          Gemini (optional)   data/*.json  +  2 public APIs
```

**Hexagonal pattern (ports and adapters)**: the domain knows nothing about
Gemini, LangChain or the datasets; only about the ports (`ports/`). The
adapters (`adapters/`) are the ones that touch the outside world.

## Layers

| Layer | Files | Responsibility |
|---|---|---|
| Presentation | `app.py` (Gradio), `main.py` (terminal), `fastmcp/server.py` (HTTP/MCP) | Input/output, no business logic |
| Application | `domain/use_cases/chat_use_case.py` | ReAct loop (max. 5 iterations), language and disclaimer |
| Domain | `domain/models.py`, `domain/prompts.py`, `domain/i18n.py`, `domain/session_history.py` | Models, system prompt, language detection, history |
| Ports | `ports/llm_port.py`, `ports/tool_port.py`, `ports/memory_port.py` | Abstract interfaces |
| Adapters | `adapters/llm_adapter.py`, `llm_adapter_fake.py`, `tool_adapter.py`, `memory_adapter.py` | Concrete implementations |
| Data | `data/*.json` + `tools.py` | 8 local tools and 2 API tools |

## Request flow (MCP `POST /chat`)

1. `fastmcp/server.py` validates the body and calls `ChatUseCase.execute`.
2. The use case detects the language (`domain/i18n`), retrieves the session
   history and builds `[system, …history, user]`.
3. `LlmPort.bind_tools(tools)` returns the LLM *bound* to the 10 tools:
   - with `GOOGLE_API_KEY` → `ChatGoogleGenerativeAI` (Gemini decides),
   - without the key → `_FakeToolBinding` from `agent.py` (keyword-based
     routing, useful for demos and for tests).
4. While there are `tool_calls`, they are run through `ToolPort.execute_tool`
   and the results come back as `ToolMessage` (max. 5 iterations).
5. The disclaimer for the language is guaranteed and everything is persisted
   through `MemoryPort`.

## The 10 tools

- **8 local** (`tools.py`): they read `data/*.json` into memory (loaded on
  import), normalize without accents and compare by keywords/aliases.
- **2 API** tools (both required, from different clouds):
  - `query_pharmacovigilance` → **openFDA/FAERS** (`https://api.fda.gov/drug/event.json`).
    Maps ES active ingredient → US USAN generic name, tries several exact
    fields and summarizes total/sample/reactions/outcome.
  - `find_real_pharmacy` → **OpenStreetMap** (`nominatim` + `overpass`).
    Geocodes, searches `amenity=pharmacy` within 3 km, computes distances and
    degrades with *fallbacks* (other mirrors → Nominatim → local
    `find_pharmacy`).

Both use `requests` with `timeout=15`, an identifying `User-Agent` and **no
authentication**; any failure turns into a helpful message, never into an
exception for the client.

## MCP publication: tools, resources and prompts

`fastmcp/server.py` registers:

- **10 tools**: the ones from `tools.py` (`mcp.tool(...)`).
- **6 resources**: 5 datasets (`medications://dataset`, …) and the guide
  `medication-advisor://guide` (Markdown).
- **3 prompts**: `openfda_pharmacovigilance`, `osm_real_pharmacies` and
  `internet_lookup` (the first two exist to consume the external APIs).

It also exposes REST discovery routes (`/tools`, `/resources`, `/prompts`) for
clients that do not speak MCP.

## Memory and sessions

- In-memory dictionary per `session_id` (`domain/session_history.py` and
  `adapters/memory_adapter.py`).
- Restarting the process ⇒ clean history (that is why there is no state to
  migrate).
- In Gradio the browser's `session_hash` is used.

## Demo mode without API key

`_FakeToolBinding` imitates the output of an LLM with *function calling*: it
detects patterns (urgency, interactions, dose, pharmacies, APIs…) and returns
real `tool_calls`, so the ReAct loop and the 10 tools run exactly as they do
with Gemini. This allows deploying **without credentials**.
