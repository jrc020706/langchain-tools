# 🚀 Despliegue

El objetivo es que el proyecto quede **publicado y consumible desde cualquier
cliente, sin pedir autenticación**. Este documento recoge las opciones y las
versiones con las que está probado.

## Versiones (importante para evitar incidencias)

| Dónde | Versión |
|---|---|
| Python (local y despliegue) | **3.14** — fijado en `.python-version` (raíz del repo) |
| Dependencias | **fijadas** en `langchain-tool/requirements.txt` (`==`) |
| FastMCP / MCP | `fastmcp==4.1.0`, `mcp==2.3.0` |
| LangChain | `langchain==1.4.4`, `langchain-core==1.6.9`, `langchain-classic==1.0.8` |
| Gradio | `gradio==6.30.0` |

> Si cambias una versión, actualiza `requirements.txt` con `pip freeze | grep <paquete>`
> y vuelve a probar `python app.py` y `python mcp_server.py` antes de desplegar.

---

## Opción A — Render (la recomendada)

`render.yaml` está en la **raíz del repositorio** y usa `rootDir: langchain-tool`,
así que Render lo detecta solo al crear un Blueprint (no hace falta indicar rutas).

1. Sube el repo a GitHub.
2. En https://dashboard.render.com → **New → Blueprint** → conecta el repositorio.
3. Render crea dos servicios:

   | Servicio | `startCommand` | Expone |
   |---|---|---|
   | `orientador-web` | `python app.py` | Interfaz Gradio |
   | `orientador-mcp` | `python mcp_server.py` | API HTTP + servidor MCP |

4. Ambos usan `HOST=0.0.0.0` (Render inyecta `PORT`) y la versión de Python de
   `.python-version`.
5. **Opcional:** añade el secret `GOOGLE_API_KEY` en *Environment* de cada
   servicio para usar Gemini real. Sin él, los servicios arrancan igual en modo
   demo simulado → **el despliegue no exige credenciales**.

Resultado: dos URLs públicas tipo `https://orientador-web.onrender.com` y
`https://orientador-mcp.onrender.com`. Comprobación rápida:

```bash
curl -s https://orientador-mcp.onrender.com/ | jq '.tools_total, .resources_total, .prompts_total'
# 10 / 6 / 3
```

> Plan gratuito: se duermen tras ~15 min sin tráfico; la primera petición
> tarda ~1 min en despertarlos.

### Servicio creado a mano (sin Blueprint)

- Build command: `pip install -r requirements.txt`
- Start command: `python app.py` o `python mcp_server.py`
- Root directory: `langchain-tool`
- Env: `HOST=0.0.0.0` (y opcional `GOOGLE_API_KEY`)

---

## Opción B — Docker (cualquier otra plataforma)

`langchain-tool/Dockerfile` usa `python:3.14-slim` (misma versión que `.python-version`).

```bash
# desde la raíz del repo
docker build -t orientador ./langchain-tool

docker run -p 8000:8000 -e HOST=0.0.0.0 orientador                 # servidor MCP
docker run -p 7860:7860 -e HOST=0.0.0.0 orientador python app.py    # interfaz Gradio
```

Sirve igual en Railway, Fly.io, AWS App Runner, Cloud Run, etc.: solo necesitan
`HOST=0.0.0.0` y respetar `PORT`.

---

## Opción C — Túneles desde tu máquina (demo rápida)

```bash
# NGrok (https://ngrok.com): ngrok config add-authtoken TU_TOKEN
python mcp_server.py       # terminal 1
ngrok http 8000            # terminal 2 -> URL pública https://xxxx.ngrok.app

# Cloudflare (sin registro)
cloudflared tunnel --url http://localhost:8000
```

La interfaz Gradio es lo mismo con el puerto 7860.

---

## Autenticación

**No la hay, por diseño (requisito del proyecto):**

- Los endpoints HTTP (`/`, `/tools`, `/resources`, `/prompts`, `/chat`,
  `/history`, `/mcp`) son públicos.
- El protocolo MCP no exige cabeceras de auth ni OAuth.
- CORS permite cualquier origen (`access-control-allow-origin: *`).
- Las dos APIs externas (openFDA y OpenStreetMap) también son públicas y sin
  API key.
- `GOOGLE_API_KEY` solo la necesita el **servicio** para hablar con Gemini; el
  cliente final nunca la usa.

⚠️ Como el servicio es abierto, no guardes secretos en el código y vigila el uso
en los logs del proveedor.

---

## Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `render.yaml` no detectado | El archivo está en una subcarpeta | Debe estar en la raíz (aquí lo está) con `rootDir` |
| Error de ruedas/wheels al instalar | Versión de Python distinta | Comprueba `.python-version` = `3.14` y `PYTHON_VERSION` en Render |
| `Address already in use` | Puerto incorrecto | Usa `PORT` del entorno (Render lo inyecta) |
| Servicio en local no escucha fuera | `HOST=127.0.0.1` | Exporta `HOST=0.0.0.0` en remoto |
| `buscar_farmacia_real` devuelve aviso | Overpass saturado o sin red | Reintenta; el tool ya hace *fallback* a Nominatim y a `buscar_farmacia` |
| Respuestas "de mentira" | Falta `GOOGLE_API_KEY` | Modo demo (mismas tools, enrutado por palabras clave) |
| 502/504 en Render | El proceso tardó en arrancar | Revisa build logs; `pip install -r requirements.txt` debe ser el build command |
