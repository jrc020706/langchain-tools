# 📡 API y protocolo MCP

El servidor (`python mcp_server.py`) expone la misma funcionalidad por dos
caminos: **HTTP/REST** (fácil de probar con `curl`) y **MCP** (para agentes y
clientes compatibles). **Ninguno requiere autenticación**: sin API key, sin
login, sin cabeceras especiales. CORS está abierto (`*`) para uso desde
cualquier navegador o cliente.

- Local: `http://127.0.0.1:8000`
- Despliegue: `https://orientador-mcp.onrender.com` (o la URL que asigne tu proveedor)

---

## 1. Endpoints REST

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/` | Estado del servidor (bilingüe), conteos y APIs usadas |
| `GET` | `/tools` | Lista las 10 tools con descripción y esquema JSON |
| `GET` | `/resources` | Lista los 6 resources MCP |
| `GET` | `/prompts` | Lista los 3 prompts MCP con sus argumentos |
| `POST` | `/chat` | Ejecuta el agente (memoria por `session_id`) |
| `GET` | `/history?session_id=x` | Devuelve el historial de una sesión |
| `POST` | `/mcp` | Endpoint JSON-RPC del protocolo MCP |

### `GET /`

```bash
curl -s https://orientador-mcp.onrender.com/
```

Respuesta (abreviada):

```json
{
  "version": "3.0.0",
  "autenticacion": "ninguna (sin API key, sin login): endpoints abiertos",
  "apis_internet": [
    {"servicio": "openFDA / FAERS (NIH)", "tool": "consultar_farmacovigilancia", "autenticacion": "ninguna"},
    {"servicio": "OpenStreetMap (Nominatim + Overpass)", "tool": "buscar_farmacia_real", "autenticacion": "ninguna"}
  ],
  "tools_total": 10,
  "resources_total": 6,
  "prompts_total": 3
}
```

### `POST /chat`

Cuerpo:

```json
{
  "input": "¿Qué dosis de paracetamol le doy a un niño de 22 kg?",
  "session_id": "demo",
  "language": "es"
}
```

- `input` *(obligatorio)*: mensaje del usuario (ES o EN).
- `session_id` *(opcional)*: reutilízalo para mantener contexto.
- `language` *(opcional)*: `"es"`, `"en"` o `"auto"` (por defecto autodetecta).

Respuesta:

```json
{
  "output": "Dosis orientativa de paracetamol para 22 kg: 330 mg por toma …",
  "session_id": "demo",
  "language": "es",
  "tool_calls": [{"name": "calcular_dosis", "args": {"medicamento": "paracetamol", "peso_kg": 22}}],
  "message_count": 2
}
```

Errores: `400` si `input`/`language` no son válidos; `500` con `{"error": …}` si
algo falla por dentro.

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"input":"busca farmacias reales en Madrid","session_id":"demo"}'
```

---

## 2. Protocolo MCP (`POST /mcp`)

El servidor FastMCP registra **tools**, **resources** y **prompts** bajo la ruta
MCP `/mcp`. Arranca en modo `stateless` con respuestas JSON planas (sin SSE), lo
que simplifica clientes simples (curl, SDKs, conectores de chat).

### Configuración en un cliente MCP

```json
{
  "mcpServers": {
    "orientador-medicamentos": {
      "type": "http",
      "url": "https://orientador-mcp.onrender.com/mcp"
    }
  }
}
```

No se necesitan cabeceras de autorización.

### Ejemplo con el SDK oficial de Python

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
            out = await s.call_tool("consultar_farmacovigilancia", {"nombre": "ibuprofeno"})
            print(out.content[0].text)

asyncio.run(main())
```

### Métodos soportados

| Método | Qué devuelve |
|---|---|
| `initialize` / `tools/list` | las 10 tools con sus esquemas |
| `tools/call` | ejecuta una tool (p. ej. `buscar_farmacia_real`) |
| `resources/list` | los 6 resources |
| `resources/read` | contenido del dataset (JSON) o de la guía (Markdown) |
| `prompts/list` | los 3 prompts |
| `prompts/get` | el mensaje del prompt renderizado con sus argumentos |

---

## 3. Tools

### 3.1 Locales (datasets de `data/`)

`analizar_sintomas`, `buscar_medicamento`, `calcular_dosis`,
`verificar_interaccion`, `consultar_contraindicacion`, `evaluar_urgencia`,
`buscar_farmacia`, `calcular`.

Todas aceptan el parámetro opcional `language` (`"es"`, `"en"` o `"auto"`) y
devuelven texto plano terminado en el disclaimer del idioma.

### 3.2 `consultar_farmacovigilancia` — API internet #1 (openFDA)

- **Servicio:** openFDA / FAERS — `https://api.fda.gov/drug/event.json` (NIH, EE. UU.)
- **Autenticación:** ninguna (API pública sin API key).
- **Parámetros:** `nombre` (principio activo o marca), `language`.
- **Qué hace:** traduce el nombre local al genérico USAN (p. ej. `paracetamol` →
  `acetaminophen`), prueba varios campos exactos (`generic_name`,
  `medicinalproduct`, `brand_name`) y resume: total de notificaciones, muestra
  analizada, reacciones más frecuentes y desenlace.
- **Semántica:** reportes **espontáneos**; correlación ≠ causalidad y hay
  infrarregistro. El tool lo indica siempre en la salida.

```bash
curl -s -X POST http://127.0.0.1:8000/chat -H 'Content-Type: application/json' \
  -d '{"input":"¿Qué efectos adversos se han notificado de ibuprofeno?","language":"es"}'
```

### 3.3 `buscar_farmacia_real` — API internet #2 (OpenStreetMap)

- **Servicios:** `https://nominatim.openstreetmap.org/search` (geocodificación) y
  `https://overpass-api.de/api/interpreter` (puntos `amenity=pharmacy`), con
  mirrors de respaldo (`overpass.private.coffee`, `overpass.kumi.systems`).
- **Autenticación:** ninguna; solo un `User-Agent` identificativo (lo exige la
  política de uso de OSM, no es una credencial).
- **Parámetros:** `ubicacion` (ciudad, barrio o dirección), `language`.
- **Qué hace:** geocodifica → busca farmacias en un radio de 3 km → calcula
  distancias (haversine) → devuelve las 5 más cercanas con dirección, teléfono y
  horario. Si Overpass está saturado, hace *fallback* a una búsqueda directa en
  Nominatim y reintenta Overpass; si no hay red, sugiere `buscar_farmacia`
  (datos locales).

```bash
curl -s -X POST http://127.0.0.1:8000/chat -H 'Content-Type: application/json' \
  -d '{"input":"farmacias reales cerca de Barcelona","language":"es"}'
```

---

## 4. Resources

| URI | MIME | Contenido |
|---|---|---|
| `medicamentos://dataset` | `application/json` | 18 medicamentos con ficha completa |
| `sintomas://dataset` | `application/json` | 24 grupos de síntomas |
| `interacciones://dataset` | `application/json` | 26 interacciones |
| `contraindicaciones://dataset` | `application/json` | 12 condiciones clínicas |
| `farmacias://dataset` | `application/json` | 10 farmacias simuladas |
| `orientador://guia` | `text/markdown` | Guía de tools/prompts/endpoints y APIs |

```bash
curl -s http://127.0.0.1:8000/resources | jq '.recursos[].uri'
```

---

## 5. Prompts

| Prompt | Argumentos | Uso |
|---|---|---|
| `farmacovigilancia_openfda` | `medicamento` (default `ibuprofeno`) | Redacta la llamada a openFDA y cómo interpretarla |
| `farmacias_reales_osm` | `ubicacion` (default `Madrid`) | Redacta la llamada a OpenStreetMap y su fallback |
| `consulta_internet` | `medicamento`, `ubicacion` | Encadena ambas APIs con las tools locales |

```bash
curl -s http://127.0.0.1:8000/prompts | jq '.prompts[].nombre'
```

---

## 6. Interfaz Gradio (`app.py`)

Servicio independiente (`orientador-web`), por defecto `http://127.0.0.1:7860`:

- `GET /` → interfaz de chat (sin login).
- Usa el mismo `ChatUseCase` (mismas tools y prompts) que el servidor MCP.

---

## 7. Límites conocidos

- El historial de sesión está **en memoria**: se pierde al reiniciar el proceso.
- En modo demo (sin `GOOGLE_API_KEY`) el enrutado de tools lo hace un LLM
  simulado por palabras clave; con la key, decide Gemini.
- Las APIs externas pueden estar caídas o saturadas: las tools avisan y degradan
  en lugar de romper la conversación.
