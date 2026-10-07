#!/usr/bin/env python3
"""
Tools del agente de orientación de medicamentos.

Cada tool es una función decorada con @tool de LangChain:
- El nombre y el docstring los usa Gemini para decidir cuándo llamarla.
- Todas devuelven texto plano (str) con la información encontrada.
- Los datos viven en data/*.json para poder ampliarlos sin tocar código.

Tools disponibles:
1. analizar_sintomas      - síntomas en texto libre -> causas posibles + OTC + alarmas
2. buscar_medicamento      - nombre comercial o principio activo -> ficha completa
3. calcular_dosis           - medicamento + peso (kg) -> dosis pediátrica por toma
4. verificar_interaccion    - 2 fármacos -> interacción, severidad y recomendación
5. consultar_contraindicacion - fármaco + condición (embarazo, hipertensión...) -> advertencias
6. evaluar_urgencia         - descripción de síntomas -> triaje (hogar / médico / 112)
7. buscar_farmacia          - ubicación -> farmacias cercanas (simulado)
8. calcular                - expresión matemática -> resultado (parser seguro con numexpr)
"""

import json
import unicodedata
from difflib import get_close_matches
from pathlib import Path

from langchain_core.tools import tool

DATA_DIR = Path(__file__).parent / "data"


def _load(nombre: str):
    """Carga un JSON de data/ y lo devuelve como lista."""
    with open(DATA_DIR / nombre, encoding="utf-8") as f:
        return json.load(f)


def _norm(texto: str) -> str:
    """Normaliza texto: minúsculas + sin tildes, para comparar sin fallos."""
    texto = texto.lower().strip()
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def _detect_lang(*texts: str) -> str:
    """Detecta 'en' o 'es' a partir de los textos de entrada.

    Usa domain.i18n como fuente única; con fallback local si el import falla
    (p. ej. al importar tools.py de forma aislada).
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


# Mapa EN -> ES para que el matching de síntomas/condiciones funcione en inglés
# sin tener que duplicar los JSON (que siguen en español).
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
    # condiciones
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
    """Añade equivalentes en español al texto normalizado para el matching."""
    extra = [es for en, es in _EN_TO_ES.items() if en in desc_norm]
    if extra:
        return desc_norm + " " + " ".join(extra)
    return desc_norm


# Carga de datasets en memoria (una sola vez al importar el módulo)
MEDICAMENTOS = _load("medicamentos.json")
SINTOMAS = _load("sintomas.json")
INTERACCIONES = _load("interacciones.json")
CONTRAINDICACIONES = _load("contraindicaciones.json")
FARMACIAS = _load("farmacias.json")

# Reglas de dosis pediátrica por principio activo (mg por kg y por toma)
DOSIS_PEDIATRICA = {
    "paracetamol": {"mg_kg": 15, "intervalo_h": 6, "max_mg_kg_dia": 60,
                    "nota": "Jarabe habitual 120 mg/5 ml o 100 mg/ml en gotas"},
    "ibuprofeno": {"mg_kg": 10, "intervalo_h": 8, "max_mg_kg_dia": 30,
                   "nota": "Solo a partir de 3-6 meses según presentación. Tomar con comida"},
}

# Mapa principio activo -> lista de alias (nombres comerciales + activo), normalizados
_ALIAS_MED = {}
for med in MEDICAMENTOS:
    alias = {_norm(med["principio_activo"])}
    for nombre in med.get("nombre_comercial", []):
        alias.add(_norm(nombre))
    _ALIAS_MED[_norm(med["principio_activo"])] = sorted(alias)


def _buscar_principio_activo(nombre: str) -> str | None:
    """Dado un nombre (comercial o activo, ES/EN), devuelve el principio activo canónico o None."""
    n = _norm(nombre)
    # Alias ingleses comunes -> forma española canónica
    _en_alias = {
        "ibuprofen": "ibuprofeno", "acetaminophen": "paracetamol",
        "paracetamol": "paracetamol", "warfarin": "warfarina",
        "aspirin": "acido acetilsalicilico",
    }
    n = _en_alias.get(n, n)
    for activo, alias in _ALIAS_MED.items():
        if n == activo or n in alias:
            return activo
    # Coincidencia parcial: el nombre aparece dentro de un alias o viceversa
    for activo, alias in _ALIAS_MED.items():
        for a in alias:
            if len(n) >= 4 and (n in a or a in n):
                return activo
    return None


def _ficha_por_activo(activo: str) -> dict | None:
    """Devuelve la ficha completa del medicamento a partir del principio activo."""
    for med in MEDICAMENTOS:
        if _norm(med["principio_activo"]) == activo:
            return med
    return None


# ---------------------------------------------------------------------------
# TOOL 1: analizar_sintomas
# ---------------------------------------------------------------------------
@tool
def analizar_sintomas(descripcion: str, language: str = "auto") -> str:
    """Analyze free-text symptoms and suggest possible common causes,
    usual over-the-counter medicines, red flags and general advice.
    Analiza síntomas en texto libre y sugiere posibles causas comunes,
    medicamentos de venta libre habituales, señales de alarma y consejo general.

    Args:
        descripcion: Síntomas que describe el usuario / Symptoms described by the user
            (ej: "tengo fiebre y dolor de garganta" / "I have fever and sore throat").
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Causas posibles, medicación OTC habitual, señales de alarma y consejo.
        Possible causes, usual OTC medication, red flags and advice.
    """
    lang = language if language in ("es", "en") else _detect_lang(descripcion)
    desc = _norm(descripcion)
    desc_match = _expand_en_to_es(desc)
    encontrados = []
    for s in SINTOMAS:
        if any(kw in desc_match for kw in s["palabras_clave"]):
            encontrados.append(s)

    if not encontrados:
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

    partes = []
    for s in encontrados[:3]:  # máximo 3 bloques para no saturar
        causas = "; ".join(
            f"{c['nombre']}: {c['descripcion']}" for c in s["condiciones_posibles"]
        )
        if lang == "en":
            partes.append(
                f"· Symptoms related to '{s['id']}':\n"
                f"  Possible common causes: {causas}.\n"
                f"  Usual over-the-counter medication: {', '.join(s['medicamentos_otc'])}.\n"
                f"  ⚠️ See a doctor / go to emergency if: {'; '.join(s['alarmas'])}.\n"
                f"  Advice: {s['consejo_general']}"
            )
        else:
            partes.append(
                f"· Síntomas relacionados con '{s['id']}':\n"
                f"  Posibles causas comunes: {causas}.\n"
                f"  Medicación sin receta habitual: {', '.join(s['medicamentos_otc'])}.\n"
                f"  ⚠️ Acude al médico/urgencias si: {'; '.join(s['alarmas'])}.\n"
                f"  Consejo: {s['consejo_general']}"
            )
    if lang == "en":
        partes.append(
            "Remember: this is general guidance, not a diagnosis. "
            "If you get worse or have doubts, ask your doctor or pharmacist. "
            f"{_disclaimer(lang)}"
        )
    else:
        partes.append(
            "Recuerda: esto es orientación general, no un diagnóstico. "
            "Si empeoras o tienes dudas, consulta a tu médico o farmacéutico. "
            f"{_disclaimer(lang)}"
        )
    return "\n".join(partes)


# ---------------------------------------------------------------------------
# TOOL 2: buscar_medicamento
# ---------------------------------------------------------------------------
@tool
def buscar_medicamento(nombre: str, language: str = "auto") -> str:
    """Look up a medicine card by brand or active ingredient (EN/ES).
    Busca la ficha de un medicamento por nombre comercial o principio activo.
    Devuelve indicaciones, dosis, efectos adversos, advertencias y uso en
    embarazo/lactancia, e indica si requiere receta.
    Returns indications, dosage, side effects, warnings, pregnancy/breastfeeding
    use, and whether it needs a prescription.

    Args:
        nombre: Nombre comercial (ej: "Gelocatil") o principio activo (ej: "paracetamol").
            Brand name (e.g. "Gelocatil") or active ingredient (e.g. "paracetamol").
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Ficha completa del medicamento o sugerencias si no se encuentra.
        Full medicine card or suggestions if not found.
    """
    lang = language if language in ("es", "en") else _detect_lang(nombre)
    activo = _buscar_principio_activo(nombre)
    if activo is None:
        todos = [a for alias in _ALIAS_MED.values() for a in alias]
        sugerencias = get_close_matches(_norm(nombre), todos, n=3, cutoff=0.6)
        if lang == "en":
            extra = f" Did you mean: {', '.join(sugerencias)}?" if sugerencias else ""
            return (
                f"I didn't find '{nombre}' in the local database.{extra} "
                f"Try another name or ask your pharmacist. {_disclaimer(lang)}"
            )
        extra = f" ¿Querías decir: {', '.join(sugerencias)}?" if sugerencias else ""
        return (
            f"No he encontrado '{nombre}' en la base de datos local.{extra} "
            f"Prueba con otro nombre o consulta a tu farmacéutico. {_disclaimer(lang)}"
        )

    med = _ficha_por_activo(activo)
    if lang == "en":
        receta = "Requires a medical prescription" if med["requiere_receta"] else "No prescription needed (OTC)"
        return (
            f"Medicine card for {med['principio_activo'].upper()} "
            f"(brand names: {', '.join(med['nombre_comercial'])})\n"
            f"Category: {med['categoria']}\n"
            f"Prescription: {receta}\n"
            f"Indications: {med['indicaciones']}\n"
            f"Adult dosage: {med['dosis_adulto']}\n"
            f"Pediatric dosage: {med['dosis_pediatrica']}\n"
            f"Side effects: {med['efectos_adversos']}\n"
            f"Warnings: {med['advertencias']}\n"
            f"Pregnancy: {med['embarazo']}\n"
            f"Breastfeeding: {med['lactancia']}\n"
            f"{_disclaimer(lang)}"
        )
    receta = "SÍ requiere receta médica" if med["requiere_receta"] else "NO requiere receta (venta libre)"
    return (
        f"Ficha de {med['principio_activo'].upper()} "
        f"(nombres comerciales: {', '.join(med['nombre_comercial'])})\n"
        f"Categoría: {med['categoria']}\n"
        f"Receta: {receta}\n"
        f"Indicaciones: {med['indicaciones']}\n"
        f"Dosis adulto: {med['dosis_adulto']}\n"
        f"Dosis pediátrica: {med['dosis_pediatrica']}\n"
        f"Efectos adversos: {med['efectos_adversos']}\n"
        f"Advertencias: {med['advertencias']}\n"
        f"Embarazo: {med['embarazo']}\n"
        f"Lactancia: {med['lactancia']}\n"
        f"{_disclaimer(lang)}"
    )


# ---------------------------------------------------------------------------
# TOOL 3: calcular_dosis
# ---------------------------------------------------------------------------
@tool
def calcular_dosis(medicamento: str, peso_kg: float, language: str = "auto") -> str:
    """Calculate the pediatric dose per intake from weight in kg (EN/ES).
    Calcula la dosis pediátrica por toma a partir del peso en kg
    (regla mg/kg) para paracetamol e ibuprofeno.

    Args:
        medicamento: Nombre del medicamento (paracetamol o ibuprofeno).
            Medicine name (paracetamol or ibuprofen).
        peso_kg: Peso del niño en kilogramos. Child weight in kilograms.
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Miligramos por toma, intervalo entre tomas y máximo diario.
        Milligrams per dose, interval and daily maximum.
    """
    lang = language if language in ("es", "en") else _detect_lang(medicamento)
    activo = _buscar_principio_activo(medicamento)
    if peso_kg <= 0 or peso_kg > 150:
        if lang == "en":
            return f"Invalid weight ({peso_kg} kg). Please give the real weight in kilograms. {_disclaimer(lang)}"
        return f"Peso no válido ({peso_kg} kg). Indica el peso real en kilogramos. {_disclaimer(lang)}"
    if activo not in DOSIS_PEDIATRICA:
        if lang == "en":
            return (
                f"I have no weight-based dosing rule for '{medicamento}'. "
                f"Only available for paracetamol and ibuprofen. "
                f"For other drugs, follow the leaflet or ask your pediatrician/pharmacist. {_disclaimer(lang)}"
            )
        return (
            f"No tengo regla de dosis por peso para '{medicamento}'. "
            f"Solo disponible para paracetamol e ibuprofeno. "
            f"Para otros fármacos, sigue el prospecto o consulta al pediatra/farmacéutico. {_disclaimer(lang)}"
        )
    regla = DOSIS_PEDIATRICA[activo]
    mg_toma = round(regla["mg_kg"] * peso_kg)
    max_dia = round(regla["max_mg_kg_dia"] * peso_kg)
    if lang == "en":
        return (
            f"Guidance dose of {activo} for {peso_kg} kg: {mg_toma} mg per dose "
            f"every {regla['intervalo_h']} hours (maximum {max_dia} mg/day). "
            f"Note: {regla['nota']}. "
            f"Always use a dosing syringe, not household spoons. "
            f"If the child is under 2 years old or has a chronic disease, confirm the dose with the pediatrician. {_disclaimer(lang)}"
        )
    return (
        f"Dosis orientativa de {activo} para {peso_kg} kg: {mg_toma} mg por toma "
        f"cada {regla['intervalo_h']} horas (máximo {max_dia} mg/día). "
        f"Nota: {regla['nota']}. "
        f"Usa siempre jeringa dosificadora, no cucharas caseras. "
        f"Si el niño tiene menos de 2 años o enfermedad crónica, confirma la dosis con el pediatra. {_disclaimer(lang)}"
    )


# ---------------------------------------------------------------------------
# TOOL 4: verificar_interaccion
# ---------------------------------------------------------------------------
@tool
def verificar_interaccion(medicamento_1: str, medicamento_2: str, language: str = "auto") -> str:
    """Check whether two medicines (or medicine + alcohol/grapefruit) interact (EN/ES).
    Comprueba si dos medicamentos (o medicamento + alcohol/pomelo) interactúan.
    Devuelve severidad (leve/moderada/grave), explicación y recomendación.
    Returns severity (mild/moderate/severe), explanation and recommendation.

    Args:
        medicamento_1: Primer fármaco (nombre comercial o principio activo).
            First drug (brand or active ingredient).
        medicamento_2: Segundo fármaco, alcohol, zumo de pomelo, etc.
            Second drug, alcohol, grapefruit juice, etc.
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Descripción de la interacción o aviso de que no hay registro local.
        Interaction description or notice that there is no local record.
    """
    lang = language if language in ("es", "en") else _detect_lang(medicamento_1, medicamento_2)
    a1 = _buscar_principio_activo(medicamento_1)
    a2 = _buscar_principio_activo(medicamento_2)
    # Alcohol, pomelo/grapefruit y vitamina K no están en la base de medicamentos: se aceptan tal cual
    # Normalizar alias ingleses para el lookup (manteniendo `lang` para la salida)
    _lookup_alias = {"grapefruit": "zumo de pomelo", "grapefruit juice": "zumo de pomelo",
                     "warfarin": "warfarina", "ibuprofen": "ibuprofeno",
                     "acetaminophen": "paracetamol"}
    a1 = a1 or _lookup_alias.get(_norm(medicamento_1), _norm(medicamento_1))
    a2 = a2 or _lookup_alias.get(_norm(medicamento_2), _norm(medicamento_2))

    for inter in INTERACCIONES:
        par = {_norm(inter["farmaco_a"]), _norm(inter["farmaco_b"])}
        if {a1, a2} == par:
            icono = {"leve": "🟢", "moderada": "🟡", "grave": "🔴"}.get(inter["severidad"], "⚪")
            if lang == "en":
                sev_en = {"leve": "MILD", "moderada": "MODERATE", "grave": "SEVERE"}.get(inter["severidad"], inter["severidad"].upper())
                return (
                    f"{icono} {sev_en} interaction between "
                    f"{inter['farmaco_a']} and {inter['farmaco_b']}:\n"
                    f"{inter['descripcion']}\n"
                    f"Recommendation: {inter['recomendacion']}\n"
                    f"{_disclaimer(lang)}"
                )
            return (
                f"{icono} Interacción {inter['severidad'].upper()} entre "
                f"{inter['farmaco_a']} y {inter['farmaco_b']}:\n"
                f"{inter['descripcion']}\n"
                f"Recomendación: {inter['recomendacion']}\n"
                f"{_disclaimer(lang)}"
            )
    if lang == "en":
        return (
            f"There is no documented interaction between '{medicamento_1}' and "
            f"'{medicamento_2}' in the local database (26 common interactions). "
            f"That does not guarantee none exists: always ask your pharmacist "
            f"before combining medicines, especially with anticoagulants, "
            f"antihypertensives or antidepressants. {_disclaimer(lang)}"
        )
    return (
        f"No hay ninguna interacción documentada entre '{medicamento_1}' y "
        f"'{medicamento_2}' en la base local (26 interacciones frecuentes). "
        f"Eso no garantiza que no exista: consulta siempre al farmacéutico "
        f"antes de combinar medicamentos, sobre todo con anticoagulantes, "
        f"antihipertensivos o antidepresivos. {_disclaimer(lang)}"
    )


# ---------------------------------------------------------------------------
# TOOL 5: consultar_contraindicacion
# ---------------------------------------------------------------------------
@tool
def consultar_contraindicacion(medicamento: str, condicion: str, language: str = "auto") -> str:
    """Check whether a medicine is problematic with a patient condition (EN/ES).
    Comprueba si un medicamento es problemático con una condición del paciente:
    embarazo, lactancia, niños, hipertensión, úlcera/gastritis, riñón, hígado,
    asma, diabetes, anticoagulación, glaucoma o edad avanzada.
    Pregnancy, breastfeeding, children, hypertension, ulcer/gastritis, kidney,
    liver, asthma, diabetes, anticoagulation, glaucoma or advanced age.

    Args:
        medicamento: Nombre comercial o principio activo. Brand or active ingredient.
        condicion: Condición del paciente (ej: "embarazo", "hipertensión", "mi hijo de 5 años").
            Patient condition (e.g. "pregnancy", "hypertension", "my 5-year-old child").
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Advertencias específicas y alternativas habituales más seguras.
        Specific warnings and usually safer alternatives.
    """
    lang = language if language in ("es", "en") else _detect_lang(medicamento, condicion)
    cond_n = _expand_en_to_es(_norm(condicion))
    entrada = None
    for c in CONTRAINDICACIONES:
        if any(kw in cond_n for kw in c["palabras_clave"]):
            entrada = c
            break
    if entrada is None:
        disponibles = ", ".join(c["condicion"] for c in CONTRAINDICACIONES)
        if lang == "en":
            return (
                f"I don't recognise the condition '{condicion}'. "
                f"Available conditions: {disponibles}. {_disclaimer(lang)}"
            )
        return (
            f"No reconozco la condición '{condicion}'. "
            f"Condiciones disponibles: {disponibles}. {_disclaimer(lang)}"
        )

    activo = _buscar_principio_activo(medicamento)
    nombre_mostrar = activo or medicamento
    evitar_n = {_norm(m) for m in entrada["evitar"]}
    precaucion_n = {_norm(m) for m in entrada["precaucion"]}

    if activo and _norm(activo) in evitar_n:
        nivel = "🔴 AVOID" if lang == "en" else "🔴 EVITAR"
    elif activo and _norm(activo) in precaucion_n:
        nivel = "🟡 CAUTION" if lang == "en" else "🟡 PRECAUCIÓN"
    else:
        nivel = "🟢 No recorded restriction for this condition" if lang == "en" else "🟢 Sin restricción registrada para esta condición"

    if lang == "en":
        return (
            f"{nivel}: {nombre_mostrar} with {entrada['condicion']}.\n"
            f"Context: {entrada['descripcion']}.\n"
            f"Medicines to avoid: {', '.join(entrada['evitar']) or '—'}.\n"
            f"Use with caution: {', '.join(entrada['precaucion']) or '—'}.\n"
            f"Usually safer alternatives: {', '.join(entrada['seguros_habituales']) or 'ask your doctor'}.\n"
            f"Note: {entrada['nota']}\n"
            f"{_disclaimer(lang)}"
        )
    return (
        f"{nivel}: {nombre_mostrar} con {entrada['condicion']}.\n"
        f"Contexto: {entrada['descripcion']}.\n"
        f"Medicamentos a evitar: {', '.join(entrada['evitar']) or '—'}.\n"
        f"Usar con precaución: {', '.join(entrada['precaucion']) or '—'}.\n"
        f"Alternativas habituales más seguras: {', '.join(entrada['seguros_habituales']) or 'consultar al médico'}.\n"
        f"Nota: {entrada['nota']}\n"
        f"{_disclaimer(lang)}"
    )


# ---------------------------------------------------------------------------
# TOOL 6: evaluar_urgencia (bilingüe EN/ES)
# ---------------------------------------------------------------------------
_REGLAS_URGENCIA = [
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
def evaluar_urgencia(descripcion: str, language: str = "auto") -> str:
    """Assess urgency level with triage rules (EN/ES).
    Evalúa el nivel de urgencia de unos síntomas con reglas de triaje:
    112/urgencias, médico en 24-48 h, o autocuidado con medicación sin receta.
    112/emergency, doctor in 24-48 h, or self-care with OTC medication.

    Args:
        descripcion: Síntomas que describe el usuario. Symptoms described by the user.
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Nivel de urgencia (🔴 🟡 🟢), motivo y qué hacer.
        Urgency level (🔴 🟡 🟢), reason and what to do.
    """
    lang = language if language in ("es", "en") else _detect_lang(descripcion)
    desc = _norm(descripcion)
    for nivel, claves, accion in _REGLAS_URGENCIA:
        if any(k in desc for k in claves):
            icono = "🔴" if "112" in nivel else "🟡"
            if lang == "en":
                nivel_en = "112/emergency" if "112" in nivel else "doctor within 24-48 h"
                accion_en = (
                    "Red flags detected. Call 112 / go to emergency immediately."
                    if "112" in nivel else
                    "You should see a doctor within 24-48 h (health center or pediatrician)."
                )
                return (
                    f"{icono} Level: {nivel_en}.\nReason: {accion_en}\n"
                    f"Meanwhile: do not drive if you feel dizzy, ask someone nearby for help "
                    f"and bring your medication list.\n{_disclaimer(lang)}"
                )
            return (
                f"{icono} Nivel: {nivel}.\nMotivo: {accion}\n"
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
# TOOL 7: buscar_farmacia
# ---------------------------------------------------------------------------
@tool
def buscar_farmacia(ubicacion: str, language: str = "auto") -> str:
    """Search pharmacies (simulated) by city (EN/ES).
    Busca farmacias (simulado) por ciudad. Si se pide 'guardia' o '24 horas',
    filtra solo las de guardia. If 'on duty' or '24 hours' is requested,
    filters only on-duty ones.

    Args:
        ubicacion: Ciudad o zona (ej: "Madrid", "farmacia de guardia en Barcelona").
            City or area (e.g. "Madrid", "on-duty pharmacy in Barcelona").
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Lista de farmacias con dirección, teléfono y horario.
        List of pharmacies with address, phone and hours.
    """
    lang = language if language in ("es", "en") else _detect_lang(ubicacion)
    ubi = _norm(ubicacion)
    solo_guardia = (
        "guardia" in ubi or "24 horas" in ubi or "24h" in ubi
        or "on duty" in ubi or "on-duty" in ubi or "24 hours" in ubi or "24-hour" in ubi
    )
    candidatas = [
        f for f in FARMACIAS
        if _norm(f["ciudad"]) in ubi or _norm(f["nombre"]) in ubi or _norm(f["direccion"]) in ubi
        or ubi in _norm(f["ciudad"])
    ]
    if solo_guardia:
        candidatas = [f for f in candidatas if f["guardia"]]
    if not candidatas:  # sin filtro de ciudad: mostrar las de guardia
        candidatas = [f for f in FARMACIAS if f["guardia"]] if solo_guardia else FARMACIAS[:4]

    lineas = []
    for f in candidatas[:5]:
        marca = " 🌙 ON DUTY 24h" if (f["guardia"] and lang == "en") else (" 🌙 DE GUARDIA 24h" if f["guardia"] else "")
        lineas.append(
            f"· {f['nombre']}{marca}\n  {f['direccion']} | Tel: {f['telefono']} | {f['horario']}"
        )
    if lang == "en":
        lineas.append(
            "Simulated demo data. For real on-duty pharmacies, "
            f"check your official pharmacists' association or dial 010/012 in your city. {_disclaimer(lang)}"
        )
    else:
        lineas.append(
            "Datos simulados de demostración. Para farmacias de guardia reales, "
            f"consulta a tu colegio oficial de farmacéuticos o el 010/012 de tu ciudad. {_disclaimer(lang)}"
        )
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# TOOL 8: calcular (parser seguro con numexpr)
# ---------------------------------------------------------------------------
@tool
def calcular(expresion: str, language: str = "auto") -> str:
    """Evaluate a math expression safely (EN/ES).
    Evalúa una expresión matemática de forma segura (útil para dosis,
    conversiones mg/ml o cálculos de tomas).

    Args:
        expresion: Expresión matemática (ej: "15*22", "120/5", "(500*3)/7").
            Math expression (e.g. "15*22", "120/5", "(500*3)/7").
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Resultado del cálculo o mensaje de error. Calculation result or error message.
    """
    lang = language if language in ("es", "en") else _detect_lang(expresion)
    import numexpr
    expr = expresion.strip().replace(",", ".").replace("×", "*").replace("÷", "/")
    permitidos = set("0123456789+-*/(). %")
    if not expr or any(c not in permitidos for c in expr):
        if lang == "en":
            return (
                f"Invalid expression: '{expresion}'. "
                f"Use only numbers and operators + - * / ( ) % (e.g. '15*22'). {_disclaimer(lang)}"
            )
        return (
            f"Expresión no válida: '{expresion}'. "
            f"Usa solo números y operadores + - * / ( ) % (ej: '15*22'). {_disclaimer(lang)}"
        )
    try:
        resultado = float(numexpr.evaluate(expr))
        if resultado.is_integer():
            resultado = int(resultado)
        if lang == "en":
            return f"Result of '{expresion}': {resultado}\n{_disclaimer(lang)}"
        return f"Resultado de '{expresion}': {resultado}\n{_disclaimer(lang)}"
    except Exception as e:
        if lang == "en":
            return f"Error evaluating '{expresion}': {e}\n{_disclaimer(lang)}"
        return f"Error evaluando '{expresion}': {e}\n{_disclaimer(lang)}"


# Lista de tools que se entregan al agente
TOOLS = [
    analizar_sintomas,
    buscar_medicamento,
    calcular_dosis,
    verificar_interaccion,
    consultar_contraindicacion,
    evaluar_urgencia,
    buscar_farmacia,
    calcular,
]
