"""LLM Port - Interface for LLM implementations.

Defines the contract that LLM adapters must follow.
The domain depends on this abstraction, not on concrete LLM frameworks.
"""

from __future__ import annotations

from typing import Any, List, Optional, Type

from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage


class LlmPort:
    """Abstract interface for LLM operations.
    
    Concrete adapters (GeminiAdapter, OpenAIAdapter) must implement this.
    The domain layer (use cases) depends only on this interface.
    """
    
    def bind_tools(self, tools: List[Any]) -> Any:
        """Bind tools to the LLM instance.
        
        Args:
            tools: List of tools available to the LLM
            
        Returns:
            LLM instance with tools bound (ready to invoke)
        """
        raise NotImplementedError("Subclasses must implement this method")
    
    def invoke(self, inputs: Dict[str, Any]) -> Any:
        """Invoke the LLM with given inputs.
        
        Args:
            inputs: Dict with 'input' and 'chat_history' keys
            
        Returns:
            LLM response (typically AIMessage or similar)
        """
        raise NotImplementedError("Subclasses must implement this method")
    
    def get_model_name(self) -> str:
        """Get the model name being used."""
        raise NotImplementedError("Subclasses must implement this method")
    
    def get_supported_capabilities(self) -> List[str]:
        """Get list of capabilities supported by this LLM."""
        raise NotImplementedError("Subclasses must implement this method")
