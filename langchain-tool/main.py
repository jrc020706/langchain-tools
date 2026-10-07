#!/usr/bin/env python3
"""
Demo por terminal del agente de orientación de medicamentos usando arquitectura hexagonal.

Ejecutar:  python main.py
También se puede correr la web con: python app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Agregar el directorio actual al path para importar los módulos del proyecto
sys.path.insert(0, str(Path(__file__).parent))

from domain.use_cases.chat_use_case import ChatUseCase
from ports.llm_port import LlmPort
from ports.tool_port import ToolPort
from ports.memory_port import MemoryPort
from adapters.llm_adapter import create_llm_adapter
from adapters.tool_adapter import create_tool_adapter
from adapters.memory_adapter import create_memory_adapter


def crear_caso_uso() -> ChatUseCase:
    """Factory function to create a ChatUseCase with all dependencies injected."""
    # Crear adaptadores concretos (implementaciones de los puertos)
    llm_adapter: LlmPort = create_llm_adapter()
    tool_adapter: ToolPort = create_tool_adapter()
    memory_adapter: MemoryPort = create_memory_adapter()
    
    # Crear el caso de uso (business logic) inyectando las dependencias
    chat_use_case: ChatUseCase = ChatUseCase(
        llm_port=llm_adapter,
        tool_port=tool_adapter,
        memory_port=memory_adapter,
    )
    
    return chat_use_case


def main():
    """Punto de entrada de la demo terminal."""
    print("=" * 70)
    print("💊 Agente de orientación de medicamentos (Arquitectura Hexagonal)")
    print("💊 Medication guidance agent (Hexagonal Architecture)")
    print("🌐 Bilingüe / Bilingual: Español + English (auto-detect)")
    print("=" * 70)
    print()
    
    # Mostrar información del modo LLM
    llm_adapter = create_llm_adapter()
    print(f"Modo LLM: {'Gemini real' if 'Fake' not in type(llm_adapter).__name__ else 'simulado (modo demo)'}")
    print(f"Modelo: {llm_adapter.get_model_name()}")
    print()
    
    # Crear caso de uso
    chat_use_case = crear_caso_uso()
    
    session_id = "user_001"
    preguntas = [
        # Español
        "Tengo fiebre y dolor de garganta, ¿qué puede ser?",
        "¿Qué dosis de paracetamol le doy a un niño de 22 kg?",
        "¿Puedo tomar ibuprofeno si tomo warfarina?",
        # English
        "I have fever and sore throat, what could it be?",
        "What paracetamol dose should I give a 22 kg child?",
        "Can I take ibuprofen if I take warfarin?",
    ]

    for i, pregunta in enumerate(preguntas, 1):
        try:
            from domain.i18n import detect_language as _det
            lang = _det(pregunta)
        except Exception:
            lang = "es"
        print(f"🔵 TURNO {i} [{lang}]")
        print("-" * 70)
        print(f"👤 Usuario: {pregunta}")
        
        # Ejecutar el caso de uso en lugar de run_agent directo
        result = chat_use_case.execute(pregunta, session_id)
        
        print(f"🤖 Agente: {result['output']}")
        print(f"   (Sesión: {result['session_id']}, Idioma/Language: {result.get('language', '?')}, Mensajes: {result['message_count']})")
        print()
    
    # Mostrar historial - los mensajes vienen como dicts con 'content'
    print("📜 Historial de la sesión:")
    history_result = chat_use_case.get_history(session_id)
    messages = history_result.get('messages', [])
    total = history_result.get('total_messages', 0)
    print(f"   Total mensajes: {total}")
    
    for i, msg in enumerate(messages, 1):
        # Los mensajes son dicts con 'content' clave
        contenido = msg.get('content', str(msg))[:80]
        # Determinar rol por posición (user/alternating)
        # En un caso completo tendríamos el role almacenado, pero por simplicidad
        # mostramos el contenido
        print(f"   {i}. {contenido}{'...' if len(contenido) > 80 else ''}")
    
    print()
    print("✅ Demo completada.")
    print("=" * 70)


if __name__ == "__main__":
    main()
