# 💊 Agente de orientación de medicamentos (LangChain + Gemini)

Agente conversacional en español que orienta sobre medicamentos según síntomas:
analiza síntomas, da fichas de medicamentos, calcula dosis pediátricas por peso,
revisa interacciones y contraindicaciones, hace triaje de urgencia y busca farmacias.

## Estructura

```
langchain-tool/
├── agent.py        # Agente: Gemini + AgentExecutor + memoria por sesión
├── tools.py        # Las 8 tools (leen de data/*.json)
├── app.py          # Interfaz web con Gradio (http://localhost:7860)
├── main.py         # Demo por terminal
├── data/
│   ├── medicamentos.json       # 18 fármacos comunes en España
│   ├── sintomas.json           # 24 grupos de síntomas
│   ├── interacciones.json      # 26 interacciones frecuentes
│   ├── contraindicaciones.json # 12 condiciones (embarazo, HTA, riñón...)
│   └── farmacias.json          # 10 farmacias de muestra
├── .env.example    # Plantilla de configuración
├── requirements.txt
└── README.md
```

## Instalación

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # y pon tu GOOGLE_API_KEY (gratis en https://aistudio.google.com)
```

Sin API key funciona igual en **modo simulado** (demo).

## Uso

```bash
python main.py   # demo por terminal (3 turnos con memoria)
python app.py    # interfaz web en http://localhost:7860
```

## Las 8 tools y cómo funcionan

| Tool | Entrada → Salida | Mecanismo |
|---|---|---|
| `analizar_sintomas` | Texto libre → causas posibles + OTC + alarmas | Coincidencia de palabras clave en `sintomas.json` (normalizado sin tildes) |
| `buscar_medicamento` | Nombre comercial o activo → ficha completa | Búsqueda por alias + sugerencias difusas (`difflib`) si no existe |
| `calcular_dosis` | Medicamento + peso kg → mg por toma e intervalo | Regla mg/kg en Python (paracetamol 15 mg/kg c/6h, ibuprofeno 10 mg/kg c/8h) |
| `verificar_interaccion` | 2 fármacos → severidad + recomendación | Cruce de parejas (orden indiferente) en `interacciones.json` |
| `consultar_contraindicacion` | Fármaco + condición → 🔴🟡🟢 + alternativas | Cruce contra `contraindicaciones.json` + advertencias de la ficha |
| `evaluar_urgencia` | Síntomas → 🟢 autocuidado / 🟡 médico / 🔴 112 | Reglas de triaje por palabras de alarma |
| `buscar_farmacia` | Ubicación → farmacias (filtro de guardia) | Filtrado en `farmacias.json` (datos simulados) |
| `calcular` | Expresión → resultado | `numexpr` (parser seguro, sin `eval`) |

## Seguridad

- El system prompt obliga a: orientación general (no diagnósticos ni recetas),
  no prescribir antibióticos ni fármacos con receta, derivar al 112 ante alarmas
  y cerrar cada respuesta con el disclaimer.
- Los datasets son de muestra con fines educativos: verifica siempre con el
  prospecto, tu médico o farmacéutico.

## Ampliar

- **Más medicamentos/síntomas**: añade entradas a los JSON (sin tocar código).
- **Datos reales**: la tool `buscar_medicamento` puede extenderse consultando la
  API pública CIMA de la AEMPS (https://cima.aemps.es/cima/rest/medicamentos).
- **Memoria persistente**: sustituye el dict de `agent.py` por Redis/Postgres.
