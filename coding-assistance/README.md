# coding-assistance — Trazabilidad del desarrollo asistido por IA

Esta carpeta documenta **qué agentes/modelos/herramientas de IA se usaron** para
desarrollar el proyecto y **todos los prompts** enviados a un asistente de
código, tal y como pide el enunciado.

> **Política de secretos:** aquí **no se guardan API keys, tokens, contraseñas ni
> ningún otro secreto**. Cuando un prompt o una nota mencionan una variable como
> `GOOGLE_API_KEY`, lo hacen únicamente como nombre de variable opcional, nunca
> con su valor.

---

## 1. Agentes, modelos y herramientas utilizados

| Agente / herramienta | Modelo | Para qué se usó |
|---|---|---|
| **OpenCode** (CLI de agentes de código) | `mimo-v2.6-flash-free` (proveedor: `opencode`) | Agente principal de la sesión: lectura del código, edición de `tools.py`, `fastmcp/server.py`, `agent.py`, `domain/prompts.py`, creación de ficheros (`render.yaml`, `.python-version`, `Dockerfile`, skills, documentación) y ejecución de pruebas |
| **Herramienta `webfetch` (dentro de OpenCode)** | mismo modelo | Consulta de documentación externa para tomar decisiones de versión: *Render → Setting Your Python Version* y *Render → Blueprint YAML Reference*, y *OpenCode → Agent Skills* |
| **Herramientas locales de OpenCode** (`read`, `edit`, `write`, `shell`, `grep`, `glob`) | mismo modelo | Exploración del repositorio, cambios puntuales y ejecución de comandos de verificación (servidor MCP, cliente MCP, APIs externas) |
| **Skill `orientador-medicamentos`** (creada en esta sesión) | — | No es una herramienta de desarrollo, pero es el artefacto "skill para agentes" que exige el enunciado |

Modelo declarado por el harness: **MiMo-V2.6-Flash Free**, provider **opencode**,
id `mimo-v2.6-flash-free`.

### Qué se hizo **sin** asistencia de IA

- Los prompts enviados al propio agente desplegado (`POST /chat`, tools
  `consultar_farmacovigilancia` y `buscar_farmacia_real`) son **pruebas de la
  aplicación**, no prompts a un asistente de código, y por eso no se registran aquí.

---

## 2. Registro de prompts: `prompts.json`

[`prompts.json`](prompts.json) contiene un array `prompts` con **todas las
prompts** enviadas al asistente de código durante el desarrollo. Cada entrada
incluye como mínimo:

| Campo | Descripción |
|---|---|
| `timestamp` | ISO 8601 con huso horario (`-05:00`) |
| `agente_o_herramienta` | Agente o herramienta de IA que recibió el prompt |
| `proveedor` / `modelo` | Proveedor y modelo usados |
| `prompt` | Texto literal del prompt (sin secretos) |
| `purpose` | Para qué se envió |
| `artifacts` | Archivos resultantes o afectados |

### Cómo mantenerlo

1. Añade una entrada nueva por **cada** prompt enviado a un asistente de código.
2. No pegues en el prompt valores de claves: sustitúyelos por el nombre de la
   variable (`GOOGLE_API_KEY`, `TU_TOKEN`, …).
3. Mantén el mismo orden de campos para facilitar la revisión.

---

## 3. Cobertura y limitaciones

- El registro cubre la sesión del **2026-10-09**, en la que se alineó el proyecto
  con el enunciado (resources, tools de API, prompts MCP, despliegue, skill y
  documentación).
- Los commits anteriores (`2026-10-07` → `2026-10-08`: arquitectura hexagonal,
  soporte bilingüe y blueprint de Render) también se desarrollaron con asistencia
  de IA, pero **sus prompts no se guardaron en el momento**: queda anotado en el
  campo `notas` de `prompts.json` para no dar a entender que el histórico está
  completo.

---

## 4. Verificaciones realizadas en esta sesión

Para asegurar que lo entregado funciona al desplegar:

| Verificación | Resultado |
|---|---|
| Instalación y arranque de `mcp_server.py` | ✅ servidor en `127.0.0.1:8010` |
| `GET /` | ✅ `tools_total: 10`, `resources_total: 6`, `prompts_total: 3` |
| `GET /tools`, `GET /resources`, `GET /prompts` | ✅ listan 10 / 6 / 3 elementos |
| `POST /mcp` con el cliente MCP oficial (`initialize`, `list_tools`, `list_resources`, `list_prompts`, `read_resource`, `get_prompt`, `call_tool`) | ✅ todo responde |
| Tool `consultar_farmacovigilancia` (openFDA) | ✅ devuelve total, muestra y reacciones (ES y EN) |
| Tool `buscar_farmacia_real` (OpenStreetMap) | ✅ farmacias reales a <1 km de "Calle Mayor 1, Madrid" (3,6 s) y "Barcelona" (6,5 s), con reparto del presupuesto (`OVERPASS_MAX`/`NOMINATIM_MAX`) y *fallbacks* si Overpass se satura |
| Presupuestos de tiempo por tool | ✅ ninguna tool cuelga el chat: ≤22 s (API) y ≤20 s (geografía) aunque fallen todas las llamadas |
| `POST /chat` con el agente | ✅ responde usando las tools de API |
| CORS | ✅ `access-control-allow-origin: *` |
| Versiones (Python + `requirements.txt` fijados) | ✅ alineadas con el despliegue |
