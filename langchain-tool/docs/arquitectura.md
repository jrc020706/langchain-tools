# 🏗️ Arquitectura

## Visión general

```
                       ┌────────────────────────────────────────────┐
 clientes (sin auth)   │            langchain-tool/                │
 ────────────────────► │                                            │
  navegador (Gradio)   │  app.py ────────┐                          │
  curl (REST)          │  main.py ───────┤                          │
  agente (MCP)  ───────┼─ fastmcp/server.py (HTTP + MCP)            │
                       │                 │                          │
                       │                 ▼                          │
                       │      domain/use_cases/chat_use_case.py     │
                       │        (ReAct loop, bilingüe, disclaimer)  │
                       │                 │  depende de interfaces   │
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
                          Gemini (opcional)   data/*.json  +  2 APIs públicas
```

Patrón **hexagonal (puertos y adaptadores)**: el dominio no conoce a Gemini,
LangChain ni a los datasets; solo a los puertos (`ports/`). Los adaptadores
(`adapters/`) son los que tocan el mundo exterior.

## Capas

| Capa | Archivos | Responsabilidad |
|---|---|---|
| Presentación | `app.py` (Gradio), `main.py` (terminal), `fastmcp/server.py` (HTTP/MCP) | Entrada/salida, sin lógica de negocio |
| Aplicación | `domain/use_cases/chat_use_case.py` | Bucle ReAct (máx. 5 iteraciones), idioma y disclaimer |
| Dominio | `domain/models.py`, `domain/prompts.py`, `domain/i18n.py`, `domain/session_history.py` | Modelos, prompt del sistema, detección de idioma, historial |
| Puertos | `ports/llm_port.py`, `ports/tool_port.py`, `ports/memory_port.py` | Interfaces abstractas |
| Adaptadores | `adapters/llm_adapter.py`, `llm_adapter_fake.py`, `tool_adapter.py`, `memory_adapter.py` | Implementaciones concretas |
| Datos | `data/*.json` + `tools.py` | 8 tools locales y 2 tools de API |

## Flujo de una petición (MCP `POST /chat`)

1. `fastmcp/server.py` valida el cuerpo y llama a `ChatUseCase.execute`.
2. El caso de uso detecta el idioma (`domain/i18n`), recupera el historial de la
   sesión y monta `[system, …historial, usuario]`.
3. `LlmPort.bind_tools(tools)` devuelve el LLM «atado» a las 10 tools:
   - con `GOOGLE_API_KEY` → `ChatGoogleGenerativeAI` (Gemini decide),
   - sin key → `_FakeToolBinding` de `agent.py` (enrutado por palabras clave,
     útil para demo y para pruebas).
4. Mientras haya `tool_calls`, se ejecutan por `ToolPort.execute_tool` y los
   resultados vuelven como `ToolMessage` (bucle máx. 5 iteraciones).
5. Se garantiza el disclaimer del idioma y se persiste en `MemoryPort`.

## Las 10 tools

- **8 locales** (`tools.py`): leen `data/*.json` en memoria (carga al importar),
  normalizan sin tildes y comparan por palabras clave/alias.
- **2 de API** (las dos obligatorias de nubes distintas):
  - `consultar_farmacovigilancia` → **openFDA/FAERS** (`https://api.fda.gov/drug/event.json`).
    Mapea principio activo ES → genérico USAN, prueba varios campos exactos y
    resume total/muestra/reacciones/desenlace.
  - `buscar_farmacia_real` → **OpenStreetMap** (`nominatim` + `overpass`).
    Geocodifica, busca `amenity=pharmacy` en 3 km, calcula distancias y degrada
    con *fallbacks* (otros mirrors → Nominatim → `buscar_farmacia` local).

Ambas usan `requests` con `timeout=15`, `User-Agent` identificativo y **sin
autenticación**; cualquier fallo se traduce en un mensaje útil, nunca en una
excepción al cliente.

## Publicación MCP: tools, resources y prompts

`fastmcp/server.py` registra:

- **10 tools**: las de `tools.py` (`mcp.tool(...)`).
- **6 resources**: 5 datasets (`medicamentos://dataset`, …) y la guía
  `orientador://guia` (Markdown).
- **3 prompts**: `farmacovigilancia_openfda`, `farmacias_reales_osm` y
  `consulta_internet` (los dos primeros existen para consumir las APIs externas).

Además expone rutas REST de descubrimiento (`/tools`, `/resources`, `/prompts`)
para clientes que no hablen MCP.

## Memoria y sesiones

- Diccionario en memoria por `session_id` (`domain/session_history.py` y
  `adapters/memory_adapter.py`).
- Reinicio del proceso ⇒ historial limpio (por eso no hay estado que migrar).
- En Gradio se usa el `session_hash` del navegador.

## Modo demo sin API key

`_FakeToolBinding` imita la salida de un LLM con *function calling*: detecta
patrones (urgencias, interacciones, dosis, farmacias, APIs…) y devuelve
`tool_calls` reales, de modo que el bucle ReAct y las 10 tools se ejecutan
igual que con Gemini. Esto permite desplegar **sin credenciales**.
