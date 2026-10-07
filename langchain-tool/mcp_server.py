#!/usr/bin/env python3
"""
Servidor MCP para el agente de orientación de medicamentos.

Usa FastMCP para exponer las tools de LangChain y endpoints personalizados
usando el decorador @mcp.custom_route(path, methods).
"""

import os
from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.responses import JSONResponse
from starlette.requests import Request

# Cargar variables de entorno
load_dotenv()

# Importar tools del agente
from tools import TOOLS

# Importar la construcción del agente
from agent import executor, get_session_history, USE_REAL_LLM, MODEL_NAME, GOOGLE_API_KEY

# -----------------------------------------------------------
# Configuración del servidor FastMCP
# -----------------------------------------------------------

mcp = FastMCP("OrientadorMedicamentos")

# Registrar tools: FastMCP espera la función .func desde StructuredTool
for tool in TOOLS:
    func = getattr(tool, 'func', tool)
    mcp.tool(func)

# -----------------------------------------------------------
# Endpoints personalizados usando @mcp.custom_route
# -----------------------------------------------------------

# Endpoint: chat principal - ejecuta el agente LangChain (bilingüe EN/ES)
@mcp.custom_route(methods=["POST"], path="/chat")
async def chat_endpoint(request: Request):
    body = await request.json()
    user_input = body.get("input", "")
    session_id = body.get("session_id", "default_mcp_session")
    language = body.get("language")  # "es" | "en" | None (auto)

    historia = get_session_history(session_id)
    # run_agent autodetecta el idioma y añade el disclaimer correcto
    from agent import run_agent as _run
    respuesta = _run(user_input, session_id, language=language)

    try:
        from domain.i18n import detect_language as _det
        lang = language if language in ("es", "en") else _det(user_input)
    except Exception:
        lang = language if language in ("es", "en") else "es"

    return JSONResponse({"output": respuesta, "session_id": session_id, "language": lang})

# Endpoint: obtener historial
@mcp.custom_route(methods=["GET"], path="/history")
async def history_endpoint(request: Request):
    session_id = request.query_params.get("session_id", "default_mcp_session")
    history = get_session_history(session_id)
    mensajes = []
    for msg in history.messages:
        if hasattr(msg, 'type'):
            rol = "user" if msg.type == "human" else "assistant"
            mensajes.append({"rol": rol, "contenido": msg.content})
    return JSONResponse({"mensajes": mensajes, "session_id": session_id})

# Endpoint: listar tools disponibles
@mcp.custom_route(methods=["GET"], path="/tools")
async def tools_endpoint(request: Request):
    herramientas = []
    for tool in TOOLS:
        herramienta = {
            "nombre": tool.name,
            "descripcion": tool.description,
        }
        if hasattr(tool, 'args_schema') and tool.args_schema:
            try:
                herramienta["parametros"] = tool.args_schema.model_json_schema()
            except Exception:
                pass
        herramientas.append(herramienta)
    return JSONResponse({"herramientas": herramientas, "total": len(herramientas)})

# Endpoint: estado raíz
@mcp.custom_route(methods=["GET"], path="/")
async def root_endpoint(request: Request):
    return JSONResponse({
        "mensaje": "Servidor FastMCP: Orientador de Medicamentos / Medication Guide activo",
        "message": "FastMCP Server: Medication Guide active",
        "languages": ["es", "en"],
        "documentacion": "/docs",
        "tools_endpoint": "/tools",
        "chat_endpoint": "/chat (POST {input, session_id, language?: 'es'|'en'})"
    })

# -----------------------------------------------------------
# Punto de entrada
# -----------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("🚀 Servidor FastMCP: Orientador de Medicamentos")
    print("=" * 70)
    print(f"Modo LLM: {'Gemini real' if USE_REAL_LLM else 'simulado (modo demo)'}")
    print()
    print("Endpoints disponibles:")
    print("  GET  /                  -> estado del servidor")
    print("  GET  /tools             -> listar tools disponibles")
    print("  POST /chat  -> ejecutar agente con input")
    print("  GET  /history?session_id=x -> obtener historial")
    print()
    print("Servidor corriendo en: http://127.0.0.1:8000/mcp")
    print("=" * 70)
    
    mcp.run(transport='http')
    
    print("\nServidor MCP detenido.")
