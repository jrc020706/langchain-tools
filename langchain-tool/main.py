#!/usr/bin/env python3
"""Interactive terminal chat for the medication guidance agent."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from domain.use_cases.chat_use_case import ChatUseCase
from adapters.llm_adapter import create_llm_adapter
from adapters.tool_adapter import create_tool_adapter
from adapters.memory_adapter import create_memory_adapter


def main() -> None:
    print("💊 Medication Advisor / Orientador de Medicamentos — interactive chat")
    print("Type /help to see commands or /exit to quit.\n")

    llm = create_llm_adapter()
    memory = create_memory_adapter()
    chat = ChatUseCase(
        llm_port=llm,
        tool_port=create_tool_adapter(),
        memory_port=memory,
    )
    mode = "real Gemini" if "Fake" not in type(llm).__name__ else "simulated (demo)"
    print(f"LLM mode: {mode} | Model: {llm.get_model_name()}")
    print("Memory lasts while this process stays open.\n")

    session_id = "terminal"
    try:
        while True:
            try:
                message = input("You: ").strip()
            except EOFError:
                print("\nGoodbye.")
                break

            if not message:
                continue

            command = message.lower()
            if command in {"/exit", "/quit", "/salir"}:
                print("Goodbye.")
                break
            if command in {"/help", "/ayuda"}:
                print("Commands: /help, /history, /clear, /exit")
                print("You can write in Spanish or English.\n")
                continue
            if command in {"/history", "/historial"}:
                history = chat.get_history(session_id).get("messages", [])
                if not history:
                    print("No messages yet.\n")
                else:
                    for item in history:
                        role = "You" if item.get("role") == "user" else "Agent"
                        print(f"{role}: {item.get('content', '')}")
                    print()
                continue
            if command in {"/clear", "/limpiar"}:
                chat.clear_session(session_id)
                print("History cleared.\n")
                continue

            try:
                result = chat.execute(message, session_id)
                print(f"Agent: {result['output']}\n")
            except Exception as error:
                print(f"Could not process the message: {error}\n")
    except KeyboardInterrupt:
        print("\nGoodbye.")


if __name__ == "__main__":
    main()
