"""FastMCP Server - Thin HTTP layer using hexagonal architecture.

This server module only handles HTTP routing and delegates all business logic
to the domain layer (use cases) through ports and adapters.
"""

from fastmcp import FastMCP
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.requests import Request

import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import domain use cases (business logic)
from domain.use_cases.chat_use_case import ChatUseCase

# Import ports (interfaces)
from ports.llm_port import LlmPort
from ports.tool_port import ToolPort
from ports.memory_port import MemoryPort

# Import adapters (concrete implementations)
from adapters.llm_adapter import create_llm_adapter, GeminiLlmAdapter, FakeGeminiAdapter
from adapters.tool_adapter import create_tool_adapter
from adapters.memory_adapter import create_memory_adapter


# -----------------------------------------------------------
# Initialize infrastructure (adapters) - singleton pattern
# -----------------------------------------------------------

# Create adapter instances (these are the "implementations" of the ports)
_llm_adapter: LlmPort = create_llm_adapter()
_tool_adapter: ToolPort = create_tool_adapter()
_memory_adapter: MemoryPort = create_memory_adapter()

# Create the use case (this is the "business logic" layer)
_chat_use_case: ChatUseCase = ChatUseCase(
    llm_port=_llm_adapter,
    tool_port=_tool_adapter,
    memory_port=_memory_adapter,
)


# -----------------------------------------------------------
# FastMCP server setup
# -----------------------------------------------------------

mcp = FastMCP(
    "MedicationAdvisorHexagonal",
    # No authentication: the server is public so any MCP client (Claude,
    # OpenCode, Cursor, ChatGPT Connectors, scripts...) can consume it.
    instructions=(
        "Bilingual (ES/EN) medication guidance agent. "
        "Exposes 10 tools (2 of them consume internet APIs: openFDA and "
        "OpenStreetMap), 6 resources with the datasets and 3 prompts. "
        "General guidance: it does not diagnose nor prescribe."
    ),
)

# Register the original tools so FastMCP knows about them
from tools import TOOLS as ORIGINAL_TOOLS
for tool in ORIGINAL_TOOLS:
    func = getattr(tool, 'func', tool)
    mcp.tool(func)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_TOOL_DESCRIPTIONS = {t.name: t.description for t in ORIGINAL_TOOLS}


# -----------------------------------------------------------
# RESOURCES (6): project datasets exposed as MCP resources
# -----------------------------------------------------------

def _read_dataset(filename: str) -> str:
    return (DATA_DIR / filename).read_text(encoding="utf-8")


@mcp.resource(
    "medications://dataset",
    name="medications.json",
    description="Local base of 18 common medicines: card, dosage, warnings "
                "and pregnancy/breastfeeding use (educational sample data).",
    mime_type="application/json",
)
def resource_medications() -> str:
    return _read_dataset("medications.json")


@mcp.resource(
    "symptoms://dataset",
    name="symptoms.json",
    description="24 symptom groups with possible causes, OTC medication, "
                "red flags and general advice.",
    mime_type="application/json",
)
def resource_symptoms() -> str:
    return _read_dataset("symptoms.json")


@mcp.resource(
    "interactions://dataset",
    name="interactions.json",
    description="26 common drug interactions (or drug + alcohol/grapefruit) "
                "with severity and recommendation.",
    mime_type="application/json",
)
def resource_interactions() -> str:
    return _read_dataset("interactions.json")


@mcp.resource(
    "contraindications://dataset",
    name="contraindications.json",
    description="12 clinical conditions (pregnancy, hypertension, kidney...) with "
                "medicines to avoid, to use with caution and safe alternatives.",
    mime_type="application/json",
)
def resource_contraindications() -> str:
    return _read_dataset("contraindications.json")


@mcp.resource(
    "pharmacies://dataset",
    name="pharmacies.json",
    description="10 sample pharmacies (simulated data) for offline mode; for real "
                "pharmacies use the find_real_pharmacy tool (OpenStreetMap).",
    mime_type="application/json",
)
def resource_pharmacies() -> str:
    return _read_dataset("pharmacies.json")


@mcp.resource(
    "medication-advisor://guide",
    name="Agent usage guide",
    description="Catalog of the server's tools, prompts and resources, with the two "
                "internet APIs it consumes (openFDA and OpenStreetMap) and their limits.",
    mime_type="text/markdown",
)
def resource_guide() -> str:
    lines = [
        "# Medication Advisor — quick guide (ES/EN)",
        "",
        "MCP server with no authentication: 10 tools, 6 resources, 3 prompts.",
        "",
        "## Local tools (data/ datasets)",
    ]
    for name, desc in _TOOL_DESCRIPTIONS.items():
        mark = " **[internet API]**" if name in (
            "query_pharmacovigilance", "find_real_pharmacy") else ""
        lines.append(f"- `{name}`{mark}: {(desc or '').strip().splitlines()[0]}")
    lines += [
        "",
        "## Internet APIs consumed (different clouds, no API key)",
        "- openFDA / FAERS (NIH): `https://api.fda.gov/drug/event.json` -> tool `query_pharmacovigilance`",
        "- OpenStreetMap: `https://nominatim.openstreetmap.org/search` + "
        "`https://overpass-api.de/api/interpreter` -> tool `find_real_pharmacy`",
        "",
        "## MCP prompts",
        "- `openfda_pharmacovigilance(medication)` -> drafts the openFDA call",
        "- `osm_real_pharmacies(location)` -> drafts the OpenStreetMap call",
        "- `internet_lookup(medication, location)` -> combines both APIs",
        "",
        "## HTTP endpoints",
        "- `POST /chat`, `GET /history`, `GET /tools`, `GET /resources`, `GET /prompts`, `GET /`",
        "- MCP (JSON-RPC): `POST /mcp`",
        "",
        "⚠️ Orientación general, no sustituye al médico o farmacéutico. / "
        "⚠️ General guidance, does not replace your doctor or pharmacist.",
    ]
    return "\n".join(lines)


# -----------------------------------------------------------
# PROMPTS (3): the first two consume the internet APIs
# -----------------------------------------------------------

@mcp.prompt(
    name="openfda_pharmacovigilance",
    description="Prompt to consume the openFDA API (NIH): adverse-reaction "
                "reports for a medicine.",
)
def prompt_openfda_pharmacovigilance(medication: str = "ibuprofeno") -> str:
    """Drafts the exact request for the agent to call the openFDA tool."""
    return (
        f"I want to check the pharmacovigilance of '{medication}' with real data. "
        f"Call the tool `query_pharmacovigilance` with name='{medication}' "
        f"(openFDA/FAERS internet API, no authentication) and summarise: total "
        f"number of reports, sample analysed, most frequent reactions and outcome. "
        f"Always explain that these are spontaneous reports (correlation does not "
        f"imply causation) and end with the general-guidance disclaimer."
    )


@mcp.prompt(
    name="osm_real_pharmacies",
    description="Prompt to consume the OpenStreetMap APIs (Nominatim + Overpass): "
                "real pharmacies near a location.",
)
def prompt_osm_pharmacies(location: str = "Madrid") -> str:
    """Drafts the exact request for the agent to call the OpenStreetMap tool."""
    return (
        f"Find REAL pharmacies near '{location}'. Call the tool "
        f"`find_real_pharmacy` with location='{location}' (OpenStreetMap "
        f"internet API: Nominatim + Overpass, no authentication) and list up to 5 "
        f"results with distance, address, opening hours and phone if available. If OpenStreetMap "
        f"does not respond, mention the fallback to the local tool `find_pharmacy` and remind "
        f"that opening hours may be outdated (call before going)."
    )


@mcp.prompt(
    name="internet_lookup",
    description="Combines the server's two internet APIs (openFDA + OpenStreetMap) "
                "into a single guidance query.",
)
def prompt_internet_lookup(medication: str = "ibuprofeno", location: str = "Madrid") -> str:
    return (
        f"Prepare full guidance about '{medication}' for someone in '{location}': "
        f"1) call `query_pharmacovigilance` (openFDA) for the reported adverse "
        f"reactions; 2) call `find_real_pharmacy` (OpenStreetMap) to locate nearby "
        f"pharmacies; 3) cross-check the results with the local tools (medicine card, "
        f"interactions, contraindications) and answer in the user's language, "
        f"with the disclaimer and without prescribing anything."
    )


# Dynamic tool count (recomputed at module import)
TOTAL_TOOLS = len(ORIGINAL_TOOLS)

# Open CORS: allows consuming the server from any client/browser
# (there is no authentication, so there are no credentials to protect).
# Note: FastMCP.add_middleware() expects a FastMCP (MCP) Middleware, not a
# Starlette one; Starlette CORS is injected via http_app(middleware=[...]).
CORS_MIDDLEWARE = [Middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)]


def build_app():
    """Starlette app for the MCP server (plain JSON HTTP, stateless, with CORS)."""
    return mcp.http_app(
        json_response=True,      # plain JSON responses instead of SSE
        stateless_http=True,     # no session handshakes: serves any client
        middleware=CORS_MIDDLEWARE,
    )


# -----------------------------------------------------------
# Custom HTTP endpoints
# -----------------------------------------------------------

# Endpoint: main chat - runs the use case
@mcp.custom_route(methods=["POST"], path="/chat")
async def chat_endpoint(request: Request):
    """POST /chat - Runs the medication guidance agent (bilingual EN/ES).

    Expected JSON body:
    {
        "input": "user message",
        "session_id": "optional_id",
        "language": "es|en|auto (optional)"
    }

    Returns the agent answer with metadata (includes `language`).
    """
    session_id = "default_mcp_session"
    try:
        body = await request.json()
        user_input = body.get("input", "")
        session_id = body.get("session_id", "default_mcp_session")
        if not isinstance(user_input, str) or not user_input.strip():
            return JSONResponse({"error": "The 'input' field must be non-empty text."}, status_code=400)
        if not isinstance(session_id, str) or not session_id.strip():
            return JSONResponse({"error": "The 'session_id' field must be non-empty text."}, status_code=400)
        language = body.get("language")  # None = auto-detect
        if language not in (None, "auto", "es", "en"):
            return JSONResponse({"error": "'language' must be 'es', 'en' or 'auto'."}, status_code=400)

        # Run the use case (business logic, bilingual)
        result = _chat_use_case.execute(user_input, session_id, language=language)

        return JSONResponse(result)

    except Exception as e:
        return JSONResponse(
            {"error": str(e), "output": "Lo siento, hubo un error procesando tu mensaje. / Sorry, there was an error processing your message.",
             "session_id": session_id},
            status_code=500
        )


# Endpoint: conversation history
@mcp.custom_route(methods=["GET"], path="/history")
async def history_endpoint(request: Request):
    """GET /history?session_id=x - Get the conversation history."""
    session_id = request.query_params.get("session_id", "default_mcp_session")

    try:
        result = _chat_use_case.get_history(session_id)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# Endpoint: list available tools
@mcp.custom_route(methods=["GET"], path="/tools")
async def tools_endpoint(request: Request):
    """GET /tools - List available tools with their schemas."""
    try:
        tool_descriptions = _tool_adapter.get_tool_descriptions()

        # Add schema info for each tool
        tools_with_schemas = []
        for desc in tool_descriptions:
            schema = _tool_adapter.get_tool_schema(desc["name"])
            tools_with_schemas.append({
                "name": desc["name"],
                "description": desc["description"],
                "parameters": schema if schema else {}
            })

        return JSONResponse({
            "tools": tools_with_schemas,
            "total": len(tools_with_schemas)
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# Endpoint: list available resources (datasets + guide)
@mcp.custom_route(methods=["GET"], path="/resources")
async def resources_endpoint(request: Request):
    """GET /resources - List the MCP resources published by the server."""
    try:
        resources = await mcp.list_resources()
        templates = await mcp.list_resource_templates()
        return JSONResponse({
            "resources": [
                {
                    "uri": str(r.uri),
                    "name": getattr(r, "name", None),
                    "description": getattr(r, "description", None),
                    "mime_type": getattr(r, "mimeType", None),
                }
                for r in resources
            ],
            "templates": [str(t.uriTemplate) for t in templates],
            "total": len(resources),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# Endpoint: list available prompts (the first two consume internet APIs)
@mcp.custom_route(methods=["GET"], path="/prompts")
async def prompts_endpoint(request: Request):
    """GET /prompts - List the MCP prompts published by the server."""
    try:
        prompts = await mcp.list_prompts()
        return JSONResponse({
            "prompts": [
                {
                    "name": p.name,
                    "description": getattr(p, "description", None),
                    "arguments": [
                        {"name": a.name, "description": getattr(a, "description", None),
                         "required": getattr(a, "required", None)}
                        for a in (getattr(p, "arguments", None) or [])
                    ],
                }
                for p in prompts
            ],
            "total": len(prompts),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# Endpoint: root status
@mcp.custom_route(methods=["GET"], path="/")
async def root_endpoint(request: Request):
    """GET / - Server status."""
    resources = await mcp.list_resources()
    prompts = await mcp.list_prompts()
    return JSONResponse({
        "message": "FastMCP Server: Medication Advisor / Orientador de Medicamentos (Hexagonal Architecture)",
        "version": "3.1.0",
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
            {"service": "openFDA / FAERS (NIH)", "tool": "query_pharmacovigilance",
             "url": "https://api.fda.gov/drug/event.json", "authentication": "none"},
            {"service": "OpenStreetMap (Nominatim + Overpass)", "tool": "find_real_pharmacy",
             "url": "https://nominatim.openstreetmap.org", "authentication": "none"},
        ],
        "llm_mode": "real" if hasattr(_llm_adapter, 'get_model_name') and "Fake" not in type(_llm_adapter).__name__ else "simulated",
        "tools_total": TOTAL_TOOLS,
        "resources_total": len(resources),
        "prompts_total": len(prompts),
    })


# -----------------------------------------------------------
# Entry point
# -----------------------------------------------------------

def run_server() -> None:
    import uvicorn

    print("=" * 70)
    print("🚀 FastMCP Server: Medication Advisor (Hexagonal Architecture)")
    print("=" * 70)

    print(f"\nLLM mode: {'real Gemini' if 'Fake' not in type(_llm_adapter).__name__ else 'simulated (demo mode)'}")
    print(f"Model: {_llm_adapter.get_model_name()}")
    _descs = _tool_adapter.get_tool_descriptions()
    _first = _descs[0].get('name', '?') if _descs else '?'
    print(f"Registered tools: {_first} and {len(_descs)-1} more" if _descs else "Tools: 0")
    print()

    # HOST/PORT from the environment:
    # - Local: default 127.0.0.1:8000 (nothing to configure).
    # - Deployment (Render/Docker): HOST=0.0.0.0 and PORT injected by Render.
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))

    print("Available endpoints:")
    print("  GET  /                  -> server status")
    print("  GET  /tools             -> list available tools")
    print("  GET  /resources         -> list MCP resources (datasets + guide)")
    print("  GET  /prompts           -> list MCP prompts (openFDA and OpenStreetMap)")
    print("  POST /chat              -> run the agent with input")
    print("  GET  /history?session_id=x -> get the history")
    print("  POST /mcp               -> MCP protocol JSON-RPC")
    print()
    print(f"Listening on: http://{host}:{port}")
    print()
    print("Architecture: Hexagonal (Ports and Adapters)")
    print("Inverted dependencies: domain -> ports -> adapters")
    print("=" * 70)

    # `stateless_http + json_response`: flat JSON responses with no persistent
    # session, so any client (curl, MCP SDK, browser, chat connectors) can
    # consume the endpoint without extra handshakes.
    app = build_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
