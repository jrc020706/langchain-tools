"""Memory Adapter - Concrete implementation of MemoryPort.

Wraps LangChain's InMemoryChatMessageHistory and implements
the MemoryPort interface defined in ports/memory_port.py.

This adapter can be swapped for others (Redis, PostgreSQL, etc.)
without affecting the domain layer (ChatUseCase).
"""

from __future__ import annotations

from typing import Any, List, Optional, Dict
from ports.memory_port import MemoryPort
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage


class InMemoryMemoryAdapter(MemoryPort):
    """Concrete adapter using LangChain's InMemoryChatMessageHistory.
    
    Stores conversation history in memory (dict). Good for demo/
    single-server applications. Can be swapped for Redis, DB, etc.
    without changing the domain layer.
    """
    
    def __init__(self):
        """Initialize the in-memory adapter with a session dict."""
        self._session_history: Dict[str, InMemoryChatMessageHistory] = {}
    
    def get_session_history(self, session_id: str) -> InMemoryChatMessageHistory:
        """Get or create session history for the given session.
        
        Args:
            session_id: Unique identifier for the conversation session
            
        Returns:
            InMemoryChatMessageHistory for this session
        """
        if session_id not in self._session_history:
            self._session_history[session_id] = InMemoryChatMessageHistory()
        return self._session_history[session_id]
    
    def add_user_message(self, message: str, session_id: str) -> None:
        """Add a user message to the session history.
        
        Args:
            message: The user's message content
            session_id: Session identifier
        """
        history = self.get_session_history(session_id)
        history.add_user_message(message)
    
    def add_ai_message(self, message: str, session_id: str) -> None:
        """Add an AI/assistant message to the session history.
        
        Args:
            message: The AI's response content
            session_id: Session identifier
        """
        history = self.get_session_history(session_id)
        history.add_ai_message(message)
    
    def get_messages(self, session_id: str) -> List[BaseMessage]:
        """Get all messages for a session in LangChain format.
        
        Args:
            session_id: Session identifier
            
        Returns:
            List of BaseMessage (HumanMessage, AIMessage, ToolMessage)
        """
        history = self.get_session_history(session_id)
        return history.messages
    
    def get_message_count(self, session_id: str) -> int:
        """Get the number of messages in a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Count of messages (user + assistant messages)
        """
        history = self.get_session_history(session_id)
        return len(history.messages)
    
    def clear_session(self, session_id: str) -> None:
        """Clear the conversation history for a session.
        
        Args:
            session_id: Session identifier to clear
        """
        if session_id in self._session_history:
            del self._session_history[session_id]


# Factory function
def create_memory_adapter() -> MemoryPort:
    """Factory to create a MemoryPort instance.
    
    Returns:
        InMemoryMemoryAdapter instance implementing the MemoryPort protocol
    """
    return InMemoryMemoryAdapter()
