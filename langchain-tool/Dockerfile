# Image for the medication advisor (HTTP API + MCP server).
# Build and run from the repo root:
#   docker build -t medication-advisor ./langchain-tool
#   docker run -p 8000:8000 -e HOST=0.0.0.0 medication-advisor                 # MCP server
#   docker run -p 7860:7860 -e HOST=0.0.0.0 medication-advisor python app.py    # Gradio UI
# It needs no API key nor credential: it starts in demo mode if GOOGLE_API_KEY is absent.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "mcp_server.py"]
