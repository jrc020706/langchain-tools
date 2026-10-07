"""Domain models - pure Python objects with no external dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MedicationGuidance:
    """Domain model for medication guidance result."""
    medication: str
    indication: str
    dosage: Optional[str] = None
    contraindications: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommended: bool = True
    disclaimer: str = (
        "⚠️ General guidance, does not replace medical or pharmaceutical advice."
    )


@dataclass 
class SymptomAnalysis:
    """Domain model for symptom analysis result."""
    possible_causes: List[str] = field(default_factory=list)
    over_the_counter: List[str] = field(default_factory=list)
    red_flags: List[str] = field(default_factory=list)
    general_advice: str = ""
    disclaimer: str = (
        "⚠️ General guidance, does not replace medical or pharmaceutical advice."
    )


@dataclass 
class UrgencyAssessment:
    """Domain model for urgency assessment result."""
    level: str  # "low", "medium", "high", "emergency"
    reason: str
    action: str
    disclaimer: str = (
        "⚠️ General guidance, does not replace medical or pharmaceutical advice."
    )


@dataclass
class ChatContext:
    """Domain model for chat session context."""
    session_id: str
    user_language: str = "es"  # "es" for Spanish, "en" for English
    message_count: int = 0
    topics_discussed: List[str] = field(default_factory=list)
    
    def get_disclaimer(self) -> str:
        """Get the disclaimer in the user's language."""
        if self.user_language == "en":
            return "⚠️ General guidance, does not replace medical or pharmaceutical advice."
        return "⚠️ Orientación general, no sustituye al médico o farmacéutico."
    
    def get_warning_emoji(self) -> str:
        """Get the warning emoji based on language."""
        return "🟡" if self.user_language == "en" else "🔴"


# Nuevo modelo para respuestas bilingües
@dataclass
class BilingualResponse:
    """Model for bilingual responses."""
    spanish: str
    english: str
    detected_language: str
    
    def get_response(self) -> str:
        """Get the response in the detected language."""
        if self.detected_language == "en":
            return self.english
        return self.spanish


def detect_language(text: str) -> str:
    """Detect if text is primarily English or Spanish.
    
    Simple heuristic: count English vs Spanish words/patterns.
    Returns 'en' for English, 'es' for Spanish.
    """
    if not text:
        return "es"  # Default to Spanish
    
    import re
    
    # Count English-like patterns (common English words, uppercase patterns, etc.)
    english_indicators = len(re.findall(r'\b(the|and|or|but|in|on|for|with|you|we|they|this|that)\b', text.lower()))
    
    # Count Spanish-like patterns (common Spanish patterns)
    spanish_indicators = len(re.findall(r'\b(el|la|los|las|un|una|y|o|pero|con|para|por|por|sin|sobre|entre)\b', text.lower()))
    
    # Also check for explicit English/Spanish markers
    english_markers = len(re.findall(r'\bHello|Hi|Hey|Good|Morning|Evening|How are you\b', text, re.IGNORECASE))
    spanish_markers = len(re.findall(r'\bHola|Buenos|Días|Tarda|Sí|No|Gracias|Por|favor\b', text, re.IGNORECASE))
    
    # Simple decision: if more English markers, use English; otherwise Spanish
    english_score = english_indicators + english_markers
    spanish_score = spanish_indicators + spanish_markers
    
    if english_score > spanish_score and english_score > 0:
        return "en"
    return "es"
