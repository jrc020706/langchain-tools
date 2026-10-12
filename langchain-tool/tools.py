#!/usr/bin/env python3
"""
Tools for the medication guidance agent.

Each tool is a function decorated with LangChain's @tool:
- Gemini uses the name and docstring to decide when to call it.
- All of them return plain text (str) with the information found.
- Data lives in data/*.json so it can be extended without touching code.

Tools:
1. analyze_symptoms            - free-text symptoms -> possible causes + OTC + red flags
2. search_medication           - brand or active ingredient -> full medicine card
3. calculate_dose              - medicine + weight (kg) -> pediatric dose per intake
4. check_interaction           - 2 drugs -> interaction, severity and recommendation
5. check_contraindication      - drug + condition (pregnancy, hypertension...) -> warnings
6. assess_urgency              - symptom description -> triage (home / doctor / 112)
7. find_pharmacy               - location -> nearby (simulated) pharmacies
8. calculate                   - math expression -> result (safe numexpr parser)
9. query_pharmacovigilance     - drug -> adverse-event reports (openFDA API)   [internet API #1]
10. find_real_pharmacy         - location -> real OpenStreetMap pharmacies
                                  (Nominatim + Overpass)                       [internet API #2]

Tools 9 and 10 are the two that consume internet APIs from two different
cloud services (openFDA / NIH and OpenStreetMap). Both are public and need
no authentication or API key; if the network fails they return a notice,
and 9 and 10 fall back to the local datasets where applicable.

Responses are bilingual (ES/EN): every tool accepts a `language` parameter
("es", "en" or "auto") and keeps the Spanish data content of data/*.json.
"""

import json
import math
import time
import unicodedata
from difflib import get_close_matches
from pathlib import Path

import requests
from langchain_core.tools import tool

DATA_DIR = Path(__file__).parent / "data"

# ---------------------------------------------------------------------------
# Shared configuration for the tools that consume internet APIs
# (different cloud services, public and WITH NO authentication)
# ---------------------------------------------------------------------------
# Internet API #1: openFDA (NIH / U.S. FAERS) - https://open.fda.gov/apis/
OPENFDA_EVENT_URL = "https://api.fda.gov/drug/event.json"
# Internet API #2: OpenStreetMap - Nominatim (geocoding) + Overpass (data)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

# Identifying User-Agent: required by the Nominatim/Overpass usage policy
# (not a secret nor a credential: it only identifies the app).
HTTP_HEADERS = {"User-Agent": "medication-advisor/1.0 (educational tool)"}
HTTP_TIMEOUT = 15  # seconds; if an API does not answer, the tool degrades with a notice

# Total network budget per tool invocation: even if every call fails, the
# tool answers within this time (it never hangs the chat).
API_BUDGET = 22.0  # seconds
GEO_BUDGET = 20.0  # seconds for the OpenStreetMap tool

# Split of the geographic budget: Overpass has the best data (radius + opening
# hours) but is the most prone to saturation, so we cap its attempt to leave
# time for the Nominatim fallback within the same budget.
OVERPASS_MAX = 9.0
NOMINATIM_MAX = 7.0


def _remaining(start: float, limit: float) -> float:
    """Seconds left from the budget (>= 0)."""
    return max(0.0, limit - (time.monotonic() - start))


def _get_json(url: str, *, params: dict | None = None, data: dict | None = None,
              timeout: float | None = None) -> dict | list:
    """GET/POST JSON with timeout. Raises if the API does not answer or fails."""
    t = HTTP_TIMEOUT if timeout is None else max(1.0, timeout)
    if data is not None:
        resp = requests.post(url, data=data, headers=HTTP_HEADERS, timeout=t)
    else:
        resp = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=t)
    resp.raise_for_status()
    return resp.json()


def _load(filename: str):
    """Loads a JSON from data/ and returns it as a list."""
    with open(DATA_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def _norm(text: str) -> str:
    """Normalizes text: lowercase + no accents, to compare without failures."""
    text = text.lower().strip()
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def _detect_lang(*texts: str) -> str:
    """Detects 'en' or 'es' from the input texts.

    Uses domain.i18n as the single source, with a local fallback if the import
    fails (e.g. when importing tools.py standalone).
    """
    joined = " ".join(t for t in texts if t)
    try:
        from domain.i18n import detect_language as _det
        return _det(joined)
    except Exception:
        import re as _re
        low = joined.lower()
        if any(c in low for c in ("¿", "¡", "ñ", "á", "é", "í", "ó", "ú")):
            return "es"
        en_words = {"the", "and", "with", "what", "how", "can", "dose",
                    "pregnant", "child", "weight", "pain", "fever", "cough",
                    "pharmacy", "interaction", "chest", "breathe", "hello"}
        words = set(_re.findall(r"[a-z]+", low))
        return "en" if (words & en_words) else "es"


DISCLAIMER_ES = "⚠️ Orientación general, no sustituye al médico o farmacéutico."
DISCLAIMER_EN = "⚠️ General guidance, does not replace your doctor or pharmacist."


def _disclaimer(lang: str) -> str:
    return DISCLAIMER_EN if lang == "en" else DISCLAIMER_ES


# EN -> ES map so symptom/condition matching also works in English
# without duplicating the JSON files (which remain in Spanish).
_EN_TO_ES = {
    "fever": "fiebre", "sore throat": "garganta", "throat": "garganta",
    "headache": "dolor de cabeza", "head hurts": "dolor de cabeza",
    "dry cough": "tos seca", "cough": "tos", "phlegm": "flema",
    "runny nose": "mocos", "stuffy nose": "congestion", "congestion": "congestion",
    "sneezing": "estornudos", "cold": "resfriado", "allergy": "alergia",
    "itch": "picor", "itching": "picor", "rash": "ronchas",
    "diarrhea": "diarrea", "heartburn": "acidez", "stomach": "estomago",
    "nausea": "nausea", "vomit": "vomito", "vomiting": "vomitos",
    "dizziness": "mareo", "dizzy": "mareo", "insomnia": "insomnio",
    "sleepless": "insomnio", "pain": "dolor", "ache": "dolor",
    # conditions
    "pregnancy": "embarazo", "pregnant": "embarazada",
    "breastfeeding": "lactancia", "hypertension": "hipertension",
    "high blood pressure": "tension alta", "kidney": "rinon",
    "liver": "higado", "ulcer": "ulcera", "asthma": "asma",
    "diabetes": "diabetes", "child": "nino", "baby": "bebe",
    "elderly": "anciano", "anticoagulant": "anticoagulante",
    "grapefruit": "pomelo", "ibuprofen": "ibuprofeno",
    "paracetamol": "paracetamol", "acetaminophen": "paracetamol",
}


def _expand_en_to_es(desc_norm: str) -> str:
    """Adds Spanish equivalents to the normalized text for matching."""
    extra = [es for en, es in _EN_TO_ES.items() if en in desc_norm]
    if extra:
        return desc_norm + " " + " ".join(extra)
    return desc_norm


# Load datasets into memory (once, at module import)
MEDICATIONS = _load("medications.json")
SYMPTOMS = _load("symptoms.json")
INTERACTIONS = _load("interactions.json")
CONTRAINDICATIONS = _load("contraindications.json")
PHARMACIES = _load("pharmacies.json")

# Pediatric dose rules per active ingredient (mg per kg per intake)
PEDIATRIC_DOSAGE = {
    "paracetamol": {"mg_kg": 15, "interval_h": 6, "max_mg_per_kg_day": 60,
                    "note": "Jarabe habitual 120 mg/5 ml o 100 mg/ml en gotas"},
    "ibuprofeno": {"mg_kg": 10, "interval_h": 8, "max_mg_per_kg_day": 30,
                   "note": "Solo a partir de 3-6 meses según presentación. Tomar con comida"},
}

# Map active ingredient -> alias list (brand + active names), normalized
_MED_ALIASES = {}
for med in MEDICATIONS:
    aliases = {_norm(med["active_ingredient"])}
    for brand in med.get("brand_names", []):
        aliases.add(_norm(brand))
    _MED_ALIASES[_norm(med["active_ingredient"])] = sorted(aliases)


def _find_active_ingredient(name: str) -> str | None:
    """Given a name (brand or active, ES/EN), returns the canonical active ingredient or None."""
    n = _norm(name)
    # Common English aliases -> canonical Spanish form
    _en_alias = {
        "ibuprofen": "ibuprofeno", "acetaminophen": "paracetamol",
        "paracetamol": "paracetamol", "warfarin": "warfarina",
        "aspirin": "acido acetilsalicilico",
    }
    n = _en_alias.get(n, n)
    for ingredient, aliases in _MED_ALIASES.items():
        if n == ingredient or n in aliases:
            return ingredient
    # Partial match: the name appears inside an alias or vice versa
    for ingredient, aliases in _MED_ALIASES.items():
        for a in aliases:
            if len(n) >= 4 and (n in a or a in n):
                return ingredient
    return None


def _card_by_ingredient(ingredient: str) -> dict | None:
    """Returns the full medicine card from the active ingredient."""
    for med in MEDICATIONS:
        if _norm(med["active_ingredient"]) == ingredient:
            return med
    return None


# ---------------------------------------------------------------------------
# TOOL 1: analyze_symptoms
# ---------------------------------------------------------------------------
@tool
def analyze_symptoms(description: str, language: str = "auto") -> str:
    """Analyze free-text symptoms and suggest possible common causes,
    usual over-the-counter medicines, red flags and general advice.
    Analiza síntomas en texto libre y sugiere posibles causas comunes,
    medicamentos de venta libre habituales, señales de alarma y consejo general.

    Args:
        description: Symptoms described by the user / Síntomas que describe el usuario
            (e.g. "tengo fiebre y dolor de garganta" / "I have fever and sore throat").
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Possible causes, usual OTC medication, red flags and advice.
        Causas posibles, medicación OTC habitual, señales de alarma y consejo.
    """
    lang = language if language in ("es", "en") else _detect_lang(description)
    desc = _norm(description)
    desc_match = _expand_en_to_es(desc)
    matches = []
    for s in SYMPTOMS:
        if any(kw in desc_match for kw in s["keywords"]):
            matches.append(s)

    if not matches:
        if lang == "en":
            return (
                "I didn't recognise any specific symptom in the description. "
                "Try words like: fever, headache, cough, sore throat, "
                "diarrhea, heartburn, allergy, insomnia, dizziness... "
                "If there is chest pain, breathing difficulty, heavy bleeding or "
                f"loss of consciousness, call 112. {_disclaimer(lang)}"
            )
        return (
            "No he reconocido ningún síntoma concreto en la descripción. "
            "Prueba a describirlo con palabras como: fiebre, dolor de cabeza, tos, "
            "garganta, diarrea, acidez, alergia, insomnio, mareo... "
            "Si hay dolor torácico, dificultad para respirar, sangrado abundante o "
            f"pérdida de conciencia, llama al 112. {_disclaimer(lang)}"
        )

    sections = []
    for s in matches[:3]:  # at most 3 blocks so as not to saturate
        causes = "; ".join(
            f"{c['name']}: {c['description']}" for c in s["possible_conditions"]
        )
        if lang == "en":
            sections.append(
                f"· Symptoms related to '{s['id']}':\n"
                f"  Possible common causes: {causes}.\n"
                f"  Usual over-the-counter medication: {', '.join(s['otc_medicines'])}.\n"
                f"  ⚠️ See a doctor / go to emergency if: {'; '.join(s['red_flags'])}.\n"
                f"  Advice: {s['general_advice']}"
            )
        else:
            sections.append(
                f"· Síntomas relacionados con '{s['id']}':\n"
                f"  Posibles causas comunes: {causes}.\n"
                f"  Medicación sin receta habitual: {', '.join(s['otc_medicines'])}.\n"
                f"  ⚠️ Acude al médico/urgencias si: {'; '.join(s['red_flags'])}.\n"
                f"  Consejo: {s['general_advice']}"
            )
    if lang == "en":
        sections.append(
            "Remember: this is general guidance, not a diagnosis. "
            "If you get worse or have doubts, ask your doctor or pharmacist. "
            f"{_disclaimer(lang)}"
        )
    else:
        sections.append(
            "Recuerda: esto es orientación general, no un diagnóstico. "
            "Si empeoras o tienes dudas, consulta a tu médico o farmacéutico. "
            f"{_disclaimer(lang)}"
        )
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# TOOL 2: search_medication
# ---------------------------------------------------------------------------
@tool
def search_medication(name: str, language: str = "auto") -> str:
    """Look up a medicine card by brand or active ingredient (EN/ES).
    Busca la ficha de un medicamento por nombre comercial o principio activo.
    Devuelve indicaciones, dosis, efectos adversos, advertencias y uso en
    embarazo/lactancia, e indica si requiere receta.
    Returns indications, dosage, side effects, warnings, pregnancy/breastfeeding
    use, and whether it needs a prescription.

    Args:
        name: Brand name or active ingredient / Nombre comercial o principio activo
            (e.g. "Gelocatil" or "paracetamol").
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Full medicine card or suggestions if not found.
        Ficha completa del medicamento o sugerencias si no se encuentra.
    """
    lang = language if language in ("es", "en") else _detect_lang(name)
    ingredient = _find_active_ingredient(name)
    if ingredient is None:
        all_aliases = [a for aliases in _MED_ALIASES.values() for a in aliases]
        suggestions = get_close_matches(_norm(name), all_aliases, n=3, cutoff=0.6)
        if lang == "en":
            extra = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
            return (
                f"I didn't find '{name}' in the local database.{extra} "
                f"Try another name or ask your pharmacist. {_disclaimer(lang)}"
            )
        extra = f" ¿Querías decir: {', '.join(suggestions)}?" if suggestions else ""
        return (
            f"No he encontrado '{name}' en la base de datos local.{extra} "
            f"Prueba con otro nombre o consulta a tu farmacéutico. {_disclaimer(lang)}"
        )

    med = _card_by_ingredient(ingredient)
    if lang == "en":
        prescription = ("Requires a medical prescription" if med["requires_prescription"]
                        else "No prescription needed (OTC)")
        return (
            f"Medicine card for {med['active_ingredient'].upper()} "
            f"(brand names: {', '.join(med['brand_names'])})\n"
            f"Category: {med['category']}\n"
            f"Prescription: {prescription}\n"
            f"Indications: {med['indications']}\n"
            f"Adult dosage: {med['adult_dose']}\n"
            f"Pediatric dosage: {med['pediatric_dose']}\n"
            f"Side effects: {med['side_effects']}\n"
            f"Warnings: {med['warnings']}\n"
            f"Pregnancy: {med['pregnancy']}\n"
            f"Breastfeeding: {med['breastfeeding']}\n"
            f"{_disclaimer(lang)}"
        )
    prescription = ("SÍ requiere receta médica" if med["requires_prescription"]
                    else "NO requiere receta (venta libre)")
    return (
        f"Ficha de {med['active_ingredient'].upper()} "
        f"(nombres comerciales: {', '.join(med['brand_names'])})\n"
        f"Categoría: {med['category']}\n"
        f"Receta: {prescription}\n"
        f"Indicaciones: {med['indications']}\n"
        f"Dosis adulto: {med['adult_dose']}\n"
        f"Dosis pediátrica: {med['pediatric_dose']}\n"
        f"Efectos adversos: {med['side_effects']}\n"
        f"Advertencias: {med['warnings']}\n"
        f"Embarazo: {med['pregnancy']}\n"
        f"Lactancia: {med['breastfeeding']}\n"
        f"{_disclaimer(lang)}"
    )


# ---------------------------------------------------------------------------
# TOOL 3: calculate_dose
# ---------------------------------------------------------------------------
@tool
def calculate_dose(medication: str, weight_kg: float, language: str = "auto") -> str:
    """Calculate the pediatric dose per intake from weight in kg (EN/ES).
    Calcula la dosis pediátrica por toma a partir del peso en kg
    (regla mg/kg) para paracetamol e ibuprofeno.

    Args:
        medication: Medicine name (paracetamol or ibuprofen).
            Nombre del medicamento (paracetamol o ibuprofeno).
        weight_kg: Child weight in kilograms. Peso del niño en kilogramos.
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Milligrams per dose, interval and daily maximum.
        Miligramos por toma, intervalo entre tomas y máximo diario.
    """
    lang = language if language in ("es", "en") else _detect_lang(medication)
    ingredient = _find_active_ingredient(medication)
    if weight_kg <= 0 or weight_kg > 150:
        if lang == "en":
            return (f"Invalid weight ({weight_kg} kg). Please give the real weight in "
                    f"kilograms. {_disclaimer(lang)}")
        return f"Peso no válido ({weight_kg} kg). Indica el peso real en kilogramos. {_disclaimer(lang)}"
    if ingredient not in PEDIATRIC_DOSAGE:
        if lang == "en":
            return (
                f"I have no weight-based dosing rule for '{medication}'. "
                f"Only available for paracetamol and ibuprofen. "
                f"For other drugs, follow the leaflet or ask your pediatrician/pharmacist. {_disclaimer(lang)}"
            )
        return (
            f"No tengo regla de dosis por peso para '{medication}'. "
            f"Solo disponible para paracetamol e ibuprofeno. "
            f"Para otros fármacos, sigue el prospecto o consulta al pediatra/farmacéutico. {_disclaimer(lang)}"
        )
    rule = PEDIATRIC_DOSAGE[ingredient]
    mg_per_dose = round(rule["mg_kg"] * weight_kg)
    max_per_day = round(rule["max_mg_per_kg_day"] * weight_kg)
    if lang == "en":
        return (
            f"Guidance dose of {ingredient} for {weight_kg} kg: {mg_per_dose} mg per dose "
            f"every {rule['interval_h']} hours (maximum {max_per_day} mg/day). "
            f"Note: {rule['note']}. "
            f"Always use a dosing syringe, not household spoons. "
            f"If the child is under 2 years old or has a chronic disease, confirm the dose with the pediatrician. {_disclaimer(lang)}"
        )
    return (
        f"Dosis orientativa de {ingredient} para {weight_kg} kg: {mg_per_dose} mg por toma "
        f"cada {rule['interval_h']} horas (máximo {max_per_day} mg/día). "
        f"Nota: {rule['note']}. "
        f"Usa siempre jeringa dosificadora, no cucharas caseras. "
        f"Si el niño tiene menos de 2 años o enfermedad crónica, confirma la dosis con el pediatra. {_disclaimer(lang)}"
    )


# ---------------------------------------------------------------------------
# TOOL 4: check_interaction
# ---------------------------------------------------------------------------
@tool
def check_interaction(medication_1: str, medication_2: str, language: str = "auto") -> str:
    """Check whether two medicines (or medicine + alcohol/grapefruit) interact (EN/ES).
    Comprueba si dos medicamentos (o medicamento + alcohol/pomelo) interactúan.
    Devuelve severidad (leve/moderada/grave), explicación y recomendación.
    Returns severity (mild/moderate/severe), explanation and recommendation.

    Args:
        medication_1: First drug (brand or active ingredient).
            Primer fármaco (nombre comercial o principio activo).
        medication_2: Second drug, alcohol, grapefruit juice, etc.
            Segundo fármaco, alcohol, zumo de pomelo, etc.
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Interaction description or notice that there is no local record.
        Descripción de la interacción o aviso de que no hay registro local.
    """
    lang = language if language in ("es", "en") else _detect_lang(medication_1, medication_2)
    a1 = _find_active_ingredient(medication_1)
    a2 = _find_active_ingredient(medication_2)
    # Alcohol, grapefruit and vitamin K are not in the medicine database: accepted as-is
    # Normalize English aliases for the lookup (keeping `lang` for the output)
    _lookup_alias = {"grapefruit": "zumo de pomelo", "grapefruit juice": "zumo de pomelo",
                     "warfarin": "warfarina", "ibuprofen": "ibuprofeno",
                     "acetaminophen": "paracetamol"}
    a1 = a1 or _lookup_alias.get(_norm(medication_1), _norm(medication_1))
    a2 = a2 or _lookup_alias.get(_norm(medication_2), _norm(medication_2))

    for interaction in INTERACTIONS:
        pair = {_norm(interaction["drug_a"]), _norm(interaction["drug_b"])}
        if {a1, a2} == pair:
            icon = {"leve": "🟢", "moderada": "🟡", "grave": "🔴"}.get(interaction["severity"], "⚪")
            if lang == "en":
                sev_en = {"leve": "MILD", "moderada": "MODERATE", "grave": "SEVERE"}.get(
                    interaction["severity"], interaction["severity"].upper())
                return (
                    f"{icon} {sev_en} interaction between "
                    f"{interaction['drug_a']} and {interaction['drug_b']}:\n"
                    f"{interaction['description']}\n"
                    f"Recommendation: {interaction['recommendation']}\n"
                    f"{_disclaimer(lang)}"
                )
            return (
                f"{icon} Interacción {interaction['severity'].upper()} entre "
                f"{interaction['drug_a']} y {interaction['drug_b']}:\n"
                f"{interaction['description']}\n"
                f"Recomendación: {interaction['recommendation']}\n"
                f"{_disclaimer(lang)}"
            )
    if lang == "en":
        return (
            f"There is no documented interaction between '{medication_1}' and "
            f"'{medication_2}' in the local database (26 common interactions). "
            f"That does not guarantee none exists: always ask your pharmacist "
            f"before combining medicines, especially with anticoagulants, "
            f"antihypertensives or antidepressants. {_disclaimer(lang)}"
        )
    return (
        f"No hay ninguna interacción documentada entre '{medication_1}' y "
        f"'{medication_2}' en la base local (26 interacciones frecuentes). "
        f"Eso no garantiza que no exista: consulta siempre al farmacéutico "
        f"antes de combinar medicamentos, sobre todo con anticoagulantes, "
        f"antihipertensivos o antidepresivos. {_disclaimer(lang)}"
    )


# ---------------------------------------------------------------------------
# TOOL 5: check_contraindication
# ---------------------------------------------------------------------------
@tool
def check_contraindication(medication: str, condition: str, language: str = "auto") -> str:
    """Check whether a medicine is problematic with a patient condition (EN/ES).
    Comprueba si un medicamento es problemático con una condición del paciente:
    embarazo, lactancia, niños, hipertensión, úlcera/gastritis, riñón, hígado,
    asma, diabetes, anticoagulación, glaucoma o edad avanzada.
    Pregnancy, breastfeeding, children, hypertension, ulcer/gastritis, kidney,
    liver, asthma, diabetes, anticoagulation, glaucoma or advanced age.

    Args:
        medication: Brand or active ingredient. Nombre comercial o principio activo.
        condition: Patient condition (e.g. "pregnancy", "hypertension", "my 5-year-old child").
            Condición del paciente (ej: "embarazo", "hipertensión", "mi hijo de 5 años").
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Specific warnings and usually safer alternatives.
        Advertencias específicas y alternativas habituales más seguras.
    """
    lang = language if language in ("es", "en") else _detect_lang(medication, condition)
    cond_norm = _expand_en_to_es(_norm(condition))
    entry = None
    for c in CONTRAINDICATIONS:
        if any(kw in cond_norm for kw in c["keywords"]):
            entry = c
            break
    if entry is None:
        available = ", ".join(c["condition"] for c in CONTRAINDICATIONS)
        if lang == "en":
            return (
                f"I don't recognise the condition '{condition}'. "
                f"Available conditions: {available}. {_disclaimer(lang)}"
            )
        return (
            f"No reconozco la condición '{condition}'. "
            f"Condiciones disponibles: {available}. {_disclaimer(lang)}"
        )

    ingredient = _find_active_ingredient(medication)
    display_name = ingredient or medication
    avoid_norm = {_norm(m) for m in entry["avoid"]}
    caution_norm = {_norm(m) for m in entry["caution"]}

    if ingredient and _norm(ingredient) in avoid_norm:
        level = "🔴 AVOID" if lang == "en" else "🔴 EVITAR"
    elif ingredient and _norm(ingredient) in caution_norm:
        level = "🟡 CAUTION" if lang == "en" else "🟡 PRECAUCIÓN"
    else:
        level = ("🟢 No recorded restriction for this condition" if lang == "en"
                 else "🟢 Sin restricción registrada para esta condición")

    if lang == "en":
        return (
            f"{level}: {display_name} with {entry['condition']}.\n"
            f"Context: {entry['description']}.\n"
            f"Medicines to avoid: {', '.join(entry['avoid']) or '—'}.\n"
            f"Use with caution: {', '.join(entry['caution']) or '—'}.\n"
            f"Usually safer alternatives: {', '.join(entry['usually_safe']) or 'ask your doctor'}.\n"
            f"Note: {entry['note']}\n"
            f"{_disclaimer(lang)}"
        )
    return (
        f"{level}: {display_name} con {entry['condition']}.\n"
        f"Contexto: {entry['description']}.\n"
        f"Medicamentos a evitar: {', '.join(entry['avoid']) or '—'}.\n"
        f"Usar con precaución: {', '.join(entry['caution']) or '—'}.\n"
        f"Alternativas habituales más seguras: {', '.join(entry['usually_safe']) or 'consultar al médico'}.\n"
        f"Nota: {entry['note']}\n"
        f"{_disclaimer(lang)}"
    )


# ---------------------------------------------------------------------------
# TOOL 6: assess_urgency (bilingual EN/ES)
# ---------------------------------------------------------------------------
_URGENCY_RULES = [
    ("112/urgencias",
     ["dolor en el pecho", "dolor de pecho", "duele el pecho", "dolor toracico",
      "opresion en el pecho", "presion en el pecho", "dolor de corazon",
      "no puedo respirar", "cuesta respirar", "dificultad para respirar",
      "falta el aire", "falta de aire", "me ahogo", "ahogo", "asfixia",
      "desmayo", "perdida de conciencia", "convulsion", "convulsiones",
      "sangrado abundante", "no para de sangrar", "hemorragia",
      "ictus", "cara torcida", "no puedo hablar", "debilidad en un lado",
      "alergia grave", "anafilaxia", "hinchazon de lengua", "hinchazon de labios",
      "quemadura extensa", "intento de suicidio", "quiero morir", "sobredosis",
      # English equivalents (normalized, no accents)
      "chest pain", "chest hurts", "my chest hurts", "pressure in chest",
      "cant breathe", "cannot breathe", "difficulty breathing", "shortness of breath",
      "choking", "faint", "fainted", "loss of consciousness", "seizure", "seizures",
      "heavy bleeding", "bleeding a lot", "hemorrhage", "stroke", "face drooping",
      "cant speak", "cannot speak", "weakness on one side",
      "severe allergy", "anaphylaxis", "swollen tongue", "swollen lips",
      "extensive burn", "suicide attempt", "want to die", "overdose", "emergency"],
     "Signos de alarma detectados. Llama al 112 o acude a urgencias de inmediato. / "
     "Red flags detected. Call 112 / go to emergency immediately."),
    ("médico en 24-48 h / doctor within 24-48 h",
     ["fiebre de mas de 3 dias", "fiebre persistente", "sangre en heces", "sangre en orina",
      "vomitos persistentes", "dolor intenso", "no mejora", "empeora", "infeccion de orina",
      "embarazada", "bebe con fiebre", "supuracion", "pus", "manchas en la piel",
      # English equivalents
      "fever for more than 3 days", "persistent fever", "blood in stool", "blood in urine",
      "persistent vomiting", "severe pain", "not getting better", "getting worse",
      "urinary infection", "pregnant", "baby with fever", "pus", "skin rash", "skin spots"],
     "Conviene valoración médica en 24-48 h (centro de salud o pediatra). / "
     "You should see a doctor within 24-48 h (health center or pediatrician)."),
]


@tool
def assess_urgency(description: str, language: str = "auto") -> str:
    """Assess urgency level with triage rules (EN/ES).
    Evalúa el nivel de urgencia de unos síntomas con reglas de triaje:
    112/urgencias, médico en 24-48 h, o autocuidado con medicación sin receta.
    112/emergency, doctor in 24-48 h, or self-care with OTC medication.

    Args:
        description: Symptoms described by the user. Síntomas que describe el usuario.
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Urgency level (🔴 🟡 🟢), reason and what to do.
        Nivel de urgencia (🔴 🟡 🟢), motivo y qué hacer.
    """
    lang = language if language in ("es", "en") else _detect_lang(description)
    desc = _norm(description)
    for level, keys, action in _URGENCY_RULES:
        if any(k in desc for k in keys):
            icon = "🔴" if "112" in level else "🟡"
            if lang == "en":
                level_en = "112/emergency" if "112" in level else "doctor within 24-48 h"
                action_en = (
                    "Red flags detected. Call 112 / go to emergency immediately."
                    if "112" in level else
                    "You should see a doctor within 24-48 h (health center or pediatrician)."
                )
                return (
                    f"{icon} Level: {level_en}.\nReason: {action_en}\n"
                    f"Meanwhile: do not drive if you feel dizzy, ask someone nearby for help "
                    f"and bring your medication list.\n{_disclaimer(lang)}"
                )
            return (
                f"{icon} Nivel: {level}.\nMotivo: {action}\n"
                f"Mientras tanto: no conduzcas si estás mareado, pide ayuda a alguien cercano "
                f"y lleva la lista de medicamentos que tomas.\n{_disclaimer(lang)}"
            )
    if lang == "en":
        return (
            "🟢 Level: self-care / pharmacy.\n"
            "No red flags detected in the description. You can manage it with "
            "general measures and OTC medication, and ask your pharmacist. "
            "If it gets worse, high persistent fever appears, or any red flag shows up "
            f"(chest pain, breathing difficulty, bleeding, confusion), escalate and seek care.\n{_disclaimer(lang)}"
        )
    return (
        "🟢 Nivel: autocuidado / farmacia.\n"
        "No se detectan señales de alarma en la descripción. Puedes tratarlo con "
        "medidas generales y medicación sin receta, y consultar al farmacéutico. "
        "Si empeora, aparece fiebre alta persistente o surge cualquier señal de alarma "
        f"(dolor torácico, dificultad respiratoria, sangrado, confusión), sube el nivel y busca atención.\n{_disclaimer(lang)}"
    )


# ---------------------------------------------------------------------------
# TOOL 7: find_pharmacy
# ---------------------------------------------------------------------------
@tool
def find_pharmacy(location: str, language: str = "auto") -> str:
    """Search pharmacies (simulated) by city (EN/ES).
    Busca farmacias (simulado) por ciudad. Si se pide 'guardia' o '24 horas',
    filtra solo las de guardia. If 'on duty' or '24 hours' is requested,
    filters only on-duty ones.

    Args:
        location: City or area (e.g. "Madrid", "on-duty pharmacy in Barcelona").
            Ciudad o zona (ej: "Madrid", "farmacia de guardia en Barcelona").
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        List of pharmacies with address, phone and hours.
        Lista de farmacias con dirección, teléfono y horario.
    """
    lang = language if language in ("es", "en") else _detect_lang(location)
    loc = _norm(location)
    duty_only = (
        "guardia" in loc or "24 horas" in loc or "24h" in loc
        or "on duty" in loc or "on-duty" in loc or "24 hours" in loc or "24-hour" in loc
    )
    candidates = [
        f for f in PHARMACIES
        if _norm(f["city"]) in loc or _norm(f["name"]) in loc or _norm(f["address"]) in loc
        or loc in _norm(f["city"])
    ]
    if duty_only:
        candidates = [f for f in candidates if f["on_duty"]]
    if not candidates:  # no city filter: show the on-duty ones
        candidates = [f for f in PHARMACIES if f["on_duty"]] if duty_only else PHARMACIES[:4]

    lines = []
    for f in candidates[:5]:
        mark = " 🌙 ON DUTY 24h" if (f["on_duty"] and lang == "en") else (" 🌙 DE GUARDIA 24h" if f["on_duty"] else "")
        lines.append(
            f"· {f['name']}{mark}\n  {f['address']} | Tel: {f['phone']} | {f['opening_hours']}"
        )
    if lang == "en":
        lines.append(
            "Simulated demo data. For real on-duty pharmacies, "
            f"check your official pharmacists' association or dial 010/012 in your city. {_disclaimer(lang)}"
        )
    else:
        lines.append(
            "Datos simulados de demostración. Para farmacias de guardia reales, "
            f"consulta a tu colegio oficial de farmacéuticos o el 010/012 de tu ciudad. {_disclaimer(lang)}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TOOL 8: calculate (safe numexpr parser)
# ---------------------------------------------------------------------------
@tool
def calculate(expression: str, language: str = "auto") -> str:
    """Evaluate a math expression safely (EN/ES).
    Evalúa una expresión matemática de forma segura (útil para dosis,
    conversiones mg/ml o cálculos de tomas).

    Args:
        expression: Math expression (e.g. "15*22", "120/5", "(500*3)/7").
            Expresión matemática (ej: "15*22", "120/5", "(500*3)/7").
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Calculation result or error message. Resultado del cálculo o mensaje de error.
    """
    lang = language if language in ("es", "en") else _detect_lang(expression)
    import numexpr
    expr = expression.strip().replace(",", ".").replace("×", "*").replace("÷", "/")
    allowed = set("0123456789+-*/(). %")
    if not expr or any(c not in allowed for c in expr):
        if lang == "en":
            return (
                f"Invalid expression: '{expression}'. "
                f"Use only numbers and operators + - * / ( ) % (e.g. '15*22'). {_disclaimer(lang)}"
            )
        return (
            f"Expresión no válida: '{expression}'. "
            f"Usa solo números y operadores + - * / ( ) % (ej: '15*22'). {_disclaimer(lang)}"
        )
    try:
        result = float(numexpr.evaluate(expr))
        if result.is_integer():
            result = int(result)
        if lang == "en":
            return f"Result of '{expression}': {result}\n{_disclaimer(lang)}"
        return f"Resultado de '{expression}': {result}\n{_disclaimer(lang)}"
    except Exception as e:
        if lang == "en":
            return f"Error evaluating '{expression}': {e}\n{_disclaimer(lang)}"
        return f"Error evaluando '{expression}': {e}\n{_disclaimer(lang)}"


# ---------------------------------------------------------------------------
# TOOL 9: query_pharmacovigilance  ->  internet API #1 (openFDA, NIH cloud)
# ---------------------------------------------------------------------------
# Active ingredient in Spanish (local base) -> USAN generic name used by openFDA
_USAN_BY_INGREDIENT = {
    "paracetamol": "acetaminophen",
    "acido acetilsalicilico": "aspirin",
    "ibuprofeno": "ibuprofen",
    "loratadina": "loratadine",
    "cetirizina": "cetirizine",
    "omeprazol": "omeprazole",
    "amoxicilina": "amoxicillin",
    "amoxicilina/acido clavulanico": "amoxicillin and clavulanate potassium",
    "diclofenaco": "diclofenac",
    "salbutamol (albuterol)": "albuterol",
    "atorvastatina": "atorvastatin",
    "enalapril": "enalapril maleate",
    "losartan": "losartan potassium",
    "metformina": "metformin hydrochloride",
    "warfarina": "warfarin sodium",
    "diazepam": "diazepam",
    "loperamida": "loperamide hydrochloride",
    "melatonina": "melatonin",
}


def _openfda_terms(ingredient: str) -> list[str]:
    """Search candidates for openFDA (USAN, brand and local name)."""
    n = _norm(ingredient)
    terms = []
    usan = _USAN_BY_INGREDIENT.get(n)
    if usan:
        terms.append(usan)
    # Known local brand (e.g. "augmentin" for amoxicillin+clavulanate)
    for med in MEDICATIONS:
        if _norm(med["active_ingredient"]) == n:
            for brand in med.get("brand_names", []):
                terms.append(_norm(brand))
            break
    terms.append(n)
    # No duplicates, keeping the order
    seen, ordered = set(), []
    for t in terms:
        if t and t not in seen:
            seen.add(t)
            ordered.append(t)
    return ordered


def _search_openfda(ingredient: str) -> tuple[dict, str] | None:
    """Queries openFDA (FAERS) until it finds reports for the drug.

    Tries several exact fields (generic, medicinalproduct, brand) for
    different candidate names, within a time budget.
    Returns (payload, matched_term) or None.
    """
    fields = (
        "patient.drug.openfda.generic_name",
        "patient.drug.medicinalproduct",
        "patient.drug.openfda.brand_name",
    )
    start = time.monotonic()
    for term in _openfda_terms(ingredient)[:3]:
        for field in fields:
            remaining = _remaining(start, API_BUDGET)
            if remaining < 2.0:
                return None
            try:
                payload = _get_json(
                    OPENFDA_EVENT_URL,
                    params={
                        "search": f'{field}:"{term.upper()}"',
                        "limit": 100,
                    },
                    timeout=min(HTTP_TIMEOUT, remaining),
                )
            except Exception:
                continue
            if isinstance(payload, dict) and payload.get("results"):
                return payload, term.upper()
    return None


@tool
def query_pharmacovigilance(name: str, language: str = "auto") -> str:
    """Look up real-world adverse-event reports for a medicine (API internet #1: openFDA).
    Busca notificaciones de farmacovigilancia (efectos adversos declarados) de un
    medicamento en la API pública openFDA / FAERS (servicio en la nube del NIH,
    sin autenticación). Devuelve nº de casos, reacciones más frecuentes en la
    muestra y desenlace, con la salvedad de que la correlación implica causalidad.
    Returns number of reported cases, most frequent reactions in the sample,
    outcomes and the causality caveat.

    Args:
        name: Brand or active ingredient (e.g. "paracetamol", "Gelocatil").
            Nombre comercial o principio activo (ej: "paracetamol", "Gelocatil").
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Pharmacovigilance summary, or a notice if there are no reports or the API
        is unreachable. Resumen de farmacovigilancia o aviso de que no hay
        reportes / la API no está disponible.
    """
    lang = language if language in ("es", "en") else _detect_lang(name)
    ingredient = _find_active_ingredient(name) or name

    try:
        search = _search_openfda(ingredient)
    except Exception:
        search = None

    if search is None:
        if lang == "en":
            return (
                f"No adverse-event reports found in openFDA/FAERS for '{name}'. "
                f"That does not mean the medicine is safe or unsafe: the database only "
                f"contains what has been voluntarily reported. "
                f"Check the leaflet or ask your pharmacist. {_disclaimer(lang)}"
            )
        return (
            f"No he encontrado notificaciones de farmacovigilancia en openFDA/FAERS para "
            f"'{name}'. Eso no significa que el medicamento sea seguro o peligroso: la "
            f"base solo recoge lo que se ha declarado de forma voluntaria. Revisa el "
            f"prospecto o consulta al farmacéutico. {_disclaimer(lang)}"
        )

    payload, term = search
    reports = payload.get("results", [])
    total = payload.get("meta", {}).get("results", {}).get("total", len(reports))

    # Count of reactions and outcomes in the retrieved sample
    reaction_counts: dict[str, int] = {}
    outcome_counts: dict[str, int] = {}
    serious_count = 0
    for r in reports:
        if str(r.get("serious")) == "1":
            serious_count += 1
        for reaction in r.get("patient", {}).get("reaction", []) or []:
            pt = (reaction.get("reactionmeddrapt") or "").strip()
            if pt:
                reaction_counts[pt] = reaction_counts.get(pt, 0) + 1
        outcome_code = (r.get("patient", {}).get("patientoutcome") or "").strip()
        if outcome_code:
            label = {"DE": "recovered/resolved", "LT": "life-threatening",
                     "HO": "hospitalization", "DS": "death", "OT": "other"}.get(
                outcome_code, outcome_code)
            outcome_counts[label] = outcome_counts.get(label, 0) + 1

    top_reactions = sorted(reaction_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    top_outcomes = sorted(outcome_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
    sample_size = len(reports)

    if lang == "en":
        lines = [
            f"Pharmacovigilance report for {term} (source: openFDA / FAERS, API internet).",
            f"· Total adverse-event reports in the database: {total:,}",
            f"· Sample analysed: {sample_size} reports ({serious_count} marked serious).",
            "· Most frequent reactions in the sample:",
        ]
        lines += [f"    - {r} ({c})" for r, c in top_reactions] or ["    - not reported"]
        if top_outcomes:
            lines.append("· Outcomes in the sample: " + ", ".join(
                f"{k}: {v}" for k, v in top_outcomes))
        lines.append(
            "· Reading: these are spontaneous reports, correlation does not imply "
            "causation, and under-reporting is common. Not a substitute for the "
            f"leaflet or your doctor. {_disclaimer(lang)}"
        )
        return "\n".join(lines)

    lines = [
        f"Informe de farmacovigilancia de {term} (fuente: openFDA / FAERS, API internet).",
        f"· Total de notificaciones de reacciones adversas en la base: {total:,}",
        f"· Muestra analizada: {sample_size} notificaciones ({serious_count} marcadas como graves).",
        "· Reacciones más frecuentes en la muestra:",
    ]
    lines += [f"    - {r} ({c})" for r, c in top_reactions] or ["    - no informadas"]
    if top_outcomes:
        lines.append("· Desenlace en la muestra: " + ", ".join(
            f"{k}: {v}" for k, v in top_outcomes))
    lines.append(
        "· Cómo leerlo: son notificaciones espontáneas, la correlación no implica "
        "causalidad y el subregistro es habitual. No sustituye al prospecto ni a "
        f"tu médico. {_disclaimer(lang)}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TOOL 10: find_real_pharmacy  ->  internet API #2 (OpenStreetMap, OSM cloud)
# ---------------------------------------------------------------------------
def _geocode(address: str, timeout: float | None = None) -> tuple[float, float, str, str | None] | None:
    """(lat, lon, name, locality) of an address via Nominatim (no API key)."""
    data = _get_json(
        NOMINATIM_URL,
        params={"q": address, "format": "jsonv2", "limit": 1, "addressdetails": 1},
        timeout=timeout,
    )
    if not data:
        return None
    first = data[0]
    addr = first.get("address", {}) or {}
    locality = next(
        (addr[k] for k in ("city", "town", "village", "municipality", "suburb", "county")
         if addr.get(k)),
        None,
    )
    return (float(first["lat"]), float(first["lon"]),
            first.get("display_name", address), locality)


def _overpass_pharmacies(lat: float, lon: float, radius_m: int = 3000,
                         max_time: float = HTTP_TIMEOUT) -> list[dict]:
    """Nearby pharmacies (amenity=pharmacy) via Overpass API, with several mirrors.

    `max_time` limits the total search time (the tool's budget).
    """
    query = (
        f'[out:json][timeout:25];(node["amenity"="pharmacy"]'
        f"(around:{radius_m},{lat},{lon}););out center tags 15;"
    )
    start = time.monotonic()
    last_error = None
    # Pass 1: the three mirrors. Pass 2: repeat the main one (usually a
    # transient 504/429 due to saturation) if budget remains.
    order = list(OVERPASS_URLS) + [OVERPASS_URLS[0]]
    for idx, endpoint in enumerate(order):
        remaining = _remaining(start, max_time)
        if remaining < 2.0:
            break
        try:
            payload = _get_json(endpoint, data={"data": query},
                                timeout=min(HTTP_TIMEOUT, remaining))
        except Exception as e:  # mirror down or saturated -> try the next one
            last_error = e
            if idx == len(OVERPASS_URLS) - 1 and _remaining(start, max_time) > 4.0:
                time.sleep(1.5)
            continue
        elements = payload.get("elements") if isinstance(payload, dict) else None
        if elements is None:
            continue
        pharmacies = []
        for el in elements:
            tags = el.get("tags", {}) or {}
            elon = el.get("lon", el.get("center", {}).get("lon"))
            elat = el.get("lat", el.get("center", {}).get("lat"))
            pharmacies.append({
                "name": tags.get("name", "Farmacia"),
                "address": " ".join(filter(None, [
                    tags.get("addr:street", ""),
                    tags.get("addr:housenumber", ""),
                ])).strip() or tags.get("addr:full", ""),
                "city": tags.get("addr:city", ""),
                "phone": tags.get("phone", tags.get("contact:phone", "")),
                "opening_hours": tags.get("opening_hours", ""),
                "lat": float(elat) if elat is not None else None,
                "lon": float(elon) if elon is not None else None,
            })
        if pharmacies:
            return pharmacies
    if last_error:
        raise last_error
    return []


def _nominatim_pharmacies(address: str, locality: str | None = None,
                          max_time: float = HTTP_TIMEOUT) -> list[dict]:
    """Fallback: search pharmacies directly in Nominatim (without Overpass).

    Useful when Overpass is saturated or the address does not geocode well.
    Only keeps results whose category is amenity=pharmacy.
    """
    queries = [f"pharmacy in {address}", f"farmacia en {address}"]
    if locality and _norm(locality) != _norm(address):
        queries += [f"pharmacy in {locality}", f"farmacia en {locality}"]

    start = time.monotonic()
    pharmacies, seen = [], set()
    for query in queries:
        remaining = _remaining(start, max_time)
        if remaining < 2.0:
            break
        try:
            data = _get_json(
                NOMINATIM_URL,
                params={"q": query, "format": "jsonv2", "limit": 10, "addressdetails": 0},
                timeout=min(HTTP_TIMEOUT, remaining),
            )
        except Exception:
            continue
        for r in data or []:
            if r.get("category") != "amenity" or r.get("type") != "pharmacy":
                continue
            if r.get("osm_id") in seen:
                continue
            seen.add(r.get("osm_id"))
            parts = [p.strip() for p in (r.get("display_name") or "").split(",")]
            pharmacies.append({
                "name": r.get("name") or (parts[0] if parts else "Farmacia"),
                "address": ", ".join(parts[1:3]),
                "city": ", ".join(parts[3:5]),
                "phone": "",
                "opening_hours": "",
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
            })
        if pharmacies:
            break
    return pharmacies


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance (haversine) between two coordinates."""
    earth_radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return earth_radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@tool
def find_real_pharmacy(location: str, language: str = "auto") -> str:
    """Find real pharmacies near a place using OpenStreetMap (API internet #2).
    Busca farmacias REALES cercanas a una ciudad o dirección usando las APIs
    públicas de OpenStreetMap (Nominatim para geocodificar + Overpass para los
    puntos de farmacia). Servicio en la nube distinto de openFDA y sin
    autenticación. Si la red falla, indica cómo usar la tool local simulada.
    Returns up to 5 nearby pharmacies with distance, address, hours and phone.

    Args:
        location: City, district or street address (e.g. "Barcelona",
            "20 Oxford St, London"). Ciudad, barrio o dirección
            (ej: "Madrid", "Gran Vía 20, Madrid").
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        List of real pharmacies with distance and details, or an unavailability notice.
        Lista de farmacias reales con distancia y datos, o aviso de indisponibilidad.
    """
    lang = language if language in ("es", "en") else _detect_lang(location)
    start = time.monotonic()

    # 1) Geocode the location (Nominatim) so distances can be measured.
    #    Capped to 6 s so as not to eat the budget Overpass and the Nominatim
    #    fallback need within GEO_BUDGET.
    try:
        geocode = _geocode(
            location,
            timeout=min(6.0, HTTP_TIMEOUT, _remaining(start, GEO_BUDGET)))
    except Exception:
        geocode = None
    reference = geocode[:2] if geocode else None
    locality = geocode[3] if geocode else None

    # 2) Pharmacies: Overpass around the reference point (rich data)
    pharmacies: list[dict] = []
    overpass_error: Exception | None = None
    if reference and _remaining(start, GEO_BUDGET) > 3.0:
        try:
            pharmacies = _overpass_pharmacies(
                *reference,
                max_time=min(OVERPASS_MAX, _remaining(start, GEO_BUDGET)))
        except Exception as e:
            overpass_error = e

    # 3) Fallback: direct pharmacy search in Nominatim (time reserved with
    #    NOMINATIM_MAX so Overpass does not take the whole budget)
    if not pharmacies and _remaining(start, GEO_BUDGET) > 3.0:
        try:
            pharmacies = _nominatim_pharmacies(
                location, locality,
                max_time=min(NOMINATIM_MAX, _remaining(start, GEO_BUDGET)))
        except Exception:
            pharmacies = []

    # 3b) Overpass fails transiently (504/429 due to saturation): if the
    # Nominatim fallback only returned far-away pharmacies, retry Overpass
    # one last time before accepting the result.
    if reference and pharmacies and _remaining(start, GEO_BUDGET) > 4.0:
        previous_distances = [
            _distance_km(reference[0], reference[1], f["lat"], f["lon"])
            for f in pharmacies if f.get("lat") is not None and f.get("lon") is not None
        ]
        if previous_distances and min(previous_distances) > 5.0:
            time.sleep(1.0)
            try:
                retry = _overpass_pharmacies(
                    *reference,
                    max_time=min(OVERPASS_MAX, _remaining(start, GEO_BUDGET)))
            except Exception:
                retry = []
            if retry:
                pharmacies = retry

    if not pharmacies:
        reason = type(overpass_error).__name__ if overpass_error else "no results"
        if lang == "en":
            return (
                f"No pharmacies found on OpenStreetMap for '{location}' ({reason}). "
                f"Try a bigger town or a more precise address, retry in a moment, or use "
                f"the local simulated search (tool 'find_pharmacy'). {_disclaimer(lang)}"
            )
        return (
            f"No he encontrado farmacias en OpenStreetMap para '{location}' ({reason}). "
            f"Prueba con una ciudad más grande o una dirección más concreta, repite la "
            f"consulta en unos segundos o usa la búsqueda local simulada (tool "
            f"'find_pharmacy'). {_disclaimer(lang)}"
        )

    if reference:
        lat, lon = reference
        for f in pharmacies:
            if f.get("lat") is not None and f.get("lon") is not None:
                f["distance_km"] = round(_distance_km(lat, lon, f["lat"], f["lon"]), 2)
            else:
                f["distance_km"] = None
        pharmacies.sort(key=lambda f: (f["distance_km"] is None, f["distance_km"] or 0))
    else:
        for f in pharmacies:
            f["distance_km"] = None

    # With a geographic reference, only show genuinely nearby pharmacies
    # (the Nominatim fallback can return points from other areas).
    if reference:
        nearby = [f for f in pharmacies
                  if f["distance_km"] is not None and f["distance_km"] <= 5.0][:5]
        if not nearby:
            nearby = pharmacies[:5]
    else:
        nearby = pharmacies[:5]

    # Notice if the closest match is far away (e.g. imprecise geocoding)
    closest = next((f["distance_km"] for f in nearby
                    if f.get("distance_km") is not None), None)
    location_note = ""
    if closest is not None and closest > 5.0:
        if lang == "en":
            location_note = (
                f"· The closest match is {closest} km away: check the spelling of the "
                f"place or add the street/city. "
            )
        else:
            location_note = (
                f"· Lo más cercano está a {closest} km: revisa cómo está escrita la "
                f"ubicación o añade calle y ciudad. "
            )

    lines = []
    if lang == "en":
        lines.append(f"Real pharmacies near '{location}' (OpenStreetMap, API internet):")
        for f in nearby:
            dist = f"{f['distance_km']} km" if f["distance_km"] is not None else "distance n/a"
            extras = " | ".join(x for x in [
                f["address"], f["city"], f["phone"] and f"Tel: {f['phone']}",
                f["opening_hours"] and f"Hours: {f['opening_hours']}",
            ] if x)
            lines.append(f"· {f['name']} ({dist})" + (f"\n  {extras}" if extras else ""))
        lines.append(
            location_note +
            "Data © OpenStreetMap contributors (ODbL). Opening hours may be "
            "outdated: call before going. " + _disclaimer(lang)
        )
    else:
        lines.append(f"Farmacias reales cerca de '{location}' (OpenStreetMap, API internet):")
        for f in nearby:
            dist = f"{f['distance_km']} km" if f["distance_km"] is not None else "distancia n/d"
            extras = " | ".join(x for x in [
                f["address"], f["city"], f["phone"] and f"Tel: {f['phone']}",
                f["opening_hours"] and f"Horario: {f['opening_hours']}",
            ] if x)
            lines.append(f"· {f['name']} ({dist})" + (f"\n  {extras}" if extras else ""))
        lines.append(
            location_note +
            "Datos © de los colaboradores de OpenStreetMap (ODbL). El horario puede "
            "desactualizarse: llama antes de ir. " + _disclaimer(lang)
        )
    return "\n".join(lines)


# List of tools handed to the agent
TOOLS = [
    analyze_symptoms,
    search_medication,
    calculate_dose,
    check_interaction,
    check_contraindication,
    assess_urgency,
    find_pharmacy,
    calculate,
    query_pharmacovigilance,
    find_real_pharmacy,
]
