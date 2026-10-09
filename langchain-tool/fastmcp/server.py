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
    "OrientadorMedicamentosHexagonal",
    # Sin autenticación: el servidor es público para que cualquier cliente MCP
    # (Claude, OpenCode, Cursor, ChatGPT Connectors, scripts...) pueda consumirlo.
    instructions=(
        "Agente bilingüe (ES/EN) de orientación sobre medicamentos. "
        "Expone 10 tools (2 de ellas consumen APIs de internet: openFDA y "
        "OpenStreetMap), 6 resources con los datasets y 3 prompts. "
        "Orientación general: no diagnostica ni receta."
    ),
)

# Register the original tools so FastMCP knows about them
from tools import TOOLS as ORIGINAL_TOOLS
for tool in ORIGINAL_TOOLS:
    func = getattr(tool, 'func', tool)
    mcp.tool(func)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_TOTALES = {t.name: t.description for t in ORIGINAL_TOOLS}


# -----------------------------------------------------------
# RESOURCES (6): datasets del proyecto como recursos MCP
# -----------------------------------------------------------

def _leer_dataset(nombre: str) -> str:
    return (DATA_DIR / nombre).read_text(encoding="utf-8")


@mcp.resource(
    "medicamentos://dataset",
    name="medicamentos.json",
    description="Base local de 18 medicamentos comunes: ficha, dosis, advertencias "
                "y uso en embarazo/lactancia (datos educativos de muestra).",
    mime_type="application/json",
)
def resource_medicamentos() -> str:
    return _leer_dataset("medicamentos.json")


@mcp.resource(
    "sintomas://dataset",
    name="sintomas.json",
    description="24 grupos de síntomas con causas posibles, medicación OTC, "
                "señales de alarma y consejo general.",
    mime_type="application/json",
)
def resource_sintomas() -> str:
    return _leer_dataset("sintomas.json")


@mcp.resource(
    "interacciones://dataset",
    name="interacciones.json",
    description="26 interacciones frecuentes entre medicamentos (o fármaco + "
                "alcohol/pomelo) con severidad y recomendación.",
    mime_type="application/json",
)
def resource_interacciones() -> str:
    return _leer_dataset("interacciones.json")


@mcp.resource(
    "contraindicaciones://dataset",
    name="contraindicaciones.json",
    description="12 condiciones clínicas (embarazo, HTA, riñón...) con medicamentos "
                "a evitar, a usar con precaución y alternativas seguras.",
    mime_type="application/json",
)
def resource_contraindicaciones() -> str:
    return _leer_dataset("contraindicaciones.json")


@mcp.resource(
    "farmacias://dataset",
    name="farmacias.json",
    description="10 farmacias de muestra (datos simulados) para el modo sin red; "
                "para farmacias reales usa la tool buscar_farmacia_real (OpenStreetMap).",
    mime_type="application/json",
)
def resource_farmacias() -> str:
    return _leer_dataset("farmacias.json")


@mcp.resource(
    "orientador://guia",
    name="Guía de uso del agente",
    description="Catálogo de tools, prompts y resources del servidor, con las dos APIs "
                "de internet que consume (openFDA y OpenStreetMap) y sus límites.",
    mime_type="text/markdown",
)
def resource_guia() -> str:
    lineas = [
        "# Orientador de Medicamentos — guía rápida (ES/EN)",
        "",
        "Servidor MCP sin autenticación: 10 tools, 6 resources, 3 prompts.",
        "",
        "## Tools locales (datasets de data/)",
    ]
    for nombre, desc in _TOTALES.items():
        marca = " **[API internet]**" if nombre in (
            "consultar_farmacovigilancia", "buscar_farmacia_real") else ""
        lineas.append(f"- `{nombre}`{marca}: {(desc or '').strip().splitlines()[0]}")
    lineas += [
        "",
        "## APIs de internet que consume (nubes distintas, sin API key)",
        "- openFDA / FAERS (NIH): `https://api.fda.gov/drug/event.json` -> tool `consultar_farmacovigilancia`",
        "- OpenStreetMap: `https://nominatim.openstreetmap.org/search` + "
        "`https://overpass-api.de/api/interpreter` -> tool `buscar_farmacia_real`",
        "",
        "## Prompts MCP",
        "- `farmacovigilancia_openfda(medicamento)` -> redacta la llamada a openFDA",
        "- `farmacias_reales_osm(ubicacion)` -> redacta la llamada a OpenStreetMap",
        "- `consulta_internet(medicamento, ubicacion)` -> combina ambas APIs",
        "",
        "## Endpoints HTTP",
        "- `POST /chat`, `GET /history`, `GET /tools`, `GET /resources`, `GET /prompts`, `GET /`",
        "- MCP (JSON-RPC): `POST /mcp`",
        "",
        "⚠️ Orientación general, no sustituye al médico o farmacéutico. / "
        "⚠️ General guidance, does not replace your doctor or pharmacist.",
    ]
    return "\n".join(lineas)


# -----------------------------------------------------------
# PROMPTS (3): los dos primeros consumen las APIs de internet
# -----------------------------------------------------------

@mcp.prompt(
    name="farmacovigilancia_openfda",
    description="Prompt para consumir la API openFDA (NIH): notificaciones de "
                "reacciones adversas de un medicamento.",
)
def prompt_farmacovigilancia(medicamento: str = "ibuprofeno") -> str:
    """Redacta la petición exacta para que el agente llame a la tool openFDA."""
    return (
        f"Quiero consultar la farmacovigilancia de '{medicamento}' con datos reales. "
        f"Llama a la tool `consultar_farmacovigilancia` con nombre='{medicamento}' "
        f"(API internet openFDA/FAERS, sin autenticación) y resume: nº total de "
        f"notificaciones, muestra analizada, reacciones más frecuentes y desenlace. "
        f"Explica siempre que son reportes espontáneos (correlación ≠ causalidad) y "
        f"termina con el disclaimer de orientación general."
    )


@mcp.prompt(
    name="farmacias_reales_osm",
    description="Prompt para consumir las APIs de OpenStreetMap (Nominatim + Overpass): "
                "farmacias reales cerca de una ubicación.",
)
def prompt_farmacias(ubicacion: str = "Madrid") -> str:
    """Redacta la petición exacta para que el agente llame a la tool OpenStreetMap."""
    return (
        f"Busca farmacias REALES cerca de '{ubicacion}'. Llama a la tool "
        f"`buscar_farmacia_real` con ubicacion='{ubicacion}' (API internet "
        f"OpenStreetMap: Nominatim + Overpass, sin autenticación) y lista hasta 5 "
        f"resultados con distancia, dirección, horario y teléfono si consta. Si OpenStreetMap "
        f"no responde, indica el fallback a la tool local `buscar_farmacia` y recuerda "
        f"que el horario puede estar desactualizado (llamar antes de ir)."
    )


@mcp.prompt(
    name="consulta_internet",
    description="Combina las dos APIs de internet del servidor (openFDA + OpenStreetMap) "
                "en una única consulta de orientación.",
)
def prompt_consulta_internet(medicamento: str = "ibuprofeno", ubicacion: str = "Madrid") -> str:
    return (
        f"Prepara una orientación completa sobre '{medicamento}' para alguien en "
        f"'{ubicacion}': 1) llama a `consultar_farmacovigilancia` (openFDA) para las "
        f"reacciones adversas declaradas; 2) llama a `buscar_farmacia_real` "
        f"(OpenStreetMap) para localizar farmacias cercanas; 3) cruza el resultado con "
        f"las tools locales (ficha, interacciones, contraindicaciones) y responde en el "
        f"idioma del usuario, con disclaimer y sin recetar nada."
    )


# Recuento dinámico de tools (se recalcula al importar el módulo)
TOTAL_TOOLS = len(ORIGINAL_TOOLS)

# CORS abierto: permite consumir el servidor desde cualquier cliente/navegador
# (no hay autenticación, así que no hay credenciales que proteger).
# Nota: FastMCP.add_middleware() espera un Middleware de FastMCP (MCP), no uno
# de Starlette; el CORS de Starlette se inyecta en http_app(middleware=[...]).
CORS_MIDDLEWARE = [Middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)]


def build_app():
    """Starlette app del servidor MCP (HTTP JSON plano, sin sesión y con CORS)."""
    return mcp.http_app(
        json_response=True,      # respuestas JSON en vez de SSE
        stateless_http=True,     # sin handshakes de sesión: sirve a cualquier cliente
        middleware=CORS_MIDDLEWARE,
    )


# -----------------------------------------------------------
# Endpoints HTTP personalizados
# -----------------------------------------------------------

# Endpoint: chat principal - ejecuta el caso de uso
@mcp.custom_route(methods=["POST"], path="/chat")
async def chat_endpoint(request: Request):
    """POST /chat - Ejecuta el agente de orientación de medicamentos (bilingüe EN/ES).

    Cuerpo JSON esperado:
    {
        "input": "mensaje del usuario / user message",
        "session_id": "id_opcional",
        "language": "es|en|auto (opcional)"
    }

    Retorna la respuesta del agente con metadatos (incluye `language`).
    """
    session_id = "default_mcp_session"
    try:
        body = await request.json()
        user_input = body.get("input", "")
        session_id = body.get("session_id", "default_mcp_session")
        if not isinstance(user_input, str) or not user_input.strip():
            return JSONResponse({"error": "El campo 'input' debe ser texto no vacío."}, status_code=400)
        if not isinstance(session_id, str) or not session_id.strip():
            return JSONResponse({"error": "El campo 'session_id' debe ser texto no vacío."}, status_code=400)
        language = body.get("language")  # None = auto-detect
        if language not in (None, "auto", "es", "en"):
            return JSONResponse({"error": "'language' debe ser 'es', 'en' o 'auto'."}, status_code=400)

        # Ejecutar el caso de uso (business logic, bilingüe)
        result = _chat_use_case.execute(user_input, session_id, language=language)

        return JSONResponse(result)

    except Exception as e:
        return JSONResponse(
            {"error": str(e), "output": "Lo siento, hubo un error procesando tu mensaje. / Sorry, there was an error processing your message.",
             "session_id": session_id},
            status_code=500
        )


# Endpoint: obtener historial
@mcp.custom_route(methods=["GET"], path="/history")
async def history_endpoint(request: Request):
    """GET /history?session_id=x - Obtener historial de conversación."""
    session_id = request.query_params.get("session_id", "default_mcp_session")
    
    try:
        result = _chat_use_case.get_history(session_id)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# Endpoint: listar tools disponibles
@mcp.custom_route(methods=["GET"], path="/tools")
async def tools_endpoint(request: Request):
    """GET /tools - Listar tools disponibles con sus esquemas."""
    try:
        tool_descriptions = _tool_adapter.get_tool_descriptions()
        
        # Add schema info for each tool
        tools_with_schemas = []
        for desc in tool_descriptions:
            schema = _tool_adapter.get_tool_schema(desc["name"])
            tools_with_schemas.append({
                "nombre": desc["name"],
                "descripcion": desc["description"],
                "parametros": schema if schema else {}
            })
        
        return JSONResponse({
            "herramientas": tools_with_schemas,
            "total": len(tools_with_schemas)
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# Endpoint: listar resources disponibles (datasets + guía)
@mcp.custom_route(methods=["GET"], path="/resources")
async def resources_endpoint(request: Request):
    """GET /resources - Listar resources MCP publicados por el servidor."""
    try:
        recursos = await mcp.list_resources()
        plantillas = await mcp.list_resource_templates()
        return JSONResponse({
            "recursos": [
                {
                    "uri": str(r.uri),
                    "nombre": getattr(r, "name", None),
                    "descripcion": getattr(r, "description", None),
                    "mime_type": getattr(r, "mimeType", None),
                }
                for r in recursos
            ],
            "plantillas": [str(t.uriTemplate) for t in plantillas],
            "total": len(recursos),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# Endpoint: listar prompts disponibles (los 2 primeros consumen APIs de internet)
@mcp.custom_route(methods=["GET"], path="/prompts")
async def prompts_endpoint(request: Request):
    """GET /prompts - Listar prompts MCP publicados por el servidor."""
    try:
        prompts = await mcp.list_prompts()
        return JSONResponse({
            "prompts": [
                {
                    "nombre": p.name,
                    "descripcion": getattr(p, "description", None),
                    "argumentos": [
                        {"nombre": a.name, "descripcion": getattr(a, "description", None),
                         "obligatorio": getattr(a, "required", None)}
                        for a in (getattr(p, "arguments", None) or [])
                    ],
                }
                for p in prompts
            ],
            "total": len(prompts),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# Endpoint: estado raíz
@mcp.custom_route(methods=["GET"], path="/")
async def root_endpoint(request: Request):
    """GET / - Estado del servidor (bilingüe)."""
    recursos = await mcp.list_resources()
    prompts = await mcp.list_prompts()
    return JSONResponse({
        "mensaje": "Servidor FastMCP: Orientador de Medicamentos / Medication Guide (Arquitectura Hexagonal)",
        "message": "FastMCP Server: Medication Guide / Orientador de Medicamentos (Hexagonal Architecture)",
        "version": "3.0.0",
        "arquitectura": "hexagonal (puertos y adaptadores)",
        "languages": ["es", "en"],
        "language_mode": "auto-detect per message (override with POST /chat {\"language\": \"es\"|\"en\"})",
        "autenticacion": "ninguna (sin API key, sin login): endpoints abiertos",
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
        "apis_internet": [
            {"servicio": "openFDA / FAERS (NIH)", "tool": "consultar_farmacovigilancia",
             "url": "https://api.fda.gov/drug/event.json", "autenticacion": "ninguna"},
            {"servicio": "OpenStreetMap (Nominatim + Overpass)", "tool": "buscar_farmacia_real",
             "url": "https://nominatim.openstreetmap.org", "autenticacion": "ninguna"},
        ],
        "modo_llm": "real" if hasattr(_llm_adapter, 'get_model_name') and "Fake" not in type(_llm_adapter).__name__ else "simulado",
        "tools_total": TOTAL_TOOLS,
        "resources_total": len(recursos),
        "prompts_total": len(prompts),
    })


# -----------------------------------------------------------
# Punto de entrada
# -----------------------------------------------------------

def run_server() -> None:
    import uvicorn
    
    print("=" * 70)
    print("🚀 Servidor FastMCP: Orientador de Medicamentos (Hexagonal Architecture)")
    print("=" * 70)
    
    print(f"\nModo LLM: {'Gemini real' if 'Fake' not in type(_llm_adapter).__name__ else 'simulado (modo demo)'}")
    print(f"Modelo: {_llm_adapter.get_model_name()}")
    _descs = _tool_adapter.get_tool_descriptions()
    _first = _descs[0].get('nombre') or _descs[0].get('name', '?') if _descs else '?'
    print(f"Tools registradas: {_first} y {len(_descs)-1} más" if _descs else "Tools: 0")
    print()
    
    # HOST/PORT desde el entorno:
    # - Local: por defecto 127.0.0.1:8000 (no hace falta configurar nada).
    # - Despliegue (Render/Docker): HOST=0.0.0.0 y PORT lo inyecta Render.
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))

    print("Endpoints disponibles:")
    print("  GET  /                  -> estado del servidor")
    print("  GET  /tools             -> listar tools disponibles")
    print("  GET  /resources         -> listar resources MCP (datasets + guía)")
    print("  GET  /prompts           -> listar prompts MCP (openFDA y OpenStreetMap)")
    print("  POST /chat              -> ejecutar agente con input")
    print("  GET  /history?session_id=x -> obtener historial")
    print("  POST /mcp               -> JSON-RPC del protocolo MCP")
    print()
    print(f"Escuchando en: http://{host}:{port}")
    print()
    print("Arquitectura: Hexagonal (Puertos y Adaptadores)")
    print("Dependencias invertidas: dominio -> puertos -> adaptadores")
    print("=" * 70)

    # `stateless_http + json_response`: respuestas JSON planas y sin sesión
    # persistente, para que cualquier cliente (curl, SDK MCP, navegador,
    # conectores de chat) pueda consumir el endpoint sin handshakes extra.
    app = build_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
