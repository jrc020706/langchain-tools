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
    """Dado un nombre (comercial o activo), devuelve el principio activo canónico o None."""
    n = _norm(nombre)
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
def analizar_sintomas(descripcion: str) -> str:
    """Analiza síntomas descritos en texto libre y sugiere posibles causas comunes,
    medicamentos de venta libre habituales, señales de alarma y consejo general.

    Args:
        descripcion: Síntomas que describe el usuario (ej: "tengo fiebre y dolor de garganta").

    Returns:
        Causas posibles, medicación OTC habitual, señales de alarma y consejo.
    """
    desc = _norm(descripcion)
    encontrados = []
    for s in SINTOMAS:
        if any(kw in desc for kw in s["palabras_clave"]):
            encontrados.append(s)

    if not encontrados:
        return (
            "No he reconocido ningún síntoma concreto en la descripción. "
            "Prueba a describirlo con palabras como: fiebre, dolor de cabeza, tos, "
            "garganta, diarrea, acidez, alergia, insomnio, mareo... "
            "Si hay dolor torácico, dificultad para respirar, sangrado abundante o "
            "pérdida de conciencia, llama al 112."
        )

    partes = []
    for s in encontrados[:3]:  # máximo 3 bloques para no saturar
        causas = "; ".join(
            f"{c['nombre']}: {c['descripcion']}" for c in s["condiciones_posibles"]
        )
        partes.append(
            f"· Síntomas relacionados con '{s['id']}':\n"
            f"  Posibles causas comunes: {causas}.\n"
            f"  Medicación sin receta habitual: {', '.join(s['medicamentos_otc'])}.\n"
            f"  ⚠️ Acude al médico/urgencias si: {'; '.join(s['alarmas'])}.\n"
            f"  Consejo: {s['consejo_general']}"
        )
    partes.append(
        "Recuerda: esto es orientación general, no un diagnóstico. "
        "Si empeoras o tienes dudas, consulta a tu médico o farmacéutico."
    )
    return "\n".join(partes)


# ---------------------------------------------------------------------------
# TOOL 2: buscar_medicamento
# ---------------------------------------------------------------------------
@tool
def buscar_medicamento(nombre: str) -> str:
    """Busca la ficha de un medicamento por nombre comercial o principio activo.
    Devuelve indicaciones, dosis, efectos adversos, advertencias y uso en
    embarazo/lactancia, e indica si requiere receta.

    Args:
        nombre: Nombre comercial (ej: "Gelocatil") o principio activo (ej: "paracetamol").

    Returns:
        Ficha completa del medicamento o sugerencias si no se encuentra.
    """
    activo = _buscar_principio_activo(nombre)
    if activo is None:
        todos = [a for alias in _ALIAS_MED.values() for a in alias]
        sugerencias = get_close_matches(_norm(nombre), todos, n=3, cutoff=0.6)
        extra = f" ¿Querías decir: {', '.join(sugerencias)}?" if sugerencias else ""
        return (
            f"No he encontrado '{nombre}' en la base de datos local.{extra} "
            f"Prueba con otro nombre o consulta a tu farmacéutico."
        )

    med = _ficha_por_activo(activo)
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
        f"Lactancia: {med['lactancia']}"
    )


# ---------------------------------------------------------------------------
# TOOL 3: calcular_dosis
# ---------------------------------------------------------------------------
@tool
def calcular_dosis(medicamento: str, peso_kg: float) -> str:
    """Calcula la dosis pediátrica por toma a partir del peso en kg
    (regla mg/kg) para paracetamol e ibuprofeno.

    Args:
        medicamento: Nombre del medicamento (paracetamol o ibuprofeno).
        peso_kg: Peso del niño en kilogramos.

    Returns:
        Miligramos por toma, intervalo entre tomas y máximo diario.
    """
    activo = _buscar_principio_activo(medicamento)
    if peso_kg <= 0 or peso_kg > 150:
        return f"Peso no válido ({peso_kg} kg). Indica el peso real en kilogramos."
    if activo not in DOSIS_PEDIATRICA:
        return (
            f"No tengo regla de dosis por peso para '{medicamento}'. "
            f"Solo disponible para paracetamol e ibuprofeno. "
            f"Para otros fármacos, sigue el prospecto o consulta al pediatra/farmacéutico."
        )
    regla = DOSIS_PEDIATRICA[activo]
    mg_toma = round(regla["mg_kg"] * peso_kg)
    max_dia = round(regla["max_mg_kg_dia"] * peso_kg)
    return (
        f"Dosis orientativa de {activo} para {peso_kg} kg: {mg_toma} mg por toma "
        f"cada {regla['intervalo_h']} horas (máximo {max_dia} mg/día). "
        f"Nota: {regla['nota']}. "
        f"Usa siempre jeringa dosificadora, no cucharas caseras. "
        f"Si el niño tiene menos de 2 años o enfermedad crónica, confirma la dosis con el pediatra."
    )


# ---------------------------------------------------------------------------
# TOOL 4: verificar_interaccion
# ---------------------------------------------------------------------------
@tool
def verificar_interaccion(medicamento_1: str, medicamento_2: str) -> str:
    """Comprueba si dos medicamentos (o medicamento + alcohol/pomelo) interactúan.
    Devuelve severidad (leve/moderada/grave), explicación y recomendación.

    Args:
        medicamento_1: Primer fármaco (nombre comercial o principio activo).
        medicamento_2: Segundo fármaco, alcohol, zumo de pomelo, etc.

    Returns:
        Descripción de la interacción o aviso de que no hay registro local.
    """
    a1 = _buscar_principio_activo(medicamento_1)
    a2 = _buscar_principio_activo(medicamento_2)
    # Alcohol, pomelo y vitamina K no están en la base de medicamentos: se aceptan tal cual
    a1 = a1 or _norm(medicamento_1)
    a2 = a2 or _norm(medicamento_2)

    for inter in INTERACCIONES:
        par = {_norm(inter["farmaco_a"]), _norm(inter["farmaco_b"])}
        if {a1, a2} == par:
            icono = {"leve": "🟢", "moderada": "🟡", "grave": "🔴"}.get(inter["severidad"], "⚪")
            return (
                f"{icono} Interacción {inter['severidad'].upper()} entre "
                f"{inter['farmaco_a']} y {inter['farmaco_b']}:\n"
                f"{inter['descripcion']}\n"
                f"Recomendación: {inter['recomendacion']}"
            )
    return (
        f"No hay ninguna interacción documentada entre '{medicamento_1}' y "
        f"'{medicamento_2}' en la base local (26 interacciones frecuentes). "
        f"Eso no garantiza que no exista: consulta siempre al farmacéutico "
        f"antes de combinar medicamentos, sobre todo con anticoagulantes, "
        "antihipertensivos o antidepresivos."
    )


# ---------------------------------------------------------------------------
# TOOL 5: consultar_contraindicacion
# ---------------------------------------------------------------------------
@tool
def consultar_contraindicacion(medicamento: str, condicion: str) -> str:
    """Comprueba si un medicamento es problemático con una condición del paciente:
    embarazo, lactancia, niños, hipertensión, úlcera/gastritis, riñón, hígado,
    asma, diabetes, anticoagulación, glaucoma o edad avanzada.

    Args:
        medicamento: Nombre comercial o principio activo.
        condicion: Condición del paciente (ej: "embarazo", "hipertensión", "mi hijo de 5 años").

    Returns:
        Advertencias específicas y alternativas habituales más seguras.
    """
    cond_n = _norm(condicion)
    entrada = None
    for c in CONTRAINDICACIONES:
        if any(kw in cond_n for kw in c["palabras_clave"]):
            entrada = c
            break
    if entrada is None:
        disponibles = ", ".join(c["condicion"] for c in CONTRAINDICACIONES)
        return (
            f"No reconozco la condición '{condicion}'. "
            f"Condiciones disponibles: {disponibles}."
        )

    activo = _buscar_principio_activo(medicamento)
    nombre_mostrar = activo or medicamento
    evitar_n = {_norm(m) for m in entrada["evitar"]}
    precaucion_n = {_norm(m) for m in entrada["precaucion"]}

    if activo and _norm(activo) in evitar_n:
        nivel = "🔴 EVITAR"
    elif activo and _norm(activo) in precaucion_n:
        nivel = "🟡 PRECAUCIÓN"
    else:
        nivel = "🟢 Sin restricción registrada para esta condición"

    return (
        f"{nivel}: {nombre_mostrar} con {entrada['condicion']}.\n"
        f"Contexto: {entrada['descripcion']}.\n"
        f"Medicamentos a evitar: {', '.join(entrada['evitar']) or '—'}.\n"
        f"Usar con precaución: {', '.join(entrada['precaucion']) or '—'}.\n"
        f"Alternativas habituales más seguras: {', '.join(entrada['seguros_habituales']) or 'consultar al médico'}.\n"
        f"Nota: {entrada['nota']}"
    )


# ---------------------------------------------------------------------------
# TOOL 6: evaluar_urgencia
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
      "quemadura extensa", "intento de suicidio", "quiero morir", "sobredosis"],
     "Signos de alarma detectados. Llama al 112 o acude a urgencias de inmediato."),
    ("médico en 24-48 h",
     ["fiebre de mas de 3 dias", "fiebre persistente", "sangre en heces", "sangre en orina",
      "vomitos persistentes", "dolor intenso", "no mejora", "empeora", "infeccion de orina",
      "embarazada", "bebe con fiebre", "supuracion", "pus", "manchas en la piel"],
     "Conviene valoración médica en 24-48 h (centro de salud o pediatra)."),
]


@tool
def evaluar_urgencia(descripcion: str) -> str:
    """Evalúa el nivel de urgencia de unos síntomas con reglas de triaje:
    112/urgencias, médico en 24-48 h, o autocuidado con medicación sin receta.

    Args:
        descripcion: Síntomas que describe el usuario.

    Returns:
        Nivel de urgencia (🔴 🟡 🟢), motivo y qué hacer.
    """
    desc = _norm(descripcion)
    for nivel, claves, accion in _REGLAS_URGENCIA:
        if any(k in desc for k in claves):
            icono = "🔴" if "112" in nivel else "🟡"
            return (
                f"{icono} Nivel: {nivel}.\nMotivo: {accion}\n"
                f"Mientras tanto: no conduzcas si estás mareado, pide ayuda a alguien cercano "
                f"y lleva la lista de medicamentos que tomas."
            )
    return (
        "🟢 Nivel: autocuidado / farmacia.\n"
        "No se detectan señales de alarma en la descripción. Puedes tratarlo con "
        "medidas generales y medicación sin receta, y consultar al farmacéutico. "
        "Si empeora, aparece fiebre alta persistente o surge cualquier señal de alarma "
        "(dolor torácico, dificultad respiratoria, sangrado, confusión), sube el nivel y busca atención."
    )


# ---------------------------------------------------------------------------
# TOOL 7: buscar_farmacia
# ---------------------------------------------------------------------------
@tool
def buscar_farmacia(ubicacion: str) -> str:
    """Busca farmacias (simulado) por ciudad. Si se pide 'guardia' o '24 horas',
    filtra solo las de guardia.

    Args:
        ubicacion: Ciudad o zona (ej: "Madrid", "farmacia de guardia en Barcelona").

    Returns:
        Lista de farmacias con dirección, teléfono y horario.
    """
    ubi = _norm(ubicacion)
    solo_guardia = "guardia" in ubi or "24 horas" in ubi or "24h" in ubi
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
        marca = " 🌙 DE GUARDIA 24h" if f["guardia"] else ""
        lineas.append(
            f"· {f['nombre']}{marca}\n  {f['direccion']} | Tel: {f['telefono']} | {f['horario']}"
        )
    lineas.append(
        "Datos simulados de demostración. Para farmacias de guardia reales, "
        "consulta a tu colegio oficial de farmacéuticos o el 010/012 de tu ciudad."
    )
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# TOOL 8: calcular (parser seguro con numexpr)
# ---------------------------------------------------------------------------
@tool
def calcular(expresion: str) -> str:
    """Evalúa una expresión matemática de forma segura (útil para dosis,
    conversiones mg/ml o cálculos de tomas).

    Args:
        expresion: Expresión matemática (ej: "15*22", "120/5", "(500*3)/7").

    Returns:
        Resultado del cálculo o mensaje de error.
    """
    import numexpr
    expr = expresion.strip().replace(",", ".").replace("×", "*").replace("÷", "/")
    permitidos = set("0123456789+-*/(). %")
    if not expr or any(c not in permitidos for c in expr):
        return (
            f"Expresión no válida: '{expresion}'. "
            f"Usa solo números y operadores + - * / ( ) % (ej: '15*22')."
        )
    try:
        resultado = float(numexpr.evaluate(expr))
        if resultado.is_integer():
            resultado = int(resultado)
        return f"Resultado de '{expresion}': {resultado}"
    except Exception as e:
        return f"Error evaluando '{expresion}': {e}"


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
