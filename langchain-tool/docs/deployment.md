# 🚀 Deployment

The goal is for the project to be **published and consumable from any client,
without asking for authentication**. This document collects the options and the
versions it has been tested with.

## Versions (important to avoid incidents)

| Where | Version |
|---|---|
| Python (local and deployment) | **3.14** — pinned in `.python-version` (repo root) |
| Dependencies | **pinned** in `langchain-tool/requirements.txt` (`==`) |
| FastMCP / MCP | `fastmcp==4.1.0`, `mcp==2.3.0` |
| LangChain | `langchain==1.4.4`, `langchain-core==1.6.9`, `langchain-classic==1.0.8` |
| Gradio | `gradio==6.30.0` |

> If you change a version, update `requirements.txt` with `pip freeze | grep <package>`
> and re-test `python app.py` and `python mcp_server.py` before deploying.

---

## Option A — Render (the recommended one)

`render.yaml` is at the **repository root** and uses `rootDir: langchain-tool`,
so Render detects it automatically when creating a Blueprint (no need to
indicate paths).

1. Push the repo to GitHub.
2. On https://dashboard.render.com → **New → Blueprint** → connect the repository.
3. Render creates two services:

   | Service | `startCommand` | Exposes |
   |---|---|---|
   | `orientador-web` | `python app.py` | Gradio interface |
   | `orientador-mcp` | `python mcp_server.py` | HTTP API + MCP server |

4. Both use `HOST=0.0.0.0` (Render injects `PORT`) and the Python version from
   `.python-version`.
5. **Optional:** add the `GOOGLE_API_KEY` secret in *Environment* of each
   service to use real Gemini. Without it, the services still start in
   simulated demo mode → **the deployment requires no credentials**.

Result: two public URLs like `https://orientador-web.onrender.com` and
`https://orientador-mcp.onrender.com`. Quick check:

```bash
curl -s https://orientador-mcp.onrender.com/ | jq '.tools_total, .resources_total, .prompts_total'
# 10 / 6 / 3
```

> Free plan: they go to sleep after ~15 min without traffic; the first request
> takes ~1 min to wake them up.

### Service created by hand (without a Blueprint)

- Build command: `pip install -r requirements.txt`
- Start command: `python app.py` or `python mcp_server.py`
- Root directory: `langchain-tool`
- Env: `HOST=0.0.0.0` (and optionally `GOOGLE_API_KEY`)

---

## Option B — Docker (any other platform)

`langchain-tool/Dockerfile` uses `python:3.14-slim` (same version as `.python-version`).

```bash
# from the repo root
docker build -t medication-advisor ./langchain-tool

docker run -p 8000:8000 -e HOST=0.0.0.0 medication-advisor                 # MCP server
docker run -p 7860:7860 -e HOST=0.0.0.0 medication-advisor python app.py    # Gradio UI
```

It works the same on Railway, Fly.io, AWS App Runner, Cloud Run, etc.: they
only need `HOST=0.0.0.0` and to respect `PORT`.

---

## Option C — Tunnels from your machine (quick demo)

```bash
# NGrok (https://ngrok.com): ngrok config add-authtoken YOUR_TOKEN
python mcp_server.py       # terminal 1
ngrok http 8000            # terminal 2 -> public URL https://xxxx.ngrok.app

# Cloudflare (no sign-up)
cloudflared tunnel --url http://localhost:8000
```

The Gradio interface is the same with port 7860.

---

## Authentication

**There is none, by design (project requirement):**

- The HTTP endpoints (`/`, `/tools`, `/resources`, `/prompts`, `/chat`,
  `/history`, `/mcp`) are public.
- The MCP protocol requires no auth headers nor OAuth.
- CORS allows any origin (`access-control-allow-origin: *`).
- The two external APIs (openFDA and OpenStreetMap) are also public and need
  no API key.
- Only the **service** needs `GOOGLE_API_KEY` to talk to Gemini; the end client
  never uses it.

⚠️ Since the service is open, do not keep secrets in the code and watch usage
in the provider's logs.

---

## Troubleshooting

| Symptom | Likely cause | Solution |
|---|---|---|
| `render.yaml` not detected | The file is in a subfolder | It must be at the root (here it is) with `rootDir` |
| Wheel errors when installing | Different Python version | Check `.python-version` = `3.14` and `PYTHON_VERSION` on Render |
| `Address already in use` | Wrong port | Use the environment `PORT` (Render injects it) |
| Local service not listening externally | `HOST=127.0.0.1` | Export `HOST=0.0.0.0` remotely |
| `find_real_pharmacy` returns a warning | Overpass overloaded or no network | Retry; the tool already *falls back* to Nominatim and to `find_pharmacy` |
| "Made-up" responses | `GOOGLE_API_KEY` missing | Demo mode (same tools, keyword-based routing) |
| 502/504 on Render | The process took too long to start | Check the build logs; `pip install -r requirements.txt` must be the build command |
