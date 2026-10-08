"""FastMCP Server - Thin HTTP layer using hexagonal architecture.

This server module only handles HTTP routing and delegates all business logic
to the domain layer (use cases) through ports and adapters.
"""

from fastmcp import FastMCP
from starlette.responses import JSONResponse
from starlette.requests import Request

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

mcp = FastMCP("OrientadorMedicamentosHexagonal")

# Register the original tools so FastMCP knows about them
from tools import TOOLS as ORIGINAL_TOOLS
for tool in ORIGINAL_TOOLS:
    func = getattr(tool, 'func', tool)
    mcp.tool(func)


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


# Endpoint: estado raíz
@mcp.custom_route(methods=["GET"], path="/")
async def root_endpoint(request: Request):
    """GET / - Estado del servidor (bilingüe)."""
    return JSONResponse({
        "mensaje": "Servidor FastMCP: Orientador de Medicamentos / Medication Guide (Arquitectura Hexagonal)",
        "message": "FastMCP Server: Medication Guide / Orientador de Medicamentos (Hexagonal Architecture)",
        "version": "2.1.0",
        "arquitectura": "hexagonal (puertos y adaptadores)",
        "languages": ["es", "en"],
        "language_mode": "auto-detect per message (override with POST /chat {\"language\": \"es\"|\"en\"})",
        "endpoints": {
            "chat": "POST /chat",
            "history": "GET /history?session_id=x",
            "tools": "GET /tools",
            "status": "GET /"
        },
        "modo_llm": "real" if hasattr(_llm_adapter, 'get_model_name') and "Fake" not in type(_llm_adapter).__name__ else "simulado",
        "tools_total": 8
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
    
    print("Endpoints disponibles:")
    print("  GET  /                  -> estado del servidor")
    print("  GET  /tools             -> listar tools disponibles")
    print("  POST /chat  -> ejecutar agente con input")
    print("  GET  /history?session_id=x -> obtener historial")
    print()
    print("Arquitectura: Hexagonal (Puertos y Adaptadores)")
    print("Dependencias invertidas: dominio -> puertos -> adaptadores")
    print("=" * 70)
    
    # Run the server
    uvicorn.run(mcp.http_app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    run_server()
