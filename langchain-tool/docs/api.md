# 📡 API and MCP protocol

The server (`python mcp_server.py`) exposes the same functionality through two
paths: **HTTP/REST** (easy to test with `curl`) and **MCP** (for agents and
compatible clients). **Neither requires authentication**: no API key, no login,
no special headers. CORS is open (`*`) so it can be used from any browser or
client.

- Local: `http://127.0.0.1:8000`
- Deployment: `https://orientador-mcp.onrender.com` (or whatever URL your provider assigns)

---

## 1. REST endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Server status (bilingual), counts and APIs used |
| `GET` | `/tools` | Lists the 10 tools with description and JSON schema |
| `GET` | `/resources` | Lists the 6 MCP resources |
| `GET` | `/prompts` | Lists the 3 MCP prompts with their arguments |
| `POST` | `/chat` | Runs the agent (memory per `session_id`) |
| `GET` | `/history?session_id=x` | Returns the history of a session |
| `POST` | `/mcp` | JSON-RPC endpoint of the MCP protocol |

### `GET /`

```bash
curl -s https://orientador-mcp.onrender.com/
```

Response (abbreviated):

```json
{
  "message": "FastMCP Server: Medication Advisor / Orientador de Medicamentos (Hexagonal Architecture)",
  "version": "3.0.0",
  "architecture": "hexagonal (ports and adapters)",
  "languages": ["es", "en"],
  "language_mode": "auto-detect per message (override with POST /chat {\"language\": \"es\"|\"en\"})",
  "authentication": "none (no API key, no login): open endpoints",
  "endpoints": {
    "chat": "POST /chat",
    "history": "GET /history?session_id=x",
    "tools": "GET /tools",
    "resources": "GET /resources",
    "prompts": "GET /prompts",
    "mcp": "POST /mcp (JSON-RPC MCP)",
    "status": "GET /"
  },
  "internet_apis": [
    {"service": "openFDA / FAERS (NIH)", "tool": "query_pharmacovigilance", "url": "https://api.fda.gov/drug/event.json", "authentication": "none"},
    {"service": "OpenStreetMap (Nominatim + Overpass)", "tool": "find_real_pharmacy", "url": "https://nominatim.openstreetmap.org", "authentication": "none"}
  ],
  "llm_mode": "real",
  "tools_total": 10,
  "resources_total": 6,
  "prompts_total": 3
}
```

### `POST /chat`

Body:

```json
{
  "input": "¿Qué dosis de paracetamol le doy a un niño de 22 kg?",
  "session_id": "demo",
  "language": "es"
}
```

(English equivalent: `"What paracetamol dose do I give a 22 kg child?"` with `"language": "en"`.)

- `input` *(required)*: user message (ES or EN).
- `session_id` *(optional)*: reuse it to keep the context.
- `language` *(optional)*: `"es"`, `"en"` or `"auto"` (auto-detected by default).

Response:

```json
{
  "output": "Dosis orientativa de paracetamol para 22 kg: 330 mg por toma …",
  "session_id": "demo",
  "language": "es",
  "tool_calls": [{"name": "calculate_dose", "args": {"medication": "paracetamol", "weight_kg": 22}}],
  "message_count": 2
}
```

(The answer text follows the detected language: Spanish for `"es"`, English for `"en"`.)

Errors: `400` if `input`/`language` are not valid — for example
`{"error": "The 'input' field must be non-empty text."}` — and `500` with
`{"error": …}` if something fails internally.

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"input":"busca farmacias reales en Madrid","session_id":"demo"}'
```

---

## 2. MCP protocol (`POST /mcp`)

The FastMCP server registers **tools**, **resources** and **prompts** under the
MCP route `/mcp`. It starts in `stateless` mode with flat JSON responses (no
SSE), which makes life easier for simple clients (curl, SDKs, chat connectors).

### Configuration in an MCP client

```json
{
  "mcpServers": {
    "medication-advisor": {
      "type": "http",
      "url": "https://orientador-mcp.onrender.com/mcp"
    }
  }
}
```

No authorization headers are needed.

### Example with the official Python SDK

```python
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def main():
    async with streamable_http_client("http://127.0.0.1:8000/mcp") as streams:
        async with ClientSession(streams[0], streams[1]) as s:
            await s.initialize()
            print([t.name for t in (await s.list_tools()).tools])          # 10 tools
            print([str(r.uri) for r in (await s.list_resources()).resources])  # 6 resources
            print([p.name for p in (await s.list_prompts()).prompts])      # 3 prompts
            out = await s.call_tool("query_pharmacovigilance", {"name": "ibuprofeno"})
            print(out.content[0].text)

asyncio.run(main())
```

### Supported methods

| Method | What it returns |
|---|---|
| `initialize` / `tools/list` | the 10 tools with their schemas |
| `tools/call` | runs a tool (e.g. `find_real_pharmacy`) |
| `resources/list` | the 6 resources |
| `resources/read` | dataset content (JSON) or the guide (Markdown) |
| `prompts/list` | the 3 prompts |
| `prompts/get` | the prompt message rendered with its arguments |

---

## 3. Tools

### 3.1 Local (datasets in `data/`)

`analyze_symptoms`, `search_medication`, `calculate_dose`,
`check_interaction`, `check_contraindication`, `assess_urgency`,
`find_pharmacy`, `calculate`.

All of them accept the optional `language` parameter (`"es"`, `"en"` or
`"auto"`) and return plain text ending with the disclaimer for the language.

### 3.2 `query_pharmacovigilance` — internet API #1 (openFDA)

- **Service:** openFDA / FAERS — `https://api.fda.gov/drug/event.json` (NIH, USA)
- **Authentication:** none (public API, no API key).
- **Parameters:** `name` (active ingredient or brand), `language`.
- **What it does:** translates the local name to the US generic USAN name
  (e.g. `paracetamol` → `acetaminophen`), tries several exact fields
  (`generic_name`, `medicinalproduct`, `brand_name`) and summarizes: total
  reports, analyzed sample, most frequent reactions and outcome.
- **Semantics:** **spontaneous** reports; correlation ≠ causality and there is
  under-reporting. The tool always states this in its output.

```bash
curl -s -X POST http://127.0.0.1:8000/chat -H 'Content-Type: application/json' \
  -d '{"input":"¿Qué efectos adversos se han notificado de ibuprofeno?","language":"es"}'
```

(English equivalent: `"What adverse effects have been reported for ibuprofen?"` with `"language": "en"`.)

### 3.3 `find_real_pharmacy` — internet API #2 (OpenStreetMap)

- **Services:** `https://nominatim.openstreetmap.org/search` (geocoding) and
  `https://overpass-api.de/api/interpreter` (`amenity=pharmacy` points), with
  backup mirrors (`overpass.private.coffee`, `overpass.kumi.systems`).
- **Authentication:** none; only an identifying `User-Agent` (required by OSM's
  usage policy, it is not a credential).
- **Parameters:** `location` (city, neighborhood or address), `language`.
- **What it does:** geocodes → searches pharmacies within a 3 km radius →
  computes distances (haversine) → returns the 5 closest ones with address,
  phone and opening hours. If Overpass is overloaded, it *falls back* to a
  direct search on Nominatim and retries Overpass; if there is no network, it
  suggests `find_pharmacy` (local data).

```bash
curl -s -X POST http://127.0.0.1:8000/chat -H 'Content-Type: application/json' \
  -d '{"input":"farmacias reales cerca de Barcelona","language":"es"}'
```

---

## 4. Resources

| URI | MIME | Content |
|---|---|---|
| `medications://dataset` | `application/json` | 18 medications with a full record |
| `symptoms://dataset` | `application/json` | 24 symptom groups |
| `interactions://dataset` | `application/json` | 26 interactions |
| `contraindications://dataset` | `application/json` | 12 clinical conditions |
| `pharmacies://dataset` | `application/json` | 10 simulated pharmacies |
| `medication-advisor://guide` | `text/markdown` | Guide to tools/prompts/endpoints and APIs |

```bash
curl -s http://127.0.0.1:8000/resources | jq '.resources[].uri'
```

---

## 5. Prompts

| Prompt | Arguments | Use |
|---|---|---|
| `openfda_pharmacovigilance` | `medication` (default `ibuprofeno`) | Drafts the openFDA call and how to interpret it |
| `osm_real_pharmacies` | `location` (default `Madrid`) | Drafts the OpenStreetMap call and its fallback |
| `internet_lookup` | `medication`, `location` | Chains both APIs together with the local tools |

```bash
curl -s http://127.0.0.1:8000/prompts | jq '.prompts[].name'
```

---

## 6. Gradio interface (`app.py`)

Standalone service (`orientador-web`), by default `http://127.0.0.1:7860`:

- `GET /` → chat interface (no login).
- Uses the same `ChatUseCase` (same tools and prompts) as the MCP server.

---

## 7. Known limitations

- Session history is **in memory**: it is lost when the process restarts.
- In demo mode (without `GOOGLE_API_KEY`) tool routing is done by a simulated
  LLM matching keywords; with the key, Gemini decides.
- External APIs may be down or overloaded: the tools warn and degrade instead
  of breaking the conversation.
