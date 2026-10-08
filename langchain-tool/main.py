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
    print("💊 Orientador de Medicamentos — chat interactivo")
    print("Escribe /ayuda para ver comandos o /salir para terminar.\n")

    llm = create_llm_adapter()
    memory = create_memory_adapter()
    chat = ChatUseCase(
        llm_port=llm,
        tool_port=create_tool_adapter(),
        memory_port=memory,
    )
    modo = "Gemini real" if "Fake" not in type(llm).__name__ else "simulado (demo)"
    print(f"Modo LLM: {modo} | Modelo: {llm.get_model_name()}")
    print("La memoria dura mientras este proceso siga abierto.\n")

    session_id = "terminal"
    try:
        while True:
            try:
                mensaje = input("Tú: ").strip()
            except EOFError:
                print("\nHasta luego.")
                break

            if not mensaje:
                continue

            comando = mensaje.lower()
            if comando in {"/salir", "/exit", "/quit"}:
                print("Hasta luego.")
                break
            if comando in {"/ayuda", "/help"}:
                print("Comandos: /ayuda, /historial, /limpiar, /salir")
                print("También puedes escribir en español o inglés.\n")
                continue
            if comando in {"/historial", "/history"}:
                historial = chat.get_history(session_id).get("messages", [])
                if not historial:
                    print("Todavía no hay mensajes.\n")
                else:
                    for item in historial:
                        rol = "Tú" if item.get("role") == "user" else "Agente"
                        print(f"{rol}: {item.get('content', '')}")
                    print()
                continue
            if comando in {"/limpiar", "/clear"}:
                chat.clear_session(session_id)
                print("Historial borrado.\n")
                continue

            try:
                resultado = chat.execute(mensaje, session_id)
                print(f"Agente: {resultado['output']}\n")
            except Exception as error:
                print(f"No se pudo procesar el mensaje: {error}\n")
    except KeyboardInterrupt:
        print("\nHasta luego.")


if __name__ == "__main__":
    main()
