"""Caso de uso: Ejecutar conversación con el agente de medicamentos (bilingüe EN/ES)."""

from __future__ import annotations

from typing import Dict, Any, List, Optional


class ChatUseCase:
    """Case: Execute medication guidance agent conversation (bilingual).

    ReAct loop (max 5 iterations) driven purely through ports:
    - System prompt (bilingual) + history + user message -> LLM bound with tools
    - While the LLM returns `tool_calls`: execute each via ToolPort,
      feed ToolMessages back, re-invoke.
    - Persist only user + final AI message in MemoryPort.
    - Always returns `language` and guarantees the safety disclaimer.

    Dependencies are injected via ports (LLM, tools, memory).
    """

    def __init__(
        self,
        llm_port: Any,  # LLM port interface
        tool_port: Any,  # Tool port interface
        memory_port: Any,  # Memory port interface
        max_iterations: int = 5,
    ):
        self._llm_port = llm_port
        self._tool_port = tool_port
        self._memory_port = memory_port
        self._max_iterations = max_iterations

    def _resolve_language(self, user_input: str, language: Optional[str]) -> str:
        if language in ("es", "en"):
            return language
        try:
            from domain.i18n import detect_language as _det
            return _det(user_input)
        except Exception:
            return "es"

    def _ensure_disclaimer(self, text: str, lang: str) -> str:
        try:
            from domain.i18n import ensure_disclaimer as _ensure
            return _ensure(text, lang)
        except Exception:
            return text

    def _system_prompt(self) -> str:
        try:
            from domain.prompts import BILINGUAL_SYSTEM_PROMPT
            return BILINGUAL_SYSTEM_PROMPT
        except Exception:
            return (
                "You are a bilingual (English/Spanish) medication guidance assistant. "
                "Always reply in the user's language."
            )

    def execute(
        self,
        user_input: str,
        session_id: str = "default",
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute the chat use case with the given user input.

        Args:
            user_input: The user's message (English or Spanish)
            session_id: Session identifier for conversation memory
            language: Optional override: "es" or "en". If None, auto-detected.

        Returns:
            Dict with 'output', 'session_id', 'language', 'tool_calls', 'message_count'
        """
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

        lang = self._resolve_language(user_input, language)

        # Persist user message first (memory holds conversation, not scratchpad)
        self._memory_port.add_user_message(user_input, session_id)
        chat_history = list(self._memory_port.get_messages(session_id)[:-1])

        # If the caller forces a language different from the detected one,
        # add an explicit hint so both the real LLM and the demo fake router
        # answer in the requested language (memory keeps the original text).
        try:
            from domain.i18n import detect_language as _det
            _detected = _det(user_input)
        except Exception:
            _detected = lang
        if language in ("es", "en") and language != _detected:
            hint = "Reply in English" if lang == "en" else "Responde en español"
            effective_input = f"[{hint}] {user_input}"
        else:
            effective_input = user_input

        messages: List[Any] = [SystemMessage(content=self._system_prompt())]
        messages.extend(chat_history)
        messages.append(HumanMessage(content=effective_input))

        bound = self._llm_port.bind_tools(self._tool_port.get_tools())

        all_tool_calls: List[Dict[str, Any]] = []
        final_text = ""
        for _ in range(self._max_iterations):
            result = bound.invoke(messages)
            tool_calls = list(getattr(result, "tool_calls", None) or [])
            content = getattr(result, "content", "") or ""

            if not tool_calls:
                final_text = content if isinstance(content, str) else str(content)
                break

            all_tool_calls.extend(tool_calls)
            # Keep the AIMessage with tool_calls in the scratchpad
            messages.append(result)
            for tc in tool_calls:
                name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                tc_id = tc.get("id", f"call-{len(all_tool_calls)}") if isinstance(tc, dict) else getattr(tc, "id", f"call-{len(all_tool_calls)}")
                if isinstance(args, dict) and "language" not in args:
                    args = {**args, "language": lang}
                try:
                    tool_out = self._tool_port.execute_tool(name, args)
                except Exception as e:
                    tool_out = f"Error executing {name}: {e}"
                messages.append(ToolMessage(content=str(tool_out), tool_call_id=tc_id))
            final_text = ""  # will be set by the next iteration's final answer
        else:
            # max iterations reached without a final answer
            final_text = final_text or "No he podido completar la respuesta. / I couldn't complete the answer."

        # If the loop ended right after tool execution without a final LLM turn,
        # do one last invoke to let the model compose the answer.
        if not final_text:
            result = bound.invoke(messages)
            content = getattr(result, "content", "") or ""
            final_text = content if isinstance(content, str) else str(content)
            extra_calls = list(getattr(result, "tool_calls", None) or [])
            all_tool_calls.extend(extra_calls)

        final_text = self._ensure_disclaimer(final_text, lang)
        self._memory_port.add_ai_message(final_text, session_id)

        # Serialise tool calls for JSON responses (MCP/HTTP)
        serialised_calls = []
        for tc in all_tool_calls:
            if isinstance(tc, dict):
                serialised_calls.append({"name": tc.get("name"), "args": tc.get("args")})
            else:
                serialised_calls.append({"name": getattr(tc, "name", ""), "args": getattr(tc, "args", {})})

        return {
            "output": final_text,
            "session_id": session_id,
            "language": lang,
            "tool_calls": serialised_calls,
            "message_count": self._memory_port.get_message_count(session_id),
        }

    def clear_session(self, session_id: str) -> None:
        """Clear the conversation for one session."""
        self._memory_port.clear_session(session_id)

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
