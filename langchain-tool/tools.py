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
9. consultar_farmacovigilancia - fármaco -> notificaciones de reacciones adversas (API openFDA)  [API internet #1]
10. buscar_farmacia_real     - ubicación -> farmacias reales de OpenStreetMap (Nominatim + Overpass)  [API internet #2]

Las tools 9 y 10 son las dos que consumen APIs de internet de dos servicios
en la nube distintos (openFDA / NIH y OpenStreetMap). Ambas son públicas y
no requieren autenticación ni API key; si la red falla, devuelven un aviso
y las 9 y 10 hacen fallback a los datasets locales cuando aplica.
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
# Configuración compartida de las tools que consumen APIs de internet
# (servicios en la nube distintos, públicos y SIN autenticación)
# ---------------------------------------------------------------------------
# API internet #1: openFDA (NIH / U.S. FAERS) - https://open.fda.gov/apis/
OPENFDA_EVENT_URL = "https://api.fda.gov/drug/event.json"
# API internet #2: OpenStreetMap - Nominatim (geocodificación) + Overpass (datos)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

# User-Agent identificatorio: lo exige la política de uso de Nominatim/Overpass
# (no es un secreto ni una credencial: solo identifica la app).
HTTP_HEADERS = {"User-Agent": "orientador-medicamentos/1.0 (herramienta educativa)"}
HTTP_TIMEOUT = 15  # segundos; si una API no contesta, la tool degrada con aviso

# Presupuesto total de red por invocación de tool: aunque todas las llamadas
# fallen, la tool contesta en menos de este tiempo (nunca cuelga el chat).
PRESUPUESTO_API = 22.0  # segundos
PRESUPUESTO_GEO = 20.0  # segundos para la tool de OpenStreetMap

# Reparto del presupuesto geográfico: Overpass es el mejor dato (radio + horarios)
# pero el más propenso a saturarse, así que acotamos su intento para dejar tiempo
# al fallback de Nominatim dentro del mismo presupuesto.
OVERPASS_MAX = 9.0
NOMINATIM_MAX = 7.0


def _restante(inicio: float, limite: float) -> float:
    """Segundos que quedan del presupuesto (>= 0)."""
    return max(0.0, limite - (time.monotonic() - inicio))


def _get_json(url: str, *, params: dict | None = None, data: dict | None = None,
              timeout: float | None = None) -> dict | list:
    """GET/POST JSON con timeout. Lanza excepción si la API no contesta o falla."""
    t = HTTP_TIMEOUT if timeout is None else max(1.0, timeout)
    if data is not None:
        resp = requests.post(url, data=data, headers=HTTP_HEADERS, timeout=t)
    else:
        resp = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=t)
    resp.raise_for_status()
    return resp.json()


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


# ---------------------------------------------------------------------------
# TOOL 9: consultar_farmacovigilancia  ->  API internet #1 (openFDA, nube NIH)
# ---------------------------------------------------------------------------
# Principio activo en español (base local) -> nombre genérico USAN que usa openFDA
_USAN_POR_ACTIVO = {
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


def _terminos_openfda(activo: str) -> list[str]:
    """Candidatos de búsqueda para openFDA (USAN, marca y nombre local)."""
    n = _norm(activo)
    terminos = []
    usan = _USAN_POR_ACTIVO.get(n)
    if usan:
        terminos.append(usan)
    # Marca local conocida (p. ej. "augmentin" para amoxicilina+clavulánico)
    for med in MEDICAMENTOS:
        if _norm(med["principio_activo"]) == n:
            for marca in med.get("nombre_comercial", []):
                terminos.append(_norm(marca))
            break
    terminos.append(n)
    # Sin duplicados, conservando el orden
    vistos, orden = set(), []
    for t in terminos:
        if t and t not in vistos:
            vistos.add(t)
            orden.append(t)
    return orden


def _buscar_en_openfda(activo: str) -> tuple[dict, str] | None:
    """Consulta openFDA (FAERS) hasta encontrar reportes para el fármaco.

    Prueba varios campos exactos (genérico, medicinalproduct, marca) para
    distintos nombres candidatos, dentro de un presupuesto de tiempo.
    Devuelve (payload, término_acertado) o None.
    """
    campos = (
        "patient.drug.openfda.generic_name",
        "patient.drug.medicinalproduct",
        "patient.drug.openfda.brand_name",
    )
    inicio = time.monotonic()
    for termino in _terminos_openfda(activo)[:3]:
        for campo in campos:
            quedan = _restante(inicio, PRESUPUESTO_API)
            if quedan < 2.0:
                return None
            try:
                payload = _get_json(
                    OPENFDA_EVENT_URL,
                    params={
                        "search": f'{campo}:"{termino.upper()}"',
                        "limit": 100,
                    },
                    timeout=min(HTTP_TIMEOUT, quedan),
                )
            except Exception:
                continue
            if isinstance(payload, dict) and payload.get("results"):
                return payload, termino.upper()
    return None


@tool
def consultar_farmacovigilancia(nombre: str, language: str = "auto") -> str:
    """Look up real-world adverse-event reports for a medicine (API internet #1: openFDA).
    Busca notificaciones de farmacovigilancia (efectos adversos declarados) de un
    medicamento en la API pública openFDA / FAERS (servicio en la nube del NIH,
    sin autenticación). Devuelve nº de casos, reacciones más frecuentes en la
    muestra y desenlace, con la salvedad de que la correlación implica causalidad.
    Returns number of reported cases, most frequent reactions in the sample,
    outcomes and the causality caveat.

    Args:
        nombre: Nombre comercial o principio activo (ej: "paracetamol", "Gelocatil").
            Brand or active ingredient (e.g. "ibuprofen", "Advil").
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Resumen de farmacovigilancia o aviso de que no hay reportes / la API no está
        disponible. Pharmacovigilance summary, or a notice if there are no reports
        or the API is unreachable.
    """
    lang = language if language in ("es", "en") else _detect_lang(nombre)
    activo = _buscar_principio_activo(nombre) or nombre

    try:
        busqueda = _buscar_en_openfda(activo)
    except Exception:
        busqueda = None

    if busqueda is None:
        if lang == "en":
            return (
                f"No adverse-event reports found in openFDA/FAERS for '{nombre}'. "
                f"That does not mean the medicine is safe or unsafe: the database only "
                f"contains what has been voluntarily reported. "
                f"Check the leaflet or ask your pharmacist. {_disclaimer(lang)}"
            )
        return (
            f"No he encontrado notificaciones de farmacovigilancia en openFDA/FAERS para "
            f"'{nombre}'. Eso no significa que el medicamento sea seguro o peligroso: la "
            f"base solo recoge lo que se ha declarado de forma voluntaria. Revisa el "
            f"prospecto o consulta al farmacéutico. {_disclaimer(lang)}"
        )

    payload, termino = busqueda
    resultados = payload.get("results", [])
    total = payload.get("meta", {}).get("results", {}).get("total", len(resultados))

    # Recuento de reacciones y desenlaces en la muestra recuperada
    reacciones: dict[str, int] = {}
    desenlaces: dict[str, int] = {}
    graves = 0
    for r in resultados:
        if str(r.get("serious")) == "1":
            graves += 1
        for reac in r.get("patient", {}).get("reaction", []) or []:
            pt = (reac.get("reactionmeddrapt") or "").strip()
            if pt:
                reacciones[pt] = reacciones.get(pt, 0) + 1
        desenlace = (r.get("patient", {}).get("patientoutcome") or "").strip()
        if desenlace:
            etiqueta = {"DE": "recovered/resolved", "LT": "life-threatening",
                        "HO": "hospitalization", "DS": "death", "OT": "other"}.get(
                desenlace, desenlace)
            desenlaces[etiqueta] = desenlaces.get(etiqueta, 0) + 1

    top_reacciones = sorted(reacciones.items(), key=lambda kv: kv[1], reverse=True)[:5]
    top_desenlaces = sorted(desenlaces.items(), key=lambda kv: kv[1], reverse=True)[:3]
    muestra = len(resultados)

    if lang == "en":
        lineas = [
            f"Pharmacovigilance report for {termino} (source: openFDA / FAERS, API internet).",
            f"· Total adverse-event reports in the database: {total:,}",
            f"· Sample analysed: {muestra} reports ({graves} marked serious).",
            "· Most frequent reactions in the sample:",
        ]
        lineas += [f"    - {r} ({c})" for r, c in top_reacciones] or ["    - not reported"]
        if top_desenlaces:
            lineas.append("· Outcomes in the sample: " + ", ".join(
                f"{k}: {v}" for k, v in top_desenlaces))
        lineas.append(
            "· Reading: these are spontaneous reports, correlation does not imply "
            "causation, and under-reporting is common. Not a substitute for the "
            f"leaflet or your doctor. {_disclaimer(lang)}"
        )
        return "\n".join(lineas)

    lineas = [
        f"Informe de farmacovigilancia de {termino} (fuente: openFDA / FAERS, API internet).",
        f"· Total de notificaciones de reacciones adversas en la base: {total:,}",
        f"· Muestra analizada: {muestra} notificaciones ({graves} marcadas como graves).",
        "· Reacciones más frecuentes en la muestra:",
    ]
    lineas += [f"    - {r} ({c})" for r, c in top_reacciones] or ["    - no informadas"]
    if top_desenlaces:
        lineas.append("· Desenlace en la muestra: " + ", ".join(
            f"{k}: {v}" for k, v in top_desenlaces))
    lineas.append(
        "· Cómo leerlo: son notificaciones espontáneas, la correlación no implica "
        "causalidad y el subregistro es habitual. No sustituye al prospecto ni a "
        f"tu médico. {_disclaimer(lang)}"
    )
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# TOOL 10: buscar_farmacia_real  ->  API internet #2 (OpenStreetMap, nube OSM)
# ---------------------------------------------------------------------------
def _geocodificar(direccion: str, timeout: float | None = None) -> tuple[float, float, str, str | None] | None:
    """(lat, lon, nombre, localidad) de una dirección vía Nominatim (sin API key)."""
    datos = _get_json(
        NOMINATIM_URL,
        params={"q": direccion, "format": "jsonv2", "limit": 1, "addressdetails": 1},
        timeout=timeout,
    )
    if not datos:
        return None
    primero = datos[0]
    addr = primero.get("address", {}) or {}
    localidad = next(
        (addr[k] for k in ("city", "town", "village", "municipality", "suburb", "county")
         if addr.get(k)),
        None,
    )
    return (float(primero["lat"]), float(primero["lon"]),
            primero.get("display_name", direccion), localidad)


def _farmacias_overpass(lat: float, lon: float, radio_m: int = 3000,
                         tiempo_max: float = HTTP_TIMEOUT) -> list[dict]:
    """Farmacias (amenity=pharmacy) cercanas vía Overpass API, con varios mirrors.

    `tiempo_max` limita el tiempo total de la búsqueda (presupuesto de la tool).
    """
    consulta = (
        f'[out:json][timeout:25];(node["amenity"="pharmacy"]'
        f"(around:{radio_m},{lat},{lon}););out center tags 15;"
    )
    inicio = time.monotonic()
    ultimo_error = None
    # Pasada 1: los tres mirrors. Pasada 2: repetimos el principal (suele ser
    # un 504/429 transitorio por saturación) si queda presupuesto.
    orden = list(OVERPASS_URLS) + [OVERPASS_URLS[0]]
    for posicion, endpoint in enumerate(orden):
        quedan = _restante(inicio, tiempo_max)
        if quedan < 2.0:
            break
        try:
            payload = _get_json(endpoint, data={"data": consulta},
                                timeout=min(HTTP_TIMEOUT, quedan))
        except Exception as e:  # mirror caído o saturado -> probamos el siguiente
            ultimo_error = e
            if posicion == len(OVERPASS_URLS) - 1 and _restante(inicio, tiempo_max) > 4.0:
                time.sleep(1.5)
            continue
        elementos = payload.get("elements") if isinstance(payload, dict) else None
        if elementos is None:
            continue
        farmacias = []
        for el in elementos:
            tags = el.get("tags", {}) or {}
            flon = el.get("lon", el.get("center", {}).get("lon"))
            flat = el.get("lat", el.get("center", {}).get("lat"))
            farmacias.append({
                "nombre": tags.get("name", "Farmacia"),
                "direccion": " ".join(filter(None, [
                    tags.get("addr:street", ""),
                    tags.get("addr:housenumber", ""),
                ])).strip() or tags.get("addr:full", ""),
                "ciudad": tags.get("addr:city", ""),
                "telefono": tags.get("phone", tags.get("contact:phone", "")),
                "horario": tags.get("opening_hours", ""),
                "lat": float(flat) if flat is not None else None,
                "lon": float(flon) if flon is not None else None,
            })
        if farmacias:
            return farmacias
    if ultimo_error:
        raise ultimo_error
    return []


def _farmacias_nominatim(direccion: str, localidad: str | None = None,
                         tiempo_max: float = HTTP_TIMEOUT) -> list[dict]:
    """Fallback: busca farmacias directamente en Nominatim (sin Overpass).

    Útil cuando Overpass está saturado o la dirección no se geocodifica bien.
    Solo conserva resultados cuya categoría es amenity=pharmacy.
    """
    consultas = [f"pharmacy in {direccion}", f"farmacia en {direccion}"]
    if localidad and _norm(localidad) != _norm(direccion):
        consultas += [f"pharmacy in {localidad}", f"farmacia en {localidad}"]

    inicio = time.monotonic()
    farmacias, vistas = [], set()
    for consulta in consultas:
        quedan = _restante(inicio, tiempo_max)
        if quedan < 2.0:
            break
        try:
            datos = _get_json(
                NOMINATIM_URL,
                params={"q": consulta, "format": "jsonv2", "limit": 10, "addressdetails": 0},
                timeout=min(HTTP_TIMEOUT, quedan),
            )
        except Exception:
            continue
        for r in datos or []:
            if r.get("category") != "amenity" or r.get("type") != "pharmacy":
                continue
            if r.get("osm_id") in vistas:
                continue
            vistas.add(r.get("osm_id"))
            partes = [p.strip() for p in (r.get("display_name") or "").split(",")]
            farmacias.append({
                "nombre": r.get("name") or (partes[0] if partes else "Farmacia"),
                "direccion": ", ".join(partes[1:3]),
                "ciudad": ", ".join(partes[3:5]),
                "telefono": "",
                "horario": "",
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
            })
        if farmacias:
            break
    return farmacias


def _distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en línea recta (haversine) entre dos coordenadas."""
    radio = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return radio * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@tool
def buscar_farmacia_real(ubicacion: str, language: str = "auto") -> str:
    """Find real pharmacies near a place using OpenStreetMap (API internet #2).
    Busca farmacias REALES cercanas a una ciudad o dirección usando las APIs
    públicas de OpenStreetMap (Nominatim para geocodificar + Overpass para los
    puntos de farmacia). Servicio en la nube distinto de openFDA y sin
    autenticación. Si la red falla, indica cómo usar la tool local simulada.
    Returns up to 5 nearby pharmacies with distance, address, hours and phone.

    Args:
        ubicacion: Ciudad, barrio o dirección (ej: "Madrid", "Gran Vía 20, Madrid").
            City, district or street address (e.g. "Barcelona", "20 Oxford St, London").
        language: Force response language: "es", "en" or "auto" (detect). Default "auto".

    Returns:
        Lista de farmacias reales con distancia y datos, o aviso de indisponibilidad.
        List of real pharmacies with distance and details, or an unavailability notice.
    """
    lang = language if language in ("es", "en") else _detect_lang(ubicacion)
    inicio = time.monotonic()

    # 1) Geocodificar la ubicación (Nominatim) para poder medir distancias.
    #    Se acota a 6 s para no comerse el presupuesto que necesitan Overpass
    #    y el fallback de Nominatim dentro de PRESUPUESTO_GEO.
    try:
        geocodigo = _geocodificar(
            ubicacion,
            timeout=min(6.0, HTTP_TIMEOUT, _restante(inicio, PRESUPUESTO_GEO)))
    except Exception:
        geocodigo = None
    referencia = geocodigo[:2] if geocodigo else None
    localidad = geocodigo[3] if geocodigo else None

    # 2) Farmacias: Overpass alrededor del punto de referencia (datos ricos)
    farmacias: list[dict] = []
    error_overpass: Exception | None = None
    if referencia and _restante(inicio, PRESUPUESTO_GEO) > 3.0:
        try:
            farmacias = _farmacias_overpass(
                *referencia,
                tiempo_max=min(OVERPASS_MAX, _restante(inicio, PRESUPUESTO_GEO)))
        except Exception as e:
            error_overpass = e

    # 3) Fallback: búsqueda directa de farmacias en Nominatim (tiempo reservado
    #    con NOMINATIM_MAX para que Overpass no se lleve todo el presupuesto)
    if not farmacias and _restante(inicio, PRESUPUESTO_GEO) > 3.0:
        try:
            farmacias = _farmacias_nominatim(
                ubicacion, localidad,
                tiempo_max=min(NOMINATIM_MAX, _restante(inicio, PRESUPUESTO_GEO)))
        except Exception:
            farmacias = []

    # 3b) Overpass falla de forma transitoria (504/429 por saturación): si el
    # fallback de Nominatim solo ha devuelto farmacias lejanas, reintentamos
    # Overpass una última vez antes de dar por bueno el resultado.
    if referencia and farmacias and _restante(inicio, PRESUPUESTO_GEO) > 4.0:
        distancias_previas = [
            _distancia_km(referencia[0], referencia[1], f["lat"], f["lon"])
            for f in farmacias if f.get("lat") is not None and f.get("lon") is not None
        ]
        if distancias_previas and min(distancias_previas) > 5.0:
            time.sleep(1.0)
            try:
                reintento = _farmacias_overpass(
                    *referencia,
                    tiempo_max=min(OVERPASS_MAX, _restante(inicio, PRESUPUESTO_GEO)))
            except Exception:
                reintento = []
            if reintento:
                farmacias = reintento

    if not farmacias:
        motivo = type(error_overpass).__name__ if error_overpass else "sin resultados"
        if lang == "en":
            return (
                f"No pharmacies found on OpenStreetMap for '{ubicacion}' ({motivo}). "
                f"Try a bigger town or a more precise address, retry in a moment, or use "
                f"the local simulated search (tool 'buscar_farmacia'). {_disclaimer(lang)}"
            )
        return (
            f"No he encontrado farmacias en OpenStreetMap para '{ubicacion}' ({motivo}). "
            f"Prueba con una ciudad más grande o una dirección más concreta, repite la "
            f"consulta en unos segundos o usa la búsqueda local simulada (tool "
            f"'buscar_farmacia'). {_disclaimer(lang)}"
        )

    if referencia:
        lat, lon = referencia
        for f in farmacias:
            if f.get("lat") is not None and f.get("lon") is not None:
                f["distancia_km"] = round(_distancia_km(lat, lon, f["lat"], f["lon"]), 2)
            else:
                f["distancia_km"] = None
        farmacias.sort(key=lambda f: (f["distancia_km"] is None, f["distancia_km"] or 0))
    else:
        for f in farmacias:
            f["distancia_km"] = None

    # Con referencia geográfica, solo mostramos farmacias realmente cercanas
    # (el fallback de Nominatim puede devolver puntos de otras zonas).
    if referencia:
        cercanas = [f for f in farmacias
                    if f["distancia_km"] is not None and f["distancia_km"] <= 5.0][:5]
        if not cercanas:
            cercanas = farmacias[:5]
    else:
        cercanas = farmacias[:5]

    # Aviso si lo más cercano queda lejos (p. ej. geocodificación imprecisa)
    mas_cerca = next((f["distancia_km"] for f in cercanas
                      if f.get("distancia_km") is not None), None)
    nota_ubicacion = ""
    if mas_cerca is not None and mas_cerca > 5.0:
        if lang == "en":
            nota_ubicacion = (
                f"· The closest match is {mas_cerca} km away: check the spelling of the "
                f"place or add the street/city. "
            )
        else:
            nota_ubicacion = (
                f"· Lo más cercano está a {mas_cerca} km: revisa cómo está escrita la "
                f"ubicación o añade calle y ciudad. "
            )

    lineas = []
    if lang == "en":
        lineas.append(f"Real pharmacies near '{ubicacion}' (OpenStreetMap, API internet):")
        for f in cercanas:
            dist = f"{f['distancia_km']} km" if f["distancia_km"] is not None else "distance n/a"
            extras = " | ".join(x for x in [
                f["direccion"], f["ciudad"], f["telefono"] and f"Tel: {f['telefono']}",
                f["horario"] and f"Hours: {f['horario']}",
            ] if x)
            lineas.append(f"· {f['nombre']} ({dist})" + (f"\n  {extras}" if extras else ""))
        lineas.append(
            nota_ubicacion +
            "Data © OpenStreetMap contributors (ODbL). Opening hours may be "
            "outdated: call before going. " + _disclaimer(lang)
        )
    else:
        lineas.append(f"Farmacias reales cerca de '{ubicacion}' (OpenStreetMap, API internet):")
        for f in cercanas:
            dist = f"{f['distancia_km']} km" if f["distancia_km"] is not None else "distancia n/d"
            extras = " | ".join(x for x in [
                f["direccion"], f["ciudad"], f["telefono"] and f"Tel: {f['telefono']}",
                f["horario"] and f"Horario: {f['horario']}",
            ] if x)
            lineas.append(f"· {f['nombre']} ({dist})" + (f"\n  {extras}" if extras else ""))
        lineas.append(
            nota_ubicacion +
            "Datos © de los colaboradores de OpenStreetMap (ODbL). El horario puede "
            "desactualizarse: llama antes de ir. " + _disclaimer(lang)
        )
    return "\n".join(lineas)


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
    consultar_farmacovigilancia,
    buscar_farmacia_real,
]
