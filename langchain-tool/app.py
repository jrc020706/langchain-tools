#!/usr/bin/env python3
"""Web interface for the medication guidance agent using hexagonal architecture.

Run:  python app.py   ->  opens http://localhost:7860

The conversation memory is kept by Gradio (the chat history is re-sent to
the agent on each turn); the 🗑️ "Clear" button resets it.

This module uses hexagonal architecture: the presentation layer (Gradio)
only depends on the ChatUseCase through its ports, without knowing about
Gemini, LangChain tools or internal memory.
"""

from __future__ import annotations

import gradio as gr
from pathlib import Path

# Add the current directory to the path
import os
import sys
sys.path.insert(0, str(Path(__file__).parent))

from domain.use_cases.chat_use_case import ChatUseCase
from ports.llm_port import LlmPort
from ports.tool_port import ToolPort
from ports.memory_port import MemoryPort
from adapters.llm_adapter import create_llm_adapter
from adapters.tool_adapter import create_tool_adapter
from adapters.memory_adapter import create_memory_adapter


def create_use_case() -> ChatUseCase:
    """Factory function to create ChatUseCase with injected dependencies."""
    llm_adapter: LlmPort = create_llm_adapter()
    tool_adapter: ToolPort = create_tool_adapter()
    memory_adapter: MemoryPort = create_memory_adapter()

    return ChatUseCase(
        llm_port=llm_adapter,
        tool_port=tool_adapter,
        memory_port=memory_adapter,
    )


# Create the use case once at app start (per-process singleton)
_chat_use_case: ChatUseCase = create_use_case()


def respond(message: str, history: list, request: gr.Request) -> str:
    """Converts the Gradio history to LangChain messages and runs the use case.

    Bilingual EN/ES: detects the message language and replies in that language.
    Bilingüe EN/ES: detecta el idioma del mensaje y responde en ese idioma.

    Unlike the previous version that called executor.invoke() directly, this
    now uses the hexagonal ChatUseCase, which allows swapping the LLM, tools
    or memory layer without touching this code.

    Args:
        message: Current user message / Mensaje actual del usuario
        history: List of Gradio chat turns

    Returns:
        Agent answer as string / Respuesta del agente como string
    """
    # Gradio supplies a per-browser session hash. Clearing the UI also clears
    # the corresponding in-memory conversation before the next turn.
    session_id = request.session_hash if request and request.session_hash else "web-default"
    if not history:
        _chat_use_case.clear_session(session_id)

    # ChatUseCase auto-detects the language (ES/EN) unless forced.
    result = _chat_use_case.execute(message, session_id=session_id)

    # Extract the answer and format it for Gradio
    answer = result.get("output", "No he podido generar una respuesta. Inténtalo de nuevo. / I couldn't generate an answer. Please try again.")

    # Messages are persisted by the use case (per-session memory is kept there)
    return answer


TITLE = "💊 Orientador de Medicamentos / Medication Guide"
DESCRIPTION = (
    "Pregunta por síntomas, medicamentos, dosis por peso, interacciones, "
    "contraindicaciones o farmacias. Respondo en tu idioma.\n"
    "Ask about symptoms, medicines, weight-based doses, interactions, "
    "contraindications or pharmacies. I reply in your language (ES/EN).\n\n"
    "⚠️ **Orientación general: no es un diagnóstico ni una receta. "
    "Ante señales de alarma (dolor torácico, ahogo, sangrado, desmayo), llama al 112.**\n"
    "⚠️ **General guidance: not a diagnosis or prescription. "
    "If red flags appear (chest pain, breathing difficulty, bleeding, fainting), call 112.**"
)

EXAMPLES = [
    "Tengo fiebre y dolor de garganta, ¿qué puede ser?",
    "I have fever and sore throat, what could it be?",
    "¿Qué es el ibuprofeno y cuándo no debo tomarlo?",
    "What is ibuprofen and when should I avoid it?",
    "¿Qué dosis de paracetamol le doy a un niño de 22 kg?",
    "What paracetamol dose for a 22 kg child?",
    "¿Puedo tomar ibuprofeno si tomo warfarina?",
    "Can I take ibuprofen if I take warfarin?",
    "Estoy embarazada, ¿puedo tomar ibuprofeno?",
    "I am pregnant, can I take ibuprofen?",
    "Me duele mucho el pecho y me cuesta respirar",
    "I have severe chest pain and trouble breathing",
    "Busca una farmacia de guardia en Madrid",
    "Find an on-duty pharmacy in Madrid",
]


def launch_app():
    """Launch the Gradio interface."""
    demo = gr.ChatInterface(
        fn=respond,
        title=TITLE,
        description=DESCRIPTION,
        examples=EXAMPLES,
    )

    # HOST/PORT from the environment:
    # - Local: default 127.0.0.1:7860 (nothing to configure).
    # - Deployment (Render/Docker/WSL): HOST=0.0.0.0 and PORT injected by Render.
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "7860"))

    print("=" * 70)
    print("🚀 Starting web interface...")
    print("=" * 70)
    print()
    print(f"LLM mode: {'real Gemini' if 'Fake' not in type(_chat_use_case._llm_port).__name__ else 'simulated'}")
    print(f"Open at: http://{host}:{port}")
    print("=" * 70)

    demo.launch(server_name=host, server_port=port)


if __name__ == "__main__":
    launch_app()
