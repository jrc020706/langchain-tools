"""LLM Adapter - Concrete implementation of LlmPort.

Wraps LangChain's ChatGoogleGenerativeAI (real) or FakeGemini (simulated).
Implements the LlmPort interface defined in ports/llm_port.py.
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

from ports.llm_port import LlmPort
from domain.models import MedicationGuidance, SymptomAnalysis, UrgencyAssessment

load_dotenv()


class GeminiLlmAdapter(LlmPort):
    """Concrete adapter for Google Gemini LLM.
    
    Implements the LlmPort interface. Can operate in two modes:
    - Real mode: Uses actual Google Generative AI with API key
    - Simulated mode: Uses FakeGemini for demo purposes without API key
    
    The domain layer (ChatUseCase) depends on LlmPort abstraction,
    not on this concrete class or LangChain directly.
    """
    
    def __init__(self, model_name: str = "gemini-2.5-flash", temperature: float = 0.3):
        """Initialize the Gemini LLM adapter.
        
        Args:
            model_name: Gemini model name (default: gemini-2.5-flash)
            temperature: Sampling temperature (default: 0.3)
        """
        from dotenv import load_dotenv
        load_dotenv()
        
        self._model_name = model_name
        self._temperature = temperature
        self._llm = self._initialize_llm()
    
    def _initialize_llm(self) -> Any:
        """Initialize the underlying LangChain LLM."""
        from langchain_google_genai import ChatGoogleGenerativeAI
        
        google_key = os.getenv("GOOGLE_API_KEY", "").strip()
        placeholder = "tu_api_key_de_google_aqui"
        
        if google_key and google_key != placeholder:
            # Real mode
            return ChatGoogleGenerativeAI(
                model=self._model_name,
                google_api_key=google_key,
                temperature=self._temperature,
            )
        else:
            # Simulated mode
            from adapters.llm_adapter_fake import FakeGeminiAdapter as _Fake
            return _Fake(model_name=self._model_name, temperature=self._temperature)
    
    def bind_tools(self, tools: List[Any]) -> Any:
        """Bind tools to the LLM instance.
        
        Args:
            tools: List of tools (StructuredTool or similar) to bind
            
        Returns:
            LLM instance with tools available for selection
        """
        return self._llm.bind_tools(tools)
    
    def invoke(self, inputs: Dict[str, Any]) -> Any:
        """Invoke the LLM with given inputs.
        
        Args:
            inputs: Dict with 'input' (user message) and 'chat_history' (conversation history)
            
        Returns:
            LLM response (AIMessage with possible tool_calls)
        """
        return self._llm.invoke(inputs)
    
    def get_model_name(self) -> str:
        """Get the model name being used."""
        return self._model_name
    
    def get_supported_capabilities(self) -> List[str]:
        """Get list of capabilities supported by this LLM."""
        return ["tool_calling", "function_calling", "natural_language", "spanish", "english", "bilingual"]


class FakeGeminiAdapter:
    """Simulated Gemini adapter for demo mode without API key.

    `bind_tools` returns agent.py's `_FakeToolBinding` with full bilingual
    routing, so the hexagonal ChatUseCase ReAct loop executes real tools
    even without a Google API key.
    """

    def __init__(self, model_name: str = "gemini-2.5-flash", temperature: float = 0.3):
        self._model_name = model_name
        self._temperature = temperature

    def bind_tools(self, tools: List[Any]) -> Any:
        """Return a routing fake bound to `tools` (like the real LLM would)."""
        try:
            from agent import _FakeToolBinding
            return _FakeToolBinding(tools)
        except Exception:
            return self

    def invoke(self, inputs: Dict[str, Any]) -> Any:
        """Direct fallback (bilingual generic) when called without bind_tools."""
        from langchain_core.messages import AIMessage

        user_input = inputs.get("input", "") if isinstance(inputs, dict) else str(inputs)
        try:
            from domain.i18n import detect_language as _det
            lang = _det(user_input)
        except Exception:
            lang = "es"

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
    
    def get_model_name(self) -> str:
        """Get the model name being used."""
        return self._model_name


# Factory function to create the appropriate adapter
def create_llm_adapter(model_name: str = "gemini-2.5-flash", 
                       temperature: float = 0.3,
                       use_real: bool = None) -> LlmPort:
    """Factory to create LLM adapter based on environment.
    
    Args:
        model_name: Gemini model name
        temperature: Sampling temperature
        use_real: Force real or simulated mode (None = auto-detect from env)
    
    Returns:
        LlmPort instance (GeminiLlmAdapter or FakeGeminiAdapter)
    """
    import os as _os
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
    
    placeholder = "tu_api_key_de_google_aqui"
    google_key = _os.getenv("GOOGLE_API_KEY", "").strip()
    
    if use_real is None:
        use_real = bool(google_key and google_key != placeholder)
    
    if use_real:
        return GeminiLlmAdapter(model_name=model_name, temperature=temperature)
    else:
        return FakeGeminiAdapter(model_name=model_name, temperature=temperature)
