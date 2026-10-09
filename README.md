# langchain-tools — Orientador de Medicamentos (LangChain + Gemini + MCP)

Repositorio con un agente conversacional bilingüe (ES/EN) que orienta sobre
medicamentos, publicado como **servidor MCP + API HTTP sin autenticación** para
que cualquier cliente (agentes, conectores de chat, scripts) pueda consumirlo.

## Contenido del repositorio

| Ruta | Qué es |
|---|---|
| [`langchain-tool/`](langchain-tool/README.md) | El proyecto: agente, 10 tools, servidor MCP, interfaz Gradio, datos y Dockerfile |
| [`langchain-tool/docs/`](langchain-tool/docs) | Documentación: [`api.md`](langchain-tool/docs/api.md), [`despliegue.md`](langchain-tool/docs/despliegue.md), [`arquitectura.md`](langchain-tool/docs/arquitectura.md) |
| [`skills/orientador-medicamentos/`](skills/orientador-medicamentos/SKILL.md) | Skill para agentes (auto-descubierta por OpenCode/Claude Code) |
| [`render.yaml`](render.yaml) | Blueprint de Render (2 servicios, `rootDir: langchain-tool`) |
| [`.python-version`](.python-version) | Fija Python 3.14 en local y en despliegue |
| [`coding-assistance/`](coding-assistance/README.md) | Trazabilidad del desarrollo asistido por IA (agentes, modelos y prompts usados) |

## Arranque rápido

```bash
cd langchain-tool
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app.py            # interfaz web   → http://127.0.0.1:7860
python mcp_server.py     # API + MCP      → http://127.0.0.1:8000
```

Sin `GOOGLE_API_KEY` todo funciona en modo demo (no hace falta ninguna
credencial ni para usar el agente ni para consumir su API).

## Requisitos cubiertos

- ✅ **3 resources** → 6 resources MCP (`GET /resources`).
- ✅ **5 tools**, dos de ellas consumiendo APIs de internet de **nubes distintas**:
  **openFDA/FAERS** (`consultar_farmacovigilancia`) y **OpenStreetMap**
  (`buscar_farmacia_real`); en total 10 tools.
- ✅ **2 prompts** para consumir esas APIs → `farmacovigilancia_openfda` y
  `farmacias_reales_osm` (más `consulta_internet`), vía `GET /prompts`.
- ✅ **Desplegable y consumible desde cualquier cliente** → `render.yaml`
  (Blueprint), `Dockerfile`, endpoint MCP `POST /mcp`, REST `POST /chat`,
  respuestas JSON planas y CORS `*`.
- ✅ **Sin autenticación** → ningún endpoint pide usuario, contraseña ni API key.
- ✅ **Skill para agentes** → `skills/orientador-medicamentos/SKILL.md`.
- ✅ **Documentación** → READMEs, `langchain-tool/docs/` y esta página.
- ✅ **Trazabilidad de IA** → `coding-assistance/README.md` + `prompts.json`.

## Seguridad

Orientación general con fines educativos: no diagnostica ni receta. Ante señales
de alarma (dolor torácico, dificultad para respirar, sangrado abundante, pérdida
de conciencia) llama al **112**.
