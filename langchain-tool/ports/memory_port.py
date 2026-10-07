"""Memory Port - Interface for conversation memory.

Defines the contract for managing chat history per session.
The domain layer depends on this abstraction, not on LangChain's
specific memory implementation.
"""

from __future__ import annotations

from typing import Any, List, Optional, Dict, Sequence
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage


class MemoryPort:
    """Abstract interface for conversation memory operations.
    
    Concrete adapters can use LangChain's InMemoryChatMessageHistory,
    Redis, PostgreSQL, or any other storage mechanism.
    The domain layer (use cases) depends only on this interface.
    """
    
    def get_session_history(self, session_id: str) -> Any:
        """Get or create session history for the given session.
        
        Args:
            session_id: Unique identifier for the conversation session
            
        Returns:
            History object compatible with LangChain message format
        """
        raise NotImplementedError("Subclasses must implement this method")
    
    def add_user_message(self, message: str, session_id: str) -> None:
        """Add a user message to the session history.
        
        Args:
            message: The user's message content
            session_id: Session identifier
        """
        raise NotImplementedError("Subclasses must implement this method")
    
    def add_ai_message(self, message: str, session_id: str) -> None:
        """Add an AI/assistant message to the session history.
        
        Args:
            message: The AI's response content
            session_id: Session identifier
        """
        raise NotImplementedError("Subclasses must implement this method")
    
    def get_messages(self, session_id: str) -> List[BaseMessage]:
        """Get all messages for a session in LangChain format.
        
        Args:
            session_id: Session identifier
            
        Returns:
            List of BaseMessage (HumanMessage, AIMessage, ToolMessage)
        """
        raise NotImplementedError("Subclasses must implement this method")
    
    def get_message_count(self, session_id: str) -> int:
        """Get the number of messages in a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Count of messages (user + assistant messages)
        """
        raise NotImplementedError("Subclasses must implement this method")
    
    def clear_session(self, session_id: str) -> None:
        """Clear the conversation history for a session.
        
        Args:
            session_id: Session identifier to clear
        """
        raise NotImplementedError("Subclasses must implement this method")
