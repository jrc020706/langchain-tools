"""i18n - Central bilingual helpers (English / Spanish).

Single source of truth for:
- detect_language(text) -> 'en' | 'es'
- DISCLAIMER_ES / DISCLAIMER_EN
- get_disclaimer(lang)
- UI strings for demos / servers

Pure Python, no external dependencies (works even if `langdetect`
is not installed). If `langdetect` IS installed it is used as
primary detector with heuristic fallback.
"""

from __future__ import annotations

import re
import unicodedata

SUPPORTED_LANGUAGES = ("es", "en")

DISCLAIMER_ES = "⚠️ Orientación general, no sustituye al médico o farmacéutico."
DISCLAIMER_EN = "⚠️ General guidance, does not replace your doctor or pharmacist."

EMERGENCY_ES = "llama al 112 / acude a urgencias de inmediato"
EMERGENCY_EN = "call 112 / go to emergency immediately"

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_ES_CHARS = set("ñáéíóúü¿¡")
_EN_COMMON = {
    "the", "and", "with", "what", "which", "how", "can", "should",
    "take", "dose", "dosage", "pregnant", "pregnancy", "breastfeeding",
    "child", "weight", "pain", "fever", "cough", "headache", "throat",
    "pharmacy", "interaction", "urgent", "emergency", "chest", "breathe",
    "breathing", "bleeding", "faint", "dizzy", "allergy",
    "hello", "hi", "please", "thanks", "thank",
    # medicines / clinical English markers DISTINCT from Spanish
    # (do NOT include identical words like "paracetamol", "diabetes", "asthma-cognates)
    "ibuprofen", "acetaminophen", "warfarin", "aspirin",
    "loratadine", "cetirizine", "amoxicillin", "omeprazole",
    "pharmacies", "doctor", "guidance",
}
_ES_COMMON = {
    "el", "la", "los", "las", "que", "tengo", "tiene", "dolor",
    "fiebre", "tos", "garganta", "cabeza", "embarazo", "embarazada",
    "lactancia", "peso", "dosis", "farmacia", "guardia", "puedo",
    "tomar", "para", "con", "sin", "hola", "gracias", "favor",
}


def _norm(text: str) -> str:
    text = text.lower().strip()
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def detect_language(text: str) -> str:
    """Detect 'en' (English) or 'es' (Spanish). Defaults to 'es'.

    Strategy:
    1. Try `langdetect` if installed (robust, statistical).
    2. Fallback to heuristic: Spanish-specific chars + common-word scoring.
    """
    if not text or not text.strip():
        return "es"

    low0 = text.lower()
    # Explicit override markers (used by ChatUseCase / run_agent language=...).
    if "reply in english" in low0:
        return "en"
    if "responde en espa" in low0:  # "responde en español"
        return "es"

    # 1) langdetect if available
    try:
        from langdetect import detect as _ld_detect  # type: ignore

        code = _ld_detect(text)
        if code and code.startswith("en"):
            return "en"
        if code and code.startswith("es"):
            return "es"
        # For other codes, fall through to heuristic
    except Exception:
        pass

    low = text.lower()

    # 2a) Strong Spanish signals: ¿ ¡ ñ á é í ó ú ü
    if any(c in low for c in ("¿", "¡", "ñ", "á", "é", "í", "ó", "ú")):
        # Could still be English quoting Spanish, so score words too,
        # but weight Spanish chars heavily.
        es_bonus = 2
    else:
        es_bonus = 0

    words = set(re.findall(r"[a-zñü]+", low, flags=re.IGNORECASE))
    words_norm = {_norm(w) for w in words}

    en_score = len(words_norm & _EN_COMMON)
    es_score = len(words_norm & {_norm(w) for w in _ES_COMMON}) + es_bonus

    # Explicit greetings / markers
    if re.search(r"\b(hello|hi\b|hey|good morning|good evening|how are you)\b", low):
        en_score += 2
    if re.search(r"\b(hola|buenos d[ií]as|buenas tardes|gracias|por favor)\b", low):
        es_score += 2

    if en_score > es_score and en_score > 0:
        return "en"
    return "es"


def get_disclaimer(lang: str) -> str:
    """Return the safety disclaimer in the requested language."""
    return DISCLAIMER_EN if lang == "en" else DISCLAIMER_ES


def ensure_disclaimer(text: str, lang: str) -> str:
    """Append the disclaimer if the text does not already contain one."""
    disclaimer = get_disclaimer(lang)
    # Avoid duplicates: check for the warning emoji + key words
    if "⚠️" in text and (
        "sustituye" in text or "replace" in text or "General guidance" in text
    ):
        return text
    return f"{text}\n{disclaimer}"
