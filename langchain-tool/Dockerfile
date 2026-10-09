# Imagen del orientador de medicamentos (API HTTP + servidor MCP).
# Construcción y arranque desde la raíz del repo:
#   docker build -t orientador ./langchain-tool
#   docker run -p 8000:8000 -e HOST=0.0.0.0 orientador                 # servidor MCP
#   docker run -p 7860:7860 -e HOST=0.0.0.0 orientador python app.py    # interfaz Gradio
# No necesita ninguna API key ni credencial: arranca en modo demo si no hay GOOGLE_API_KEY.
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
