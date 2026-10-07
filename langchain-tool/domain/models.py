"""Domain models - pure Python objects with no external dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from domain.i18n import (
    detect_language,
    get_disclaimer,
    ensure_disclaimer,
    DISCLAIMER_ES,
    DISCLAIMER_EN,
    SUPPORTED_LANGUAGES,
)

__all__ = [
    "MedicationGuidance",
    "SymptomAnalysis",
    "UrgencyAssessment",
    "ChatContext",
    "BilingualResponse",
    "detect_language",
    "get_disclaimer",
    "ensure_disclaimer",
    "DISCLAIMER_ES",
    "DISCLAIMER_EN",
    "SUPPORTED_LANGUAGES",
]


@dataclass
class MedicationGuidance:
    """Domain model for medication guidance result."""
    medication: str
    indication: str
    dosage: Optional[str] = None
    contraindications: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommended: bool = True
    disclaimer: str = DISCLAIMER_EN


@dataclass
class SymptomAnalysis:
    """Domain model for symptom analysis result."""
    possible_causes: List[str] = field(default_factory=list)
    over_the_counter: List[str] = field(default_factory=list)
    red_flags: List[str] = field(default_factory=list)
    general_advice: str = ""
    disclaimer: str = DISCLAIMER_EN


@dataclass
class UrgencyAssessment:
    """Domain model for urgency assessment result."""
    level: str  # "low", "medium", "high", "emergency"
    reason: str
    action: str
    disclaimer: str = DISCLAIMER_EN


@dataclass
class ChatContext:
    """Domain model for chat session context."""
    session_id: str
    user_language: str = "es"  # "es" for Spanish, "en" for English
    message_count: int = 0
    topics_discussed: List[str] = field(default_factory=list)

    def get_disclaimer(self) -> str:
        """Get the disclaimer in the user's language."""
        return get_disclaimer(self.user_language)


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
