# coding-assistance — Trace of AI-assisted development

This folder documents **which AI agents/models/tools were used** to develop the
project and **every prompt** sent to a coding assistant, as required by the
assignment.

> **Secrets policy:** no API keys, tokens, passwords or any other secret are
> stored here. When a prompt or a note mentions a variable such as
> `GOOGLE_API_KEY`, it does so only as the name of an optional variable, never
> with its value.

---

## 1. Agents, models and tools used

| Agent / tool | Model | What it was used for |
|---|---|---|
| **OpenCode** (code-agent CLI) — session of **2026-10-09** | `mimo-v2.6-flash-free` (provider: `opencode`) | Main agent of that session: reading the code, editing `tools.py`, `fastmcp/server.py`, `agent.py`, `domain/prompts.py`, creating files (`render.yaml`, `.python-version`, `Dockerfile`, skills, documentation) and running tests |
| **`webfetch` tool (inside OpenCode)** | same model | Querying external documentation for version decisions: *Render → Setting Your Python Version* and *Render → Blueprint YAML Reference*, and *OpenCode → Agent Skills* |
| **OpenCode local tools** (`read`, `edit`, `write`, `shell`, `grep`, `glob`) | same model | Repository exploration, targeted edits and verification commands (MCP server, MCP client, external APIs) |
| **OpenCode** (code-agent CLI) — session of **2026-10-12** | `z-ai/glm-5.3` — **GLM-5.3** (provider: `nvidia`) | Audit of the project against the acceptance criteria (counting tools/resources/prompts in the code, checking that `.env` is not versioned, probing the production URLs), completion of this log, and the **English translation of all code and documentation** |
| **Skill `medication-advisor`** (created in the 2026-10-09 session, renamed in the 2026-10-12 translation session) | — | Not a development tool, but it is the "skill for agents" artifact required by the assignment |

Session of **2026-10-09** — model declared by the harness: **MiMo-V2.6-Flash Free**,
provider **opencode**, id `mimo-v2.6-flash-free`.
Session of **2026-10-12** — model declared by the harness: **GLM-5.3**,
provider **nvidia**, id `z-ai/glm-5.3`.
Earlier sessions (2026-10-06 → 2026-10-08) were developed with AI assistance whose
agent/model was not recorded at the time (see §3).

### What was done **without** AI assistance

- The prompts sent to the project's own agent (`POST /chat` on the local server,
  tools `query_pharmacovigilance` and `find_real_pharmacy`) are **tests of the
  application**, not prompts to a coding assistant, and are therefore not
  logged here.

---

## 2. Prompt log: `prompts.json`

[`prompts.json`](prompts.json) contains a `prompts` array with **every prompt**
sent to the coding assistant during development. Each entry includes at least:

| Field | Description |
|---|---|
| `timestamp` | ISO 8601 with timezone (`-05:00`) |
| `reconstruido` | Optional: `true` only on entries reconstructed after the fact from the git history (see §3); absent on entries recorded at the time |
| `agente_o_herramienta` | Agent or AI tool that received the prompt |
| `proveedor` / `modelo` | Provider and model used |
| `prompt` | Literal text of the prompt (no secrets) |
| `purpose` | Why it was sent |
| `artifacts` | Resulting or affected files |

### How to maintain it

1. Add a new entry for **every** prompt sent to a coding assistant.
2. Never paste key values into a prompt: replace them with the variable name
   (`GOOGLE_API_KEY`, `TU_TOKEN`, …).
3. Keep the same field order to make review easier.
4. If you recover a prompt after the fact that was not recorded at the time,
   mark the entry with `"reconstruido": true` and note the associated commit in
   its `purpose`, to distinguish it from literal transcripts.

---

## 3. Coverage and limitations

- The log covers **all development sessions** of the project
  (2026-10-06 → 2026-10-12) and grows with every new prompt.
- **Literal transcripts** (recorded at the time): the session of
  **2026-10-09** (alignment with the assignment and the two external
  documentation queries via `webfetch`) and the sessions of **2026-10-12**
  (audit against the acceptance criteria, completion of this log, and the
  English translation of code and documentation).
- **After-the-fact reconstructions** (marked with `"reconstruido": true`): the
  prompts of the sessions from **2026-10-06 to 2026-10-08** (initial skeleton,
  agent with tools and datasets, hexagonal architecture, bilingual support,
  sessions and Render blueprint) and the tests prompt of **2026-10-09** **were
  not saved at the time**. They were reconstructed from the git history (commit
  date and message + modified files, verified with `git show --stat`): the text
  is a faithful paraphrase of the intent —not a literal transcript—, the
  agent/model of those sessions is "not recorded" and the timestamp is
  approximate (immediately before the resulting commit). Each entry notes its
  associated commit in its `purpose`.

---

## 4. Verifications performed

### Session of 2026-10-09 (alignment with the assignment)

To ensure what is delivered works when deployed:

| Verification | Result |
|---|---|
| Install and boot of `mcp_server.py` | ✅ server on `127.0.0.1:8010` |
| `GET /` | ✅ `tools_total: 10`, `resources_total: 6`, `prompts_total: 3` |
| `GET /tools`, `GET /resources`, `GET /prompts` | ✅ list 10 / 6 / 3 items |
| `POST /mcp` with the official MCP client (`initialize`, `list_tools`, `list_resources`, `list_prompts`, `read_resource`, `get_prompt`, `call_tool`) | ✅ everything responds |
| Tool `query_pharmacovigilance` (openFDA) | ✅ returns total, sample and reactions (ES and EN) |
| Tool `find_real_pharmacy` (OpenStreetMap) | ✅ real pharmacies <1 km from "Calle Mayor 1, Madrid" (3.6 s) and "Barcelona" (6.5 s), with budget splitting (`OVERPASS_MAX`/`NOMINATIM_MAX`) and *fallbacks* when Overpass is saturated |
| Per-tool time budgets | ✅ no tool hangs the chat: ≤22 s (API) and ≤20 s (geography) even if every call fails |
| `POST /chat` with the agent | ✅ answers using the API tools |
| CORS | ✅ `access-control-allow-origin: *` |
| Versions (Python + pinned `requirements.txt`) | ✅ aligned with the deployment |

### Session of 2026-10-12 (audit against the acceptance criteria)

| Verification | Result |
|---|---|
| Counts in the code (`@tool`, `@mcp.resource`, `@mcp.prompt`) | ✅ 10 tools / 6 resources / 3 MCP prompts |
| `.env` versioned in git | ✅ not tracked (only `.env.example`); no secrets in the repo |
| Render production URLs (`orientador-mcp.onrender.com`, `orientador-web.onrender.com`) | ❌ return `404` with header `x-render-routing: no-server` → **no deployed service**; deployment criterion pending |
| Sync with GitHub (`github.com/jrc020706/langchain-tools`) | ✅ local `main` and remote on the same commit, public repo |

### Session of 2026-10-12 (English translation of code and documentation)

| Verification | Result |
|---|---|
| `python3 -m py_compile` on every project `.py` file | ✅ all compile |
| `pytest langchain-tool/tests/basic_test.py` | ✅ 3 passed (tests renamed to English) |
| Boot of `mcp_server.py` + `GET /`, `/tools`, `/resources`, `/prompts` | ✅ 10 / 6 / 3 with English names and English JSON keys |
| `POST /chat` in Spanish and in English | ✅ auto-detects `es`/`en` and answers in the same language (bilingual product kept) |
| `POST /mcp` `initialize` | ✅ `serverInfo.name: MedicationAdvisorHexagonal`, English `instructions` |
| Skill renamed to `skills/medication-advisor` with symlinks updated in `.opencode/skills/` and `.claude/skills/` | ✅ loads with `name: medication-advisor` |
| Grep for old Spanish identifiers in `.py` files | ✅ no leftovers (Spanish remains only in bilingual docstrings, product strings and dataset values) |
