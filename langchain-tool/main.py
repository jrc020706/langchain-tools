#!/usr/bin/env python3
"""
Demo por terminal del agente de orientación de medicamentos.

Ejecutar:  python main.py
Web (Gradio): python app.py
"""

from langchain_core.messages import HumanMessage, AIMessage
from agent import run_agent, get_session_history, USE_REAL_LLM

if __name__ == "__main__":
    print("=" * 70)
    print("💊 Agente de orientación de medicamentos (LangChain + Gemini)")
    print(f"   Modo: {'Gemini real' if USE_REAL_LLM else 'simulado (sin API key)'}")
    print("=" * 70)
    print()

    session_id = "user_001"
    preguntas = [
        "Tengo fiebre y dolor de garganta, ¿qué puede ser?",
        "¿Qué dosis de paracetamol le doy a un niño de 22 kg?",
        "¿Puedo tomar ibuprofeno si tomo warfarina?",
    ]

    for i, pregunta in enumerate(preguntas, 1):
        print(f"🔵 TURNO {i}")
        print("-" * 70)
        print(f"👤 Usuario: {pregunta}")
        respuesta = run_agent(pregunta, session_id)
        print(f"🤖 Agente: {respuesta}")
        print()

    history = get_session_history(session_id)
    n_user = sum(isinstance(m, HumanMessage) for m in history.messages)
    n_ai = sum(isinstance(m, AIMessage) for m in history.messages)
    print(f"📜 Historial guardado: {n_user} mensajes de usuario + {n_ai} del agente")
    print()
    print("✅ Demo completada. Prueba la interfaz web con: python app.py")
    print("=" * 70)
