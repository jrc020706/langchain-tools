"""Fake Gemini adapter for demo mode without API key (bilingual EN/ES)."""

from __future__ import annotations

from typing import Any, List


class FakeGeminiAdapter:
    """Simulated Gemini adapter for demo mode.

    `bind_tools` returns agent.py's `_FakeToolBinding`, which contains the
    full bilingual keyword routing (symptoms, doses, interactions, urgency...).
    This way the hexagonal ChatUseCase ReAct loop executes real tools even
    without a Google API key.
    """

    def __init__(self, model_name: str = "gemini-2.5-flash", temperature: float = 0.3):
        self.model_name = model_name
        self.temperature = temperature

    def bind_tools(self, tools: List[Any]) -> Any:
        """Return a routing fake bound to `tools` (like the real LLM would)."""
        try:
            from agent import _FakeToolBinding
            return _FakeToolBinding(tools)
        except Exception:
            return self

    def invoke(self, inputs: Any) -> Any:
        """Direct fallback (bilingual generic) when called without bind_tools."""
        user_input = ""
        if isinstance(inputs, dict):
            user_input = inputs.get("input", "")
        elif isinstance(inputs, list):
            for m in reversed(inputs):
                if getattr(m, "type", "") == "human" or m.__class__.__name__ == "HumanMessage":
                    user_input = getattr(m, "content", "") or ""
                    break
        else:
            user_input = str(inputs)

        try:
            from domain.i18n import detect_language as _det
            lang = _det(user_input)
        except Exception:
            lang = "es"

        if lang == "en":
            return type('AIMessage', (), {
                'content': ("I'm a medication guidance assistant (demo mode, no API key). "
                           "I can: analyze symptoms, give medicine cards, calculate weight-based doses, "
                           "check interactions and contraindications, assess urgency and find pharmacies. "
                           "⚠️ General guidance, does not replace your doctor or pharmacist."),
                'tool_calls': []
            })()

        return type('AIMessage', (), {
            'content': ("Soy un orientador de medicamentos (modo demo sin API key). "
                       "Puedo: analizar síntomas, dar fichas de medicamentos, calcular dosis por peso, "
                       "revisar interacciones y contraindicaciones, evaluar urgencia y buscar farmacias. "
                       "⚠️ Orientación general, no sustituye al médico o farmacéutico."),
            'tool_calls': []
        })()


def create_fake_adapter(model_name: str = "gemini-2.5-flash", temperature: float = 0.3) -> FakeGeminiAdapter:
    """Factory function for FakeGeminiAdapter."""
    return FakeGeminiAdapter(model_name=model_name, temperature=temperature)
