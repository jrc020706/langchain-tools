"""Caso de uso: Ejecutar conversación con el agente de medicamentos."""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage


class ChatUseCase:
    """Case: Execute medication guidance agent conversation.
    
    This is the core business logic that:
    - Takes user input
    - Decides which tools to call
    - Executes them
    - Returns a final response
    
    Dependencies are injected via ports (LLM, tools, memory).
    """
    
    def __init__(
        self,
        llm_port: Any,  # LLM port interface
        tool_port: Any,  # Tool port interface
        memory_port: Any,  # Memory port interface
    ):
        self._llm_port = llm_port
        self._tool_port = tool_port
        self._memory_port = memory_port
    
    def execute(self, user_input: str, session_id: str = "default") -> Dict[str, Any]:
        """Execute the chat use case with the given user input.
        
        Args:
            user_input: The user's message
            session_id: Session identifier for conversation memory
            
        Returns:
            Dict with 'output' (AI response) and 'session_id'
        """
        # Get or create session history
        history = self._memory_port.get_session_history(session_id)
        
        # Add user message to history
        self._memory_port.add_user_message(user_input, session_id)
        
        # Convert history to LLM format
        chat_history = self._memory_port.get_messages(session_id)
        
        # Invoke the agent executor
        result = self._llm_port.bind_tools(
            self._tool_port.get_tools()
        ).invoke({
            "input": user_input,
            "chat_history": chat_history,
        })
        
        # Process result and get response
        if hasattr(result, 'content') and result.content:
            response_text = result.content
        elif hasattr(result, 'output'):
            response_text = result.output
        else:
            response_text = str(result)
        
        # Add AI message to history
        self._memory_port.add_ai_message(response_text, session_id)
        
        # Extract tool calls if any for potential re-execution
        tool_calls = getattr(result, 'tool_calls', None) or []
        
        return {
            "output": response_text,
            "session_id": session_id,
            "tool_calls": tool_calls,
            "message_count": self._memory_port.get_message_count(session_id),
        }
    
    def get_history(self, session_id: str) -> Dict[str, Any]:
        """Get conversation history for a session."""
        history = self._memory_port.get_session_history(session_id)
        messages = []
        
        for msg in history.messages:
            if hasattr(msg, 'type'):
                role = "user" if msg.type == "human" else "assistant"
                messages.append({
                    "role": role,
                    "content": msg.content or "",
                })
        
        return {
            "session_id": session_id,
            "messages": messages,
            "total_messages": len(messages),
        }
