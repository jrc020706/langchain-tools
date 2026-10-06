#!/usr/bin/env python3
"""
Conversational Agent with LangChain + Free-Tier API Provider.

This script demonstrates a conversational agent that:
1. Configures ChatOpenAI to connect to a free-tier compatible endpoint
   (e.g., Nemotron 3.5 Lightning, Ollama, TogetherAI, etc.).
2. Uses custom @tool examples (weather lookup and calculation).
3. Employs a ChatPromptTemplate with chat_history and agent_scratchpad markers.
4. Implements session-based conversational memory using RunnableWithMessageHistory.
5. Shows a two-turn example where the agent executes a tool and remembers
   the conversation history in the second turn.

The LLM client is adaptable: it uses a real OpenAI key if provided,
otherwise falls back to a simulated LLM for demonstration purposes.
"""

import os
import re
from dotenv import load_dotenv
from typing import Optional

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langchain_core.runnables.base import Runnable
from langchain_core.chat_history import InMemoryChatMessageHistory


# ---------------------------------------------------------------------------
# 1. Fake LLM class (for demonstration without a real API key)
# ---------------------------------------------------------------------------


class FakeChatOpenAI:
    """Mimics ChatOpenAI interface for demo purposes without a real key."""

    def __init__(self, model_name="gpt-4o-mini", temperature=0.7):
        self.model_name = model_name
        self.temperature = temperature
        self._tools = None

    def bind_tools(self, tools):
        """Bind tools and return a Runnable that simulates tool usage."""
        self._tools = tools
        class ToolBinding(Runnable):
            def __init__(self, llm):
                self.llm = llm

            def invoke(self, input, config=None):
                # Extract user question from chat_history
                q = ""
                chat_history = []
                if hasattr(input, "messages"):
                    messages = input.messages
                    for msg in reversed(messages):
                        if hasattr(msg, "content"):
                            q = msg.content
                            break
                elif isinstance(input, dict):
                    chat_history = input.get("chat_history", [])
                    for msg in reversed(chat_history):
                        if hasattr(msg, "content"):
                            q = msg.content
                            break

                return self.llm._simulate_response_with_tools(q, self.llm._tools)

        return ToolBinding(self)

    def _simulate_response_with_tools(self, user_question, tools):
        """Simulate LLM reasoning and tool usage based on pattern matching."""
        if not user_question:
            user_question = ""
        q_lower = user_question.lower()

        # Weather tool simulation
        if "madrid" in q_lower:
            return f"The weather in Madrid is: Sunny, 28°C"
        if "barcelona" in q_lower:
            return f"The weather in Barcelona is: Cloudy, 24°C"
        if "paris" in q_lower:
            return f"The weather in Paris is: Rainy, 18°C"
        if "nyc" in q_lower or "new york" in q_lower:
            return f"The weather in NYC is: Partly cloudy, 22°C"

        # Calculate tool simulation
        calc_match = re.search(r"[\d+\-*/\s]+", q_lower)
        if calc_match:
            expr = calc_match.group().strip()
            try:
                result = eval(expr, {"__builtins__": {}})
                return f"Result of '{expr}': {result}"
            except:
                pass

        # Default response
        return (
            "I understand you're asking about: '{}'. "
            "I have tools to check weather and calculate math. "
            "Try asking about a city's weather or a math expression!".format(
                q[:50] if q else "your question"
            )
        )


# ---------------------------------------------------------------------------
# 2. Load environment variables
# ---------------------------------------------------------------------------

load_dotenv()

# --- OpenAI / Free-Tier Configuration ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip()  # e.g. https://provider.com/v1
MODEL_NAME = os.getenv("MODEL_NAME", "nemotron-3.5-lightning-free")

# --- Detect if we should use a real LLM or the simulated one ---
# A real LLM is used ONLY when BOTH conditions are met:
#   1. OPENAI_API_KEY is set AND not a placeholder
#   2. OPENAI_BASE_URL is set AND looks like a valid URL
OPEN_AI_PLACEHOLDER = "your_openai_api_key_here"
USE_REAL_LLM = bool(
    OPENAI_API_KEY
    and OPENAI_API_KEY != OPEN_AI_PLACEHOLDER
    and OPENAI_BASE_URL
    and OPENAI_BASE_URL.startswith(("http://", "https://"))
)

# --- Initialize the LLM ---
if USE_REAL_LLM:
    """
    Real LLM: Connects to the free-tier provider specified in OPENAI_BASE_URL.
    The api_key can often be "dummy" or any string, as free-tier providers
    may authenticate via IP, internal tokens, or not at all for free tiers.
    """
    llm = ChatOpenAI(
        api_key=OPENAI_API_KEY,  # "dummy" or real key
        base_url=OPENAI_BASE_URL,  # Free-tier endpoint, must end with /v1
        model_name=MODEL_NAME,
        temperature=0.7,
    )
    print("✅ Using real LLM via free-tier provider:")
    print(f"   Model: {MODEL_NAME}")
    print(f"   Endpoint: {OPENAI_BASE_URL}")
else:
    """
    Simulated LLM: Used for demonstration when no API key or base_url is provided.
    This FakeChatOpenAI mimics ChatOpenAI's interface so the rest of the code works
    without an actual API key. Perfect for local development and testing.
    """
    llm = FakeChatOpenAI(model_name=MODEL_NAME, temperature=0.7)
    print("🛠️ Using simulated LLM (no API key provided).")


# ---------------------------------------------------------------------------
# 3. Custom Tools (example: weather lookup and calculation)
# ---------------------------------------------------------------------------

@tool
def get_weather(city: str) -> str:
    """Get simulated weather for a city.

    Args:
        city: Name of the city.

    Returns:
        Simulated weather description.
    """
    simulated_weather = {
        "Madrid": "Sunny, 28°C",
        "Barcelona": "Cloudy, 24°C",
        "Paris": "Rainy, 18°C",
        "NYC": "Partly cloudy, 22°C",
    }
    weather = simulated_weather.get(city, "Unknown")
    return f"The weather in {city} is: {weather}"


@tool
def calculate(expression: str) -> str:
    """Evaluate a simple mathematical expression.

    Args:
        expression: Mathematical expression (e.g., "2+2", "3*5-10").

    Returns:
        Calculation result or error message.
    """
    try:
        # Note: in production, use a safe library like numexpr
        result = eval(expression, {"__builtins__": {}})
        return f"Result of '{expression}': {result}"
    except Exception as e:
        return f"Error evaluating '{expression}': {str(e)}"


tools = [get_weather, calculate]


# ---------------------------------------------------------------------------
# 4. Prompt template with chat_history and agent_scratchpad
# ---------------------------------------------------------------------------
system_message = SystemMessage(
    content=(
        "You are a helpful assistant with access to tools. "
        "Use the tools when necessary to answer user questions. "
        "Be concise and precise."
    )
)

prompt = ChatPromptTemplate.from_messages([
    system_message,
    MessagesPlaceholder(variable_name="chat_history"),  # Conversation memory
    MessagesPlaceholder(variable_name="agent_scratchpad"),  # Agent thought/action space
])


# ---------------------------------------------------------------------------
# 5. Conversational memory per session
# ---------------------------------------------------------------------------
session_history: dict[str, InMemoryChatMessageHistory] = {}


def get_session_history(session_id: str) -> InMemoryChatMessageHistory:
    """Retrieve the message history for a specific session."""
    if session_id not in session_history:
        session_history[session_id] = InMemoryChatMessageHistory()
    return session_history[session_id]


# ---------------------------------------------------------------------------
# 6. Build the chain with memory support
# ---------------------------------------------------------------------------
if USE_REAL_LLM:
    chain = prompt | llm.bind_tools(tools)
else:
    # For simulated LLM, chain is not used the same way; handling in run_agent()
    chain = None


# ---------------------------------------------------------------------------
# 7. Helper function to run the agent with session memory
# ---------------------------------------------------------------------------
def run_agent(user_input: str, session_id: str = "default_session") -> str:
    """Execute the agent with the given input and session ID, preserving history."""
    history = get_session_history(session_id)

    # Add the user's message to history FIRST so the LLM sees it in context
    history.add_user_message(user_input)

    if USE_REAL_LLM:
        # Real LLM path: use the chain
        response = chain.invoke(
            {
                "chat_history": history.messages,
                "agent_scratchpad": [],  # Will be populated by the agent's tool calls
            }
        )
    else:
        # Simulated LLM path: get last user message and call fake LLM
        last_user_msg = ""
        for msg in reversed(history.messages):
            if isinstance(msg, HumanMessage):
                last_user_msg = msg.content
                break

        # Call the fake LLM's invoke directly
        response = llm.bind_tools(tools).invoke(
            {"chat_history": history.messages, "agent_scratchpad": []}
        )

    # Append the assistant's response to history
    if hasattr(response, "content"):
        assistant_msg = AIMessage(content=response.content)
    else:
        assistant_msg = AIMessage(content=str(response))

    history.add_ai_message(assistant_msg.content)

    return assistant_msg.content


# ---------------------------------------------------------------------------
# 8. Main demonstration
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("🤖 Conversational Agent with LangChain + Free-Tier Provider")
    print("=" * 70)
    print()

    # Current session
    session_id = "user_001"

    # --- FIRST TURN ---
    print("🔵 FIRST TURN")
    print("-" * 70)
    question1 = "What's the weather in Madrid?"
    print(f"👤 User: {question1}")

    answer1 = run_agent(question1, session_id)
    print(f"🤖 Agent: {answer1}")
    print()

    # --- SECOND TURN (demonstrates memory) ---
    print("🔵 SECOND TURN (testing memory)")
    print("-" * 70)
    question2 = "And in Barcelona?"
    print(f"👤 User: {question2}")

    answer2 = run_agent(question2, session_id)
    print(f"🤖 Agent: {answer2}")
    print()

    # Verify history was stored
    history = get_session_history(session_id)
    print("📜 Stored session history:")
    for msg in history.messages:
        if isinstance(msg, HumanMessage):
            print(f"   User: {msg.content}")
        elif isinstance(msg, AIMessage):
            print(f"   Agent: {msg.content}")
    print()

    print("✅ Demo completed successfully!")
    print("=" * 70)