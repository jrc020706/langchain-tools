# 💊 Agente de orientación de medicamentos (LangChain + Gemini + MCP)

Agente conversacional bilingüe (ES/EN) que orienta sobre medicamentos según síntomas:
analiza síntomas, da fichas de medicamentos, calcula dosis pediátricas por peso,
revisa interacciones y contraindicaciones, hace triaje de urgencia, consulta
**farmacovigilancia real (openFDA)** y busca **farmacias reales (OpenStreetMap)**.

> ⚠️ Orientación general educativa: **no diagnostica ni receta**. Ante señales de
> alarma (dolor torácico, dificultad para respirar, sangrado abundante, pérdida de
> conciencia) llama al **112**.

---

## Requisitos del proyecto y cómo los cumple

| Requisito | Dónde se cumple |
|---|---|
| Al menos **3 resources** | 6 resources MCP (`GET /resources`): 5 datasets JSON + 1 guía Markdown |
| Al menos **5 tools** (2 de APIs de internet de **nubes distintas**) | 10 tools; `consultar_farmacovigilancia` → **openFDA/FAERS (NIH)** y `buscar_farmacia_real` → **OpenStreetMap (Nominatim + Overpass)** |
| Al menos **2 prompts** para consumir esas APIs | 3 prompts MCP (`GET /prompts`): `farmacovigilancia_openfda`, `farmacias_reales_osm`, `consulta_internet` |
| **Desplegado y consumible desde cualquier cliente** | `render.yaml` en la raíz del repo (2 servicios) + `Dockerfile`; endpoint MCP HTTP `POST /mcp` y REST `POST /chat`, con CORS `*` y respuestas JSON planas |
| **Sin autenticación** | Ningún endpoint pide usuario, contraseña ni API key; `GOOGLE_API_KEY` es opcional (sin ella funciona en modo demo) |
| Al menos **1 skill para agentes** | [`skills/orientador-medicamentos/SKILL.md`](../skills/orientador-medicamentos/SKILL.md) (enlazada en `.opencode/skills/` y `.claude/skills/`) |
| **Documentación** | Este README + [`docs/`](docs/) (`api.md`, `despliegue.md`, `arquitectura.md`) |
| Trazabilidad de desarrollo con IA | [`../coding-assistance/README.md`](../coding-assistance/README.md) y [`../coding-assistance/prompts.json`](../coding-assistance/prompts.json) |

---

## Estructura

```
langchain-tools/                    # raíz del repositorio
├── render.yaml                     # Blueprint de Render (2 servicios, rootDir: langchain-tool)
├── .python-version                 # 3.14 -> misma versión en local y en despliegue
├── skills/orientador-medicamentos/ # skill de agente (SKILL.md)
├── .opencode/skills/…  y  .claude/skills/…   # enlaces para auto-descubrimiento
├── coding-assistance/              # trazabilidad del asistente de código
└── langchain-tool/
    ├── agent.py                    # agente: Gemini + AgentExecutor + memoria por sesión
    ├── tools.py                    # las 10 tools (8 locales + 2 que consumen APIs)
    ├── app.py                      # interfaz web Gradio (http://localhost:7860)
    ├── main.py                     # chat interactivo por terminal
    ├── fastmcp/server.py           # servidor MCP HTTP: tools + resources + prompts
    ├── mcp_server.py               # alias de arranque de FastMCP
    ├── Dockerfile / .dockerignore  # despliegue alternativo en contenedor
    ├── data/
    │   ├── medicamentos.json       # 18 fármacos comunes en España
    │   ├── sintomas.json           # 24 grupos de síntomas
    │   ├── interacciones.json      # 26 interacciones frecuentes
    │   ├── contraindicaciones.json # 12 condiciones (embarazo, HTA, riñón…)
    │   └── farmacias.json          # 10 farmacias de muestra (simuladas)
    ├── docs/                       # documentación ampliada
    ├── .env.example                # plantilla de configuración
    ├── requirements.txt            # dependencias con versión fijada
    └── README.md                   # este archivo
```

## Instalación

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # opcional: pon tu GOOGLE_API_KEY (gratis en https://aistudio.google.com)
```

Las versiones de `requirements.txt` están **fijadas** a las probadas con
**Python 3.14** (la misma que fija `.python-version`), así que la instalación
local y la del despliegue resuelven lo mismo.

Sin API key funciona igual en **modo simulado** (demo).

## Uso

```bash
python main.py                 # chat interactivo por terminal
python app.py                  # interfaz web en http://localhost:7860
python mcp_server.py           # servidor MCP + API HTTP en http://localhost:8000
python fastmcp/server.py       # idéntico al anterior
```

En el chat de terminal escribe `/ayuda`, `/historial`, `/limpiar` o `/salir`.

---

## 🌐 Servidor MCP y API HTTP (sin autenticación)

`mcp_server.py` escucha por defecto en `127.0.0.1:8000` (en despliegue,
`HOST=0.0.0.0` y `PORT` lo inyecta el proveedor). Publica:

| Método | Ruta | Qué hace |
|---|---|---|
| `GET` | `/` | estado, conteos (`tools_total`, `resources_total`, `prompts_total`) y las APIs usadas |
| `GET` | `/tools` | las **10 tools** con sus esquemas |
| `GET` | `/resources` | los **6 resources** (URI, nombre, descripción) |
| `GET` | `/prompts` | los **3 prompts** con sus argumentos |
| `POST` | `/chat` | ejecuta el agente: `{"input", "session_id", "language"}` |
| `GET` | `/history?session_id=x` | historial de la sesión |
| `POST` | `/mcp` | **JSON-RPC del protocolo MCP** (tools, resources y prompts) |

Respuestas JSON planas (`stateless` + `json_response`) y **CORS `*`**, para que
cualquier cliente lo consuma: Claude, OpenCode, Cursor, ChatGPT Connectors,
`curl`, scripts Python/JS… **sin API key, sin login, sin cabeceras de auth.**

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"input":"¿Qué es el paracetamol?","session_id":"demo"}'
```

Para seguir una conversación, reutiliza el mismo `session_id`. El historial vive
en memoria y se pierde al detener el servidor.

Guía completa con ejemplos MCP y REST: [`docs/api.md`](docs/api.md).

---

## Las 10 tools

| # | Tool | Entrada → Salida | Fuente |
|---|---|---|---|
| 1 | `analizar_sintomas` | Texto libre → causas posibles + OTC + alarmas | `data/sintomas.json` |
| 2 | `buscar_medicamento` | Nombre comercial o activo → ficha completa | `data/medicamentos.json` + sugerencias difusas |
| 3 | `calcular_dosis` | Medicamento + peso kg → mg por toma e intervalo | Regla mg/kg en Python |
| 4 | `verificar_interaccion` | 2 fármacos → severidad + recomendación | `data/interacciones.json` |
| 5 | `consultar_contraindicacion` | Fármaco + condición → 🔴🟡🟢 + alternativas | `data/contraindicaciones.json` |
| 6 | `evaluar_urgencia` | Síntomas → 🟢 autocuidado / 🟡 médico / 🔴 112 | Reglas de triaje |
| 7 | `buscar_farmacia` | Ubicación → farmacias (datos simulados) | `data/farmacias.json` |
| 8 | `calcular` | Expresión → resultado | `numexpr` (parser seguro) |
| 9 | `consultar_farmacovigilancia` | Fármaco → casos, reacciones frecuentes y desenlace | 🔵 **API internet #1:** openFDA/FAERS (NIH) |
| 10 | `buscar_farmacia_real` | Ubicación → farmacias reales con distancia, dirección y horario | 🟢 **API internet #2:** OpenStreetMap (Nominatim + Overpass) |

Las dos últimas son las que **consumen APIs de internet**; son públicas, no
requieren autenticación y degradan con un aviso claro si la red falla
(`buscar_farmacia_real` cae en la tool local `buscar_farmacia`).

### Resources MCP (6)

| URI | Contenido |
|---|---|
| `medicamentos://dataset` | `medicamentos.json` completo |
| `sintomas://dataset` | `sintomas.json` completo |
| `interacciones://dataset` | `interacciones.json` completo |
| `contraindicaciones://dataset` | `contraindicaciones.json` completo |
| `farmacias://dataset` | `farmacias.json` (muestra simulada) |
| `orientador://guia` | Catálogo Markdown de tools/prompts/endpoints y de las APIs usadas |

### Prompts MCP (3)

| Prompt | Argumentos | Para qué |
|---|---|---|
| `farmacovigilancia_openfda` | `medicamento` | consume la API **openFDA** y explica cómo interpretar los reportes |
| `farmacias_reales_osm` | `ubicacion` | consume las APIs de **OpenStreetMap** y lista farmacias cercanas |
| `consulta_internet` | `medicamento`, `ubicacion` | encadena ambas APIs en una sola orientación |

---

## 🚀 Despliegue

Todo está preparado para desplegar **sin tocar código**:

- **`render.yaml` en la raíz del repo** con `rootDir: langchain-tool` → Render lo
  detecta automáticamente al crear un Blueprint (antes estaba dentro de la carpeta
  y había que indicarlo a mano).
- **`.python-version` = `3.14`** en la raíz → la misma versión de Python en local y
  en Render (sin problemas de ruedas/wheels al instalar).
- **`requirements.txt` con versiones fijadas** → build reproducible.
- **`Dockerfile`** por si prefieres cualquier otra plataforma (Railway, Fly, AWS…).

Pasos en Render: sube el repo a GitHub → https://dashboard.render.com →
**New → Blueprint** → conecta el repo → crea los dos servicios → (opcional)
añade el secret `GOOGLE_API_KEY`. **Ningún servicio pide credenciales para ser
consumido.**

| Servicio | Arranque | Qué expone |
|---|---|---|
| `orientador-web` | `python app.py` | Interfaz Gradio |
| `orientador-mcp` | `python mcp_server.py` | API HTTP + servidor MCP |

Detalles, alternativas (Docker, NGrok, Cloudflare) y solución de problemas:
[`docs/despliegue.md`](docs/despliegue.md).

> Plan gratuito: los servicios se duermen tras ~15 min sin tráfico; la primera
> petición posterior tarda ~1 min en despertarlos.

---

## 🤖 Skill para agentes

[`skills/orientador-medicamentos/SKILL.md`](../skills/orientador-medicamentos/SKILL.md)
define cuándo y cómo un agente debe usar este servidor (endpoint, tools, prompts,
resources, reglas de seguridad y disclaimer). Está enlazada en
`.opencode/skills/` y `.claude/skills/`, así que OpenCode y Claude Code la
descubren automáticamente al trabajar dentro del repo.

---

## Seguridad

- El system prompt obliga a: orientación general (no diagnósticos ni recetas),
  no prescribir antibióticos ni fármacos con receta, derivar al 112 ante alarmas
  y cerrar cada respuesta con el disclaimer.
- Los endpoints son abiertos **a propósito** (requisito: sin autenticación): no
  exponen datos personales, solo datasets educativos y APIs públicas. No coloques
  secretos en el código; `GOOGLE_API_KEY` va en `.env` o en el gestor de secretos.
- Los datos de las APIs externas son de referencia: FAERS son notificaciones
  espontáneas y OpenStreetMap es colaborativo; conviene advertirlo siempre.

## 📚 Documentación

- [`docs/api.md`](docs/api.md) — endpoints HTTP y protocolo MCP (tools, resources, prompts).
- [`docs/despliegue.md`](docs/despliegue.md) — Render, Docker, túneles y versiones.
- [`docs/arquitectura.md`](docs/arquitectura.md) — arquitectura hexagonal y flujo de datos.
- [`../coding-assistance/`](../coding-assistance/README.md) — trazabilidad del desarrollo con IA.

## Ampliar

- **Más medicamentos/síntomas**: añade entradas a los JSON (sin tocar código).
- **Más APIs**: añade una tool en `tools.py` siguiendo el patrón de
  `consultar_farmacovigilancia` y regístrala en `TOOLS`.
- **Memoria persistente**: sustituye el dict de `agent.py` por Redis/Postgres.
