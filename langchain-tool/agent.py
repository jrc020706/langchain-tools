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
from domain.session_history import SessionHistory
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
# Prompt del sistema (bilingüe EN/ES: responde en el idioma del usuario)
# Fuente única: domain/prompts.py (fallback inline si el import falla)
# ---------------------------------------------------------------------------
try:
    from domain.prompts import BILINGUAL_SYSTEM_PROMPT as SYSTEM_PROMPT
except Exception:
    SYSTEM_PROMPT = """You are a medication guidance assistant (orientador de medicamentos). You are fully bilingual: English and Spanish.
RULES:
1. LANGUAGE (strict): ALWAYS reply in the same language the user writes in.
   - If the user writes in English, reply 100% in English.
   - If the user writes in Spanish, reply 100% in Spanish.
   - Default to Spanish only when the language is unclear.
   - Never mix languages in the same answer.
2. You have tools for: symptom analysis, drug info sheets, pediatric dose calculation,
   drug interaction checks, contraindications, urgency triage, pharmacy search and math.
   Use them whenever the user asks about symptoms, medicines, doses, interactions,
   contraindications, urgency or pharmacies. Base your answer on the tool results.
   Tool outputs may contain Spanish data (drug database is in Spanish): when the user
   asked in English, briefly explain/translate the key points into English.
3. SAFETY (strict):
   - This is general guidance, NOT a diagnosis and NOT a prescription.
   - Never prescribe antibiotics or prescription-only medicines.
   - If red flags appear (chest pain / dolor en el pecho, breathing difficulty / dificultad
     para respirar, heavy bleeding / sangrado abundante, loss of consciousness /
     pérdida de conciencia, facial/tongue swelling, suicidal intent), tell the user
     to call 112 / go to emergency immediately (llama al 112 / acude a urgencias).
   - In pregnancy, breastfeeding, babies < 2 years or chronic disease, be conservative
     and recommend pharmacist/doctor confirmation.
4. Be concise and clear. Use short lists. End every answer with exactly one line:
   - In Spanish: "⚠️ Orientación general, no sustituye al médico o farmacéutico."
   - In English: "⚠️ General guidance, does not replace your doctor or pharmacist."
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

def _detect_lang_local(texto: str) -> str:
    """Local bilingual detector (mirrors domain.i18n, no hard dependency)."""
    low0 = (texto or "").lower()
    if "reply in english" in low0:
        return "en"
    if "responde en espa" in low0:
        return "es"
    try:
        from domain.i18n import detect_language as _det
        return _det(texto)
    except Exception:
        low = (texto or "").lower()
        if any(c in low for c in ("¿", "¡", "ñ", "á", "é", "í", "ó", "ú")):
            return "es"
        en_words = {"the", "and", "with", "what", "how", "can", "dose",
                    "pregnant", "child", "weight", "pain", "fever", "cough",
                    "pharmacy", "interaction", "chest", "breathe", "hello"}
        import re as _re
        words = set(_re.findall(r"[a-z]+", low))
        return "en" if (words & en_words) else "es"


_EN_TO_ES_FAKE = {
    "ibuprofen": "ibuprofeno", "acetaminophen": "paracetamol",
    "warfarin": "warfarina", "grapefruit": "pomelo",
    "fever": "fiebre", "sore throat": "garganta", "throat": "garganta",
    "headache": "dolor de cabeza", "cough": "tos", "phlegm": "flema",
    "cold": "resfriado", "allergy": "alergia", "diarrhea": "diarrea",
    "heartburn": "acidez", "dizziness": "mareo", "dizzy": "mareo",
    "pregnancy": "embarazo", "pregnant": "embarazada",
    "breastfeeding": "lactancia", "hypertension": "hipertension",
    "high blood pressure": "tension alta", "kidney": "rinon",
    "chest pain": "dolor en el pecho", "difficulty breathing": "dificultad para respirar",
}


def _q_matchable(q_norm: str) -> str:
    """Expande la query normalizada con equivalentes ES para el matching."""
    extra = [es for en, es in _EN_TO_ES_FAKE.items() if en in q_norm]
    return q_norm + (" " + " ".join(extra) if extra else "")


_PATRONES = [
    ("evaluar_urgencia", ["112", "urgencia", "urgency", "emergency", "emergencia",
                          "ahogo", "me ahogo", "asfixia", "choking",
                          "no puedo respirar", "cuesta respirar", "dificultad para respirar",
                          "falta el aire", "falta de aire",
                          "i can't breathe", "i cant breathe", "can't breathe", "cannot breathe",
                          "difficulty breathing", "shortness of breath",
                          "dolor en el pecho", "dolor de pecho", "duele el pecho", "dolor toracico",
                          "opresion en el pecho", "presion en el pecho", "dolor de corazon",
                          "chest pain", "chest hurts", "my chest hurts", "pressure in chest",
                          "desmayo", "perdida de conciencia", "convulsion", "convulsiones",
                          "faint", "fainted", "loss of consciousness", "seizure", "seizures",
                          "sangrado abundante", "no para de sangrar", "hemorragia",
                          "heavy bleeding", "bleeding a lot", "hemorrhage",
                          "ictus", "cara torcida", "no puedo hablar", "debilidad en un lado",
                          "stroke", "face drooping", "cant speak", "cannot speak", "weakness on one side",
                          "alergia grave", "anafilaxia", "hinchazon de lengua", "hinchazon de labios",
                          "severe allergy", "anaphylaxis", "swollen tongue", "swollen lips",
                          "quemadura extensa", "extensive burn",
                          "intento de suicidio", "quiero morir", "sobredosis",
                          "suicide attempt", "want to die", "overdose",
                          "grave", "severe"]),
    ("verificar_interaccion", ["interaccion", "interacción", "interaction", "combinar", "combine", "juntos",
                               "together", "puedo tomar", "can i take", "mezclar", "mix", "compatible con",
                               "compatible with"]),
    ("calcular_dosis", ["dosis", "dose", "dosage", "cuanto le doy", "cuánto le doy", "how much", "mg por kg",
                        "mg per kg", "pesa", "weighs", "weight", "peso", "jarabe", "syrup", "jeringa", "syringe"]),
    ("consultar_contraindicacion", ["embarazo", "pregnancy", "pregnant", "embarazada", "lactancia", "breastfeeding",
                                    "hipertension", "hypertension", "high blood pressure", "tension alta",
                                    "diabetes", "asma", "asthma", "riñon", "kidney", "higado", "liver",
                                    "ulcera", "ulcer", "gastritis", "niño", "child", "bebe", "baby",
                                    "anciano", "elderly", "abuelo", "anticoagulante", "anticoagulant", "sintrom",
                                    "warfarin", "warfarina", "contraindication"]),
    ("buscar_farmacia", ["farmacia", "pharmacy", "guardia", "on duty", "on-duty", "donde comprar",
                         "dónde comprar", "where to buy", "24 hours", "24 horas"]),
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
        qm = _q_matchable(q)
        self._llamada_n += 1

        # 1) Expresión matemática pura -> calcular
        if re.fullmatch(r"[\d\s+\-*/().%×÷,]+", pregunta.strip()) and re.search(r"\d", q):
            return self._tool_call("calcular", {"expresion": pregunta.strip()})

        # 2) Patrones por palabras clave (ES/EN, con query expandida)
        for nombre_tool, claves in _PATRONES:
            if any(c in qm for c in claves):
                args = self._args_para(nombre_tool, pregunta, qm)
                if args is not None:
                    return self._tool_call(nombre_tool, args)

        # 3) ¿Menciona un medicamento conocido? -> ficha (con alias EN normalizados)
        for nombre_med in _MED_NOMBRES:
            if len(nombre_med) >= 4 and nombre_med in qm:
                return self._tool_call("buscar_medicamento", {"nombre": nombre_med})

        # 4) ¿Describe algún síntoma conocido? -> analizar_sintomas (ES/EN)
        for s in SINTOMAS:
            if any(kw in qm for kw in s["palabras_clave"]):
                return self._tool_call("analizar_sintomas", {"descripcion": pregunta})

        # 5) Respuesta genérica final (bilingüe según idioma detectado)
        self._llamada_n = 0
        lang = _detect_lang_local(pregunta)
        if lang == "en":
            return AIMessage(content=(
                "I'm a medication guidance assistant (demo mode, no API key). "
                "I can: analyze symptoms, give medicine cards, calculate weight-based doses, "
                "check interactions and contraindications, assess urgency and find pharmacies. "
                "Try for example: 'I have fever and sore throat', "
                "'what is ibuprofen', 'paracetamol dose for 22 kg' or "
                "'can I take ibuprofen with warfarin'.\n"
                "⚠️ General guidance, does not replace your doctor or pharmacist."
            ))
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
        # q here is already the EXPANDED query (qm). Keep original norm for EN check.
        lang_q = _detect_lang_local(pregunta)
        _es_to_en = {"ibuprofeno": "ibuprofen", "warfarina": "warfarin",
                     "acido acetilsalicilico": "aspirin"}
        def _to_lang(med_es: str) -> str:
            if lang_q == "en":
                return _es_to_en.get(med_es, med_es)
            return med_es
        if nombre_tool == "calcular":
            return {"expresion": pregunta.strip(), "language": lang_q}
        if nombre_tool == "analizar_sintomas":
            return {"descripcion": pregunta, "language": lang_q}
        if nombre_tool == "evaluar_urgencia":
            return {"descripcion": pregunta, "language": lang_q}
        if nombre_tool == "buscar_farmacia":
            return {"ubicacion": pregunta, "language": lang_q}
        if nombre_tool == "buscar_medicamento":
            for nombre_med in _MED_NOMBRES:
                if len(nombre_med) >= 4 and nombre_med in q:
                    return {"nombre": _to_lang(nombre_med), "language": lang_q}
            return None
        if nombre_tool == "calcular_dosis":
            med = next((m for m in _MED_NOMBRES if len(m) >= 4 and m in q), None)
            # ES: "22 kg" / EN: "22 kg", "22kg", "48 lb" not supported -> kg only
            peso = re.search(r"(\d+(?:[.,]\d+)?)\s*kg", q)
            if med and peso:
                return {"medicamento": _to_lang(med), "peso_kg": float(peso.group(1).replace(",", ".")), "language": lang_q}
            # EN fallback: "dose ... for 22 kg" already covered; "weight 22" without kg?
            return None
        if nombre_tool == "verificar_interaccion":
            encontrados = [m for m in _MED_NOMBRES if len(m) >= 4 and m in q]
            extras = []
            if "alcohol" in q:
                extras.append("alcohol")
            if "pomelo" in q or "grapefruit" in q:
                extras.append("grapefruit" if lang_q == "en" else "zumo de pomelo")
            todos = [_to_lang(m) for m in encontrados] + extras
            if len(todos) >= 2:
                return {"medicamento_1": todos[0], "medicamento_2": todos[1], "language": lang_q}
            return None
        if nombre_tool == "consultar_contraindicacion":
            med = next((m for m in _MED_NOMBRES if len(m) >= 4 and m in q), None)
            if med:
                return {"medicamento": _to_lang(med), "condicion": pregunta, "language": lang_q}
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
_session_history: dict[str, SessionHistory] = {}


def get_session_history(session_id: str) -> SessionHistory:
    if session_id not in _session_history:
        _session_history[session_id] = SessionHistory()
    return _session_history[session_id]


def run_agent(user_input: str, session_id: str = "default_session", language: str | None = None) -> str:
    """Ejecuta el agente con memoria de sesión y devuelve la respuesta final.

    Bilingüe EN/ES: si `language` es None se autodetecta desde `user_input`
    ('en' o 'es'); la respuesta siempre termina con el disclaimer en ese idioma.
    """
    try:
        from domain.i18n import detect_language as _det, ensure_disclaimer as _ensure
        lang = language if language in ("es", "en") else _det(user_input)
    except Exception:
        lang = language if language in ("es", "en") else "es"
    history = get_session_history(session_id)
    # Si se fuerza un idioma distinto al detectado, añadir pista explícita
    # para que tanto el LLM real como el fake de demo respondan en ese idioma.
    try:
        from domain.i18n import detect_language as _det2
        _detected = _det2(user_input)
    except Exception:
        _detected = lang
    effective_input = user_input
    if language in ("es", "en") and language != _detected:
        hint = "Reply in English" if lang == "en" else "Responde en español"
        effective_input = f"[{hint}] {user_input}"
    result = executor.invoke({
        "input": effective_input,
        "chat_history": history.messages,
    })
    respuesta = result.get("output", "")
    try:
        from domain.i18n import ensure_disclaimer as _ensure2
        respuesta = _ensure2(respuesta, lang)
    except Exception:
        pass
    history.add_user_message(user_input)
    history.add_ai_message(respuesta)
    return respuesta
