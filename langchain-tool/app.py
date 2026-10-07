#!/usr/bin/env python3
"""
Interfaz web del agente de orientación de medicamentos usando arquitectura hexagonal.

Ejecutar:  python app.py   ->  abre http://localhost:7860

La memoria de conversación la mantiene Gradio (el historial del chat se
reenvía al agente en cada turno); el botón 🗑️ "Clear" la reinicia.

Este módulo usa la arquitectura hexagonal: la capa de presentación (Gradio)
solo depende del caso de uso ChatUseCase a través de sus puertos (ports),
sin conocer detalles de Gemini, LangChain tools o memoria interna.
"""

from __future__ import annotations

import gradio as gr
from pathlib import Path

# Agregar el directorio actual al path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from domain.use_cases.chat_use_case import ChatUseCase
from ports.llm_port import LlmPort
from ports.tool_port import ToolPort
from ports.memory_port import MemoryPort
from adapters.llm_adapter import create_llm_adapter
from adapters.tool_adapter import create_tool_adapter
from adapters.memory_adapter import create_memory_adapter


def crear_caso_uso() -> ChatUseCase:
    """Factory function to create ChatUseCase with injected dependencies."""
    llm_adapter: LlmPort = create_llm_adapter()
    tool_adapter: ToolPort = create_tool_adapter()
    memory_adapter: MemoryPort = create_memory_adapter()
    
    return ChatUseCase(
        llm_port=llm_adapter,
        tool_port=tool_adapter,
        memory_port=memory_adapter,
    )


# Crear el caso de uso una vez al iniciar la aplicación (singleton por proceso)
_chat_use_case: ChatUseCase = crear_caso_uso()


def responder(mensaje: str, historial: list) -> str:
    """Convierte el historial de Grado a messages LangChain y ejecuta el caso de uso.
    
    A diferencia de la versión anterior que llamaba directamente a executor.invoke(),
    ahora usa el ChatUseCase hexagonal, lo que permite cambiar de LLM, tools o
    capa de memoria sin tocar este código.
    
    Args:
        mensaje: Mensaje actual del usuario
        historial: Historial de turns del chat de Gradio
        
    Returns:
        Respuesta del agente como string
    """
    # Usar el caso de uso hexagonal en lugar de executor directo
    result = _chat_use_case.execute(mensaje)
    
    # Extraer la respuesta y formatear para Gradio
    respuesta = result.get("output", "No he podido generar una respuesta. Inténtalo de nuevo.")
    
    # Agregar mensajes al historial del caso de uso (para memoria sesión si se reusa)
    # Nota: En Gradio típicamente cada petición es independiente, pero el caso de uso
    # mantiene su propia memoria interna si es necesario
    
    return respuesta


TITLE = "💊 Orientador de Medicamentos"
DESCRIPTION = (
    "Pregunta por síntomas, medicamentos, dosis por peso, interacciones, "
    "contraindicaciones o farmacias. Respondo en tu idioma.\n\n"
    "⚠️ **Orientación general: no es un diagnóstico ni una receta. "
    "Ante señales de alarma (dolor torácico, ahogo, sangrado, desmayo), llama al 112.**"
)

EXAMPLES = [
    "Tengo fiebre y dolor de garganta, ¿qué puede ser?",
    "¿Qué es el ibuprofeno y cuándo no debo tomarlo?",
    "¿Qué dosis de paracetamol le doy a un niño de 22 kg?",
    "¿Puedo tomar ibuprofeno si tomo warfarina?",
    "Estoy embarazada, ¿puedo tomar ibuprofeno?",
    "Me duele mucho el pecho y me cuesta respirar",
    "Busca una farmacia de guardia en Madrid",
]


def launch_app():
    """Lanzar la interfaz Gradio."""
    demo = gr.ChatInterface(
        fn=responder,
        title=TITLE,
        description=DESCRIPTION,
        examples=EXAMPLES,
    )
    
    print("=" * 70)
    print("🚀 Iniciando interfaz web...")
    print("=" * 70)
    print()
    print(f"Modo LLM: {'Gemini real' if 'Fake' not in type(_chat_use_case._llm_port).__name__ else 'simulado'}")
    print(f"Accede en: http://127.0.0.1:7860")
    print("=" * 70)
    
    demo.launch(server_name="127.0.0.1", server_port=7860)


if __name__ == "__main__":
    launch_app()
