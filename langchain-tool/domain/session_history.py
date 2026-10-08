"""Small in-process conversation history used by the demo adapters."""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


class SessionHistory:
    """Store user and assistant messages for one process-local session."""

    def __init__(self) -> None:
        self.messages: list[BaseMessage] = []

    def add_user_message(self, message: str) -> None:
        self.messages.append(HumanMessage(content=message))

    def add_ai_message(self, message: str) -> None:
        self.messages.append(AIMessage(content=message))

    def clear(self) -> None:
        self.messages.clear()
