#!/usr/bin/env python3
"""
Agente de orientación de medicamentos con LangChain + Gemini.

- Si hay GOOGLE_API_KEY en el entorno: usa ChatGoogleGenerativeAI real
  con create_tool_calling_agent + AgentExecutor (loop real de agente:
  el modelo decide qué tool usar, se ejecuta, y el resultado vuelve al modelo).
- Si no hay key: usa FakeGemini, un LLM simulado que devuelve tool_calls
  reales para que el AgentExecutor funcione igual en modo demo.

La memoria de conversación se gestiona por sesión con InMemoryChatMessageHistory.
"""

import os
import re
from dotenv import load_dotenv

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.base import Runnable
from langchain_core.chat_history import InMemoryChatMessageHistory
try:
    from langchain.agents import AgentExecutor, create_tool_calling_agent
except ImportError:  # LangChain >= 1.0: agentes en langchain-classic
    from langchain_classic.agents import AgentExecutor, create_tool_calling_agent

from tools import TOOLS, _norm, _buscar_principio_activo, SINTOMAS, MEDICAMENTOS

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-2.5-flash").strip() or "gemini-2.5-flash"

PLACEHOLDER = "tu_api_key_de_google_aqui"
USE_REAL_LLM = bool(GOOGLE_API_KEY and GOOGLE_API_KEY != PLACEHOLDER)

# ---------------------------------------------------------------------------
# Prompt del sistema (bilingüe: responde en el idioma del usuario)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a medication guidance assistant (orientador de medicamentos).
RULES:
1. ALWAYS reply in the same language the user writes in (Spanish by default).
2. You have tools for: symptom analysis, drug info sheets, pediatric dose calculation,
   drug interaction checks, contraindications, urgency triage, pharmacy search and math.
   Use them whenever the user asks about symptoms, medicines, doses, interactions,
   contraindications, urgency or pharmacies. Base your answer on the tool results.
3. SAFETY (strict):
   - This is general guidance, NOT a diagnosis and NOT a prescription.
   - Never prescribe antibiotics or prescription-only medicines.
   - If red flags appear (chest pain, breathing difficulty, heavy bleeding,
     loss of consciousness, facial/tongue swelling, suicidal intent), tell the user
     to call 112 / go to emergency immediately.
   - In pregnancy, breastfeeding, babies < 2 years or chronic disease, be conservative
     and recommend pharmacist/doctor confirmation.
4. Be concise and clear. Use short lists. End every answer with one line:
   "⚠️ Orientación general, no sustituye al médico o farmacéutico."
"""

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="chat_history"),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

# ---------------------------------------------------------------------------
# LLM simulado (modo demo sin API key): devuelve tool_calls reales
# ---------------------------------------------------------------------------
_MED_NOMBRES = sorted(
    {_norm(m["principio_activo"]) for m in MEDICAMENTOS} |
    {_norm(n) for m in MEDICAMENTOS for n in m.get("nombre_comercial", [])},
    key=len, reverse=True,
)

_PATRONES = [
    ("evaluar_urgencia", ["112", "urgencia", "emergencia", "ahogo", "no puedo respirar",
                          "dolor en el pecho", "dolor toracico", "desmayo", "sangrado",
                          "convulsion", "anafilaxia", "grave"]),
    ("verificar_interaccion", ["interaccion", "interacción", "combinar", "juntos",
                               "puedo tomar", "mezclar", "compatible con"]),
    ("calcular_dosis", ["dosis", "cuanto le doy", "cuánto le doy", "mg por kg",
                        "pesa", "peso", "jarabe", "jeringa"]),
    ("consultar_contraindicacion", ["embarazo", "embarazada", "lactancia", "dando el pecho",
                                    "hipertension", "tension alta", "diabetes", "asma",
                                    "riñon", "higado", "ulcera", "gastritis", "niño",
                                    "bebe", "anciano", "abuelo", "anticoagulante", "sintrom"]),
    ("buscar_farmacia", ["farmacia", "guardia", "donde comprar", "dónde comprar"]),
    ("calcular", []),  # se detecta por regex matemática
]


class _FakeToolBinding(Runnable):
    """Runnable que imita la salida de un LLM con function calling."""

    def __init__(self, tools):
        self._tools = {t.name: t for t in tools}
        self._llamada_n = 0

    def invoke(self, input, config=None):
        mensajes = input.to_messages() if hasattr(input, "to_messages") else input

        # Si ya hay resultados de tools en el scratchpad -> respuesta final
        for msg in reversed(mensajes):
            if isinstance(msg, ToolMessage):
                self._llamada_n = 0
                return AIMessage(content=str(msg.content))

        # Último mensaje del usuario
        pregunta = ""
        for msg in reversed(mensajes):
            if isinstance(msg, HumanMessage):
                pregunta = msg.content or ""
                break
        q = _norm(pregunta)
        self._llamada_n += 1

        # 1) Expresión matemática pura -> calcular
        if re.fullmatch(r"[\d\s+\-*/().%×÷,]+", pregunta.strip()) and re.search(r"\d", q):
            return self._tool_call("calcular", {"expresion": pregunta.strip()})

        # 2) Patrones por palabras clave
        for nombre_tool, claves in _PATRONES:
            if any(c in q for c in claves):
                args = self._args_para(nombre_tool, pregunta, q)
                if args is not None:
                    return self._tool_call(nombre_tool, args)

        # 3) ¿Menciona un medicamento conocido? -> ficha
        for nombre_med in _MED_NOMBRES:
            if len(nombre_med) >= 4 and nombre_med in q:
                return self._tool_call("buscar_medicamento", {"nombre": nombre_med})

        # 4) ¿Describe algún síntoma conocido? -> analizar_sintomas
        for s in SINTOMAS:
            if any(kw in q for kw in s["palabras_clave"]):
                return self._tool_call("analizar_sintomas", {"descripcion": pregunta})

        # 5) Respuesta genérica final
        self._llamada_n = 0
        return AIMessage(content=(
            "Soy un orientador de medicamentos (modo demo sin API key). "
            "Puedo: analizar síntomas, dar fichas de medicamentos, calcular dosis por peso, "
            "revisar interacciones y contraindicaciones, evaluar urgencia y buscar farmacias. "
            "Prueba por ejemplo: 'tengo fiebre y dolor de garganta', "
            "'qué es el ibuprofeno', 'dosis de paracetamol para 22 kg' o "
            "'puedo tomar ibuprofeno con warfarina'.\n"
            "⚠️ Orientación general, no sustituye al médico o farmacéutico."
        ))

    def _tool_call(self, nombre, args):
        self._llamada_n = 0
        return AIMessage(content="", tool_calls=[{
            "name": nombre, "args": args, "id": f"fake-{nombre}", "type": "tool_call",
        }])

    def _args_para(self, nombre_tool, pregunta, q):
        if nombre_tool == "calcular":
            return {"expresion": pregunta.strip()}
        if nombre_tool == "analizar_sintomas":
            return {"descripcion": pregunta}
        if nombre_tool == "evaluar_urgencia":
            return {"descripcion": pregunta}
        if nombre_tool == "buscar_farmacia":
            return {"ubicacion": pregunta}
        if nombre_tool == "buscar_medicamento":
            for nombre_med in _MED_NOMBRES:
                if len(nombre_med) >= 4 and nombre_med in q:
                    return {"nombre": nombre_med}
            return None
        if nombre_tool == "calcular_dosis":
            med = next((m for m in _MED_NOMBRES if len(m) >= 4 and m in q), None)
            peso = re.search(r"(\d+(?:[.,]\d+)?)\s*kg", q)
            if med and peso:
                return {"medicamento": med, "peso_kg": float(peso.group(1).replace(",", "."))}
            return None
        if nombre_tool == "verificar_interaccion":
            encontrados = [m for m in _MED_NOMBRES if len(m) >= 4 and m in q]
            extras = []
            if "alcohol" in q:
                extras.append("alcohol")
            if "pomelo" in q:
                extras.append("zumo de pomelo")
            todos = encontrados + extras
            if len(todos) >= 2:
                return {"medicamento_1": todos[0], "medicamento_2": todos[1]}
            return None
        if nombre_tool == "consultar_contraindicacion":
            med = next((m for m in _MED_NOMBRES if len(m) >= 4 and m in q), None)
            if med:
                return {"medicamento": med, "condicion": pregunta}
            return None
        return None


class FakeGemini:
    """Imita ChatGoogleGenerativeAI lo justo para create_tool_calling_agent."""

    def __init__(self, model_name="gemini-2.5-flash", temperature=0.3):
        self.model_name = model_name
        self.temperature = temperature

    def bind_tools(self, tools):
        return _FakeToolBinding(tools)


# ---------------------------------------------------------------------------
# Construcción del agente
# ---------------------------------------------------------------------------
if USE_REAL_LLM:
    from langchain_google_genai import ChatGoogleGenerativeAI
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME, google_api_key=GOOGLE_API_KEY, temperature=0.3,
    )
    print(f"✅ Usando Gemini real: {MODEL_NAME}")
else:
    llm = FakeGemini(model_name=MODEL_NAME)
    print("🛠️  Modo simulado (sin GOOGLE_API_KEY). Consigue una gratis en https://aistudio.google.com")

agent = create_tool_calling_agent(llm, TOOLS, prompt)
executor = AgentExecutor(
    agent=agent, tools=TOOLS, verbose=False,
    max_iterations=5, handle_parsing_errors=True,
)

# ---------------------------------------------------------------------------
# Memoria por sesión
# ---------------------------------------------------------------------------
_session_history: dict[str, InMemoryChatMessageHistory] = {}


def get_session_history(session_id: str) -> InMemoryChatMessageHistory:
    if session_id not in _session_history:
        _session_history[session_id] = InMemoryChatMessageHistory()
    return _session_history[session_id]


def run_agent(user_input: str, session_id: str = "default_session") -> str:
    """Ejecuta el agente con memoria de sesión y devuelve la respuesta final."""
    history = get_session_history(session_id)
    result = executor.invoke({
        "input": user_input,
        "chat_history": history.messages,
    })
    respuesta = result.get("output", "")
    history.add_user_message(user_input)
    history.add_ai_message(respuesta)
    return respuesta
