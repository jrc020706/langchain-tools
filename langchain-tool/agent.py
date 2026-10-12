#!/usr/bin/env python3
"""
Medication guidance agent with LangChain + Gemini.

- If GOOGLE_API_KEY is in the environment: uses real ChatGoogleGenerativeAI
  with create_tool_calling_agent + AgentExecutor (a real agent loop:
  the model decides which tool to use, it runs, and the result goes back
  to the model).
- If there is no key: uses FakeGemini, a simulated LLM that returns real
  tool_calls so the AgentExecutor works the same way in demo mode.

Conversation memory is managed per session with InMemoryChatMessageHistory.
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
except ImportError:  # LangChain >= 1.0: agents live in langchain-classic
    from langchain_classic.agents import AgentExecutor, create_tool_calling_agent

from tools import TOOLS, _norm, SYMPTOMS, MEDICATIONS

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-2.5-flash").strip() or "gemini-2.5-flash"

PLACEHOLDER = "your_google_api_key_here"
USE_REAL_LLM = bool(GOOGLE_API_KEY and GOOGLE_API_KEY != PLACEHOLDER)

# ---------------------------------------------------------------------------
# System prompt (bilingual EN/ES: reply in the user's language)
# Single source: domain/prompts.py (inline fallback if the import fails)
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
   Two tools use public internet APIs (no credentials): `query_pharmacovigilance`
   (openFDA/FAERS adverse-event reports - use for reported side effects) and
   `find_real_pharmacy` (OpenStreetMap real pharmacies - use for actual pharmacies,
   fall back to the local `find_pharmacy` if the API is down).
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
# Simulated LLM (demo mode without API key): returns real tool_calls
# ---------------------------------------------------------------------------
_MED_NAMES = sorted(
    {_norm(m["active_ingredient"]) for m in MEDICATIONS} |
    {_norm(n) for m in MEDICATIONS for n in m.get("brand_names", [])},
    key=len, reverse=True,
)

def _detect_lang_local(text: str) -> str:
    """Local bilingual detector (mirrors domain.i18n, no hard dependency)."""
    low0 = (text or "").lower()
    if "reply in english" in low0:
        return "en"
    if "responde en espa" in low0:
        return "es"
    try:
        from domain.i18n import detect_language as _det
        return _det(text)
    except Exception:
        low = (text or "").lower()
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
    """Expands the normalized query with ES equivalents for matching."""
    extra = [es for en, es in _EN_TO_ES_FAKE.items() if en in q_norm]
    return q_norm + (" " + " ".join(extra) if extra else "")


_PATTERNS = [
    ("assess_urgency", ["112", "urgencia", "urgency", "emergency", "emergencia",
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
    ("check_interaction", ["interaccion", "interacción", "interaction", "combinar", "combine", "juntos",
                           "together", "puedo tomar", "can i take", "mezclar", "mix", "compatible con",
                           "compatible with"]),
    ("calculate_dose", ["dosis", "dose", "dosage", "cuanto le doy", "cuánto le doy", "how much", "mg por kg",
                        "mg per kg", "pesa", "weighs", "weight", "peso", "jarabe", "syrup", "jeringa", "syringe"]),
    ("check_contraindication", ["embarazo", "pregnancy", "pregnant", "embarazada", "lactancia", "breastfeeding",
                                "hipertension", "hypertension", "high blood pressure", "tension alta",
                                "diabetes", "asma", "asthma", "riñon", "kidney", "higado", "liver",
                                "ulcera", "ulcer", "gastritis", "niño", "child", "bebe", "baby",
                                "anciano", "elderly", "abuelo", "anticoagulante", "anticoagulant", "sintrom",
                                "warfarin", "warfarina", "contraindication"]),
    ("find_real_pharmacy", ["farmacia real", "farmacias reales", "real pharmacy",
                            "real pharmacies", "nearest pharmacy", "closest pharmacy",
                            "pharmacy near", "farmacia cerca", "farmacias cerca",
                            "openstreetmap", "nominatim", "en el mapa", "on the map"]),
    ("query_pharmacovigilance", ["farmacovigilancia", "pharmacovigilance", "openfda",
                                 "faers", "efectos adversos", "reacciones adversas",
                                 "adverse events", "adverse reactions", "side effects",
                                 "notificaciones de reacciones", "reaction reports"]),
    ("find_pharmacy", ["farmacia", "pharmacy", "guardia", "on duty", "on-duty", "donde comprar",
                       "dónde comprar", "where to buy", "24 hours", "24 horas"]),
    ("calculate", []),  # detected by math regex
]


class _FakeToolBinding(Runnable):
    """Runnable that mimics an LLM output with function calling."""

    def __init__(self, tools):
        self._tools = {t.name: t for t in tools}
        self._call_count = 0

    def invoke(self, input, config=None):
        messages = input.to_messages() if hasattr(input, "to_messages") else input

        # If there are already tool results in the scratchpad -> final answer
        for msg in reversed(messages):
            if isinstance(msg, ToolMessage):
                self._call_count = 0
                return AIMessage(content=str(msg.content))

        # Last user message
        question = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                question = msg.content or ""
                break
        q = _norm(question)
        qm = _q_matchable(q)
        self._call_count += 1

        # 1) Pure math expression -> calculate
        if re.fullmatch(r"[\d\s+\-*/().%×÷,]+", question.strip()) and re.search(r"\d", q):
            return self._tool_call("calculate", {"expression": question.strip()})

        # 2) Keyword patterns (ES/EN, with expanded query)
        for tool_name, keys in _PATTERNS:
            if any(c in qm for c in keys):
                args = self._args_for(tool_name, question, qm)
                if args is not None:
                    return self._tool_call(tool_name, args)

        # 3) Mentions a known medicine? -> card (with normalized EN aliases)
        for med_name in _MED_NAMES:
            if len(med_name) >= 4 and med_name in qm:
                return self._tool_call("search_medication", {"name": med_name})

        # 4) Describes a known symptom? -> analyze_symptoms (ES/EN)
        for s in SYMPTOMS:
            if any(kw in qm for kw in s["keywords"]):
                return self._tool_call("analyze_symptoms", {"description": question})

        # 5) Generic final answer (bilingual, per detected language)
        self._call_count = 0
        lang = _detect_lang_local(question)
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

    def _tool_call(self, name, args):
        self._call_count = 0
        return AIMessage(content="", tool_calls=[{
            "name": name, "args": args, "id": f"fake-{name}", "type": "tool_call",
        }])

    def _args_for(self, tool_name, question, q):
        # q here is already the EXPANDED query (qm). Keep original norm for EN check.
        lang_q = _detect_lang_local(question)
        _es_to_en = {"ibuprofeno": "ibuprofen", "warfarina": "warfarin",
                     "acido acetilsalicilico": "aspirin"}
        def _to_lang(med_es: str) -> str:
            if lang_q == "en":
                return _es_to_en.get(med_es, med_es)
            return med_es
        if tool_name == "calculate":
            return {"expression": question.strip(), "language": lang_q}
        if tool_name == "analyze_symptoms":
            return {"description": question, "language": lang_q}
        if tool_name == "assess_urgency":
            return {"description": question, "language": lang_q}
        if tool_name == "find_real_pharmacy":
            return {"location": question, "language": lang_q}
        if tool_name == "query_pharmacovigilance":
            med = next((m for m in _MED_NAMES if len(m) >= 4 and m in q), None)
            if med:
                return {"name": _to_lang(med), "language": lang_q}
            return None
        if tool_name == "find_pharmacy":
            return {"location": question, "language": lang_q}
        if tool_name == "search_medication":
            for med_name in _MED_NAMES:
                if len(med_name) >= 4 and med_name in q:
                    return {"name": _to_lang(med_name), "language": lang_q}
            return None
        if tool_name == "calculate_dose":
            med = next((m for m in _MED_NAMES if len(m) >= 4 and m in q), None)
            # ES: "22 kg" / EN: "22 kg", "22kg", "48 lb" not supported -> kg only
            weight = re.search(r"(\d+(?:[.,]\d+)?)\s*kg", q)
            if med and weight:
                return {"medication": _to_lang(med),
                        "weight_kg": float(weight.group(1).replace(",", ".")),
                        "language": lang_q}
            # EN fallback: "dose ... for 22 kg" already covered; "weight 22" without kg?
            return None
        if tool_name == "check_interaction":
            found_meds = [m for m in _MED_NAMES if len(m) >= 4 and m in q]
            extras = []
            if "alcohol" in q:
                extras.append("alcohol")
            if "pomelo" in q or "grapefruit" in q:
                extras.append("grapefruit" if lang_q == "en" else "zumo de pomelo")
            drugs = [_to_lang(m) for m in found_meds] + extras
            if len(drugs) >= 2:
                return {"medication_1": drugs[0], "medication_2": drugs[1], "language": lang_q}
            return None
        if tool_name == "check_contraindication":
            med = next((m for m in _MED_NAMES if len(m) >= 4 and m in q), None)
            if med:
                return {"medication": _to_lang(med), "condition": question, "language": lang_q}
            return None
        return None


class FakeGemini:
    """Mimics ChatGoogleGenerativeAI just enough for create_tool_calling_agent."""

    def __init__(self, model_name="gemini-2.5-flash", temperature=0.3):
        self.model_name = model_name
        self.temperature = temperature

    def bind_tools(self, tools):
        return _FakeToolBinding(tools)


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------
if USE_REAL_LLM:
    from langchain_google_genai import ChatGoogleGenerativeAI
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME, google_api_key=GOOGLE_API_KEY, temperature=0.3,
    )
    print(f"✅ Using real Gemini: {MODEL_NAME}")
else:
    llm = FakeGemini(model_name=MODEL_NAME)
    print("🛠️  Simulated mode (no GOOGLE_API_KEY). Get a free one at https://aistudio.google.com")

agent = create_tool_calling_agent(llm, TOOLS, prompt)
executor = AgentExecutor(
    agent=agent, tools=TOOLS, verbose=False,
    max_iterations=5, handle_parsing_errors=True,
)

# ---------------------------------------------------------------------------
# Per-session memory
# ---------------------------------------------------------------------------
_session_history: dict[str, SessionHistory] = {}


def get_session_history(session_id: str) -> SessionHistory:
    if session_id not in _session_history:
        _session_history[session_id] = SessionHistory()
    return _session_history[session_id]


def run_agent(user_input: str, session_id: str = "default_session", language: str | None = None) -> str:
    """Runs the agent with session memory and returns the final answer.

    Bilingual EN/ES: if `language` is None it is auto-detected from
    `user_input` ('en' or 'es'); the answer always ends with the disclaimer
    in that language.
    """
    try:
        from domain.i18n import detect_language as _det, ensure_disclaimer as _ensure
        lang = language if language in ("es", "en") else _det(user_input)
    except Exception:
        lang = language if language in ("es", "en") else "es"
    history = get_session_history(session_id)
    # If a language different from the detected one is forced, add an explicit
    # hint so that both the real LLM and the demo fake answer in that language.
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
    answer = result.get("output", "")
    try:
        from domain.i18n import ensure_disclaimer as _ensure2
        answer = _ensure2(answer, lang)
    except Exception:
        pass
    history.add_user_message(user_input)
    history.add_ai_message(answer)
    return answer
