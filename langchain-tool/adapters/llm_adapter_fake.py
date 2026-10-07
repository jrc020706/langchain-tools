"""Fake Gemini adapter for demo mode without API key.

Provides a simulated LLM that returns realistic tool_calls
so the AgentExecutor works in demo mode without a Google API key.
"""

from __future__ import annotations

from typing import Any, List


class FakeGeminiAdapter:
    """Simulated Gemini adapter for demo mode."""
    
    def __init__(self, model_name: str = "gemini-2.5-flash", temperature: float = 0.3):
        self.model_name = model_name
        self.temperature = temperature
    
    def bind_tools(self, tools: List[Any]) -> Any:
        """Bind tools to the fake LLM - returns self for chaining."""
        return self
    
    def invoke(self, inputs: dict) -> Any:
        """Invoke the fake LLM and return a fake AIMessage with tool_calls.
        
        This mimics what a real LLM would return so the AgentExecutor
        can continue its normal flow in demo mode.
        """
        # Extract the user's question
        user_input = inputs.get("input", "") if isinstance(inputs, dict) else str(inputs)
        
        # Simple keyword-based simulation (mimics the _FakeToolBinding logic from agent.py)
        import re
        q = user_input.lower().strip()
        
        # Check for math expression
        if re.fullmatch(r"[\d\s+\-*/().%×÷,]+", q) and re.search(r"\d", q):
            return type('AIMessage', (), {'content': '', 'tool_calls': [{'name': 'calcular', 'args': {'expresion': q}, 'id': 'fake-calcular', 'type': 'tool_call'}]})()
        
        # Check for symptom patterns
        SINTOMAS = [
            {"palabras_clave": ["fiebre", "dolor", "garganta"]},
            {"palabras_clave": ["tos", "respirar"]},
        ]
        
        for s in SINTOMAS:
            if any(kw in q for kw in s["palabras_clave"]):
                return type('AIMessage', (), {
                    'content': f"Soy un orientador de medicamentos (modo demo sin API key). Puedo: analizar síntomas, dar fichas de medicamentos, calcular dosis por peso, revisar interacciones y contraindicaciones, evaluar urgencia y buscar farmacias. ⚠️ Orientación general, no sustituye al médico o farmacéutico.",
                    'tool_calls': []
                })()
        
        # Default generic response
        return type('AIMessage', (), {
            'content': ("Soy un orientador de medicamentos (modo demo sin API key). "
                       "Puedo: analizar síntomas, dar fichas de medicamentos, calcular dosis por peso, "
                       "revisar interacciones y contraindicaciones, evaluar urgencia y buscar farmacias. "
                       "Prueba por ejemplo: 'tengo fiebre y dolor de garganta', "
                       "'qué es el ibuprofeno', 'dosis de paracetamol para 22 kg' o "
                       "'puedo tomar ibuprofeno con warfarina'.⚠️ Orientación general, no sustituye al médico o farmacéutico."),
            'tool_calls': []
        })()


# For compatibility with the adapter code that expects .bind_tools() and .invoke()
# to work with the LlmPort interface
def create_fake_adapter(model_name: str = "gemini-2.5-flash", temperature: float = 0.3) -> FakeGeminiAdapter:
    """Factory function for FakeGeminiAdapter."""
    return FakeGeminiAdapter(model_name=model_name, temperature=temperature)
