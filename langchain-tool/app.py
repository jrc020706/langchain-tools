#!/usr/bin/env python3
"""
Interfaz web del agente de orientación de medicamentos (Gradio).

Ejecutar:  python app.py   ->  abre http://localhost:7860

La memoria de conversación la mantiene Gradio (el historial del chat se
reenvía al agente en cada turno); el botón 🗑️ "Clear" la reinicia.
"""

import gradio as gr
from langchain_core.messages import HumanMessage, AIMessage

from agent import executor

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


def responder(mensaje: str, historial: list) -> str:
    """Convierte el historial de Gradio a mensajes LangChain y llama al agente."""
    chat_history = []
    for turno in historial or []:
        if turno["role"] == "user":
            chat_history.append(HumanMessage(content=turno["content"]))
        elif turno["role"] == "assistant":
            chat_history.append(AIMessage(content=turno["content"]))
    result = executor.invoke({"input": mensaje, "chat_history": chat_history})
    return result.get("output", "No he podido generar una respuesta. Inténtalo de nuevo.")


demo = gr.ChatInterface(
    fn=responder,
    title=TITLE,
    description=DESCRIPTION,
    examples=EXAMPLES,
)

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860)
