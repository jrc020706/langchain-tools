# Conversational Agent with LangChain

A functional Python agent demonstrating conversational AI capabilities using LangChain, with session-based memory and tool usage.

## Project Structure

```
langchain-tool/
├── main.py              # Main script with the conversational agent
├── .env                 # Environment variables (API keys, configuration)
├── requirements.txt     # Python dependencies
└── venv/                # Virtual environment (already created)
```

## Prerequisites

- Python 3.10+ recommended
- OpenAI API key (or compatible endpoint key)
- Virtual environment activated

## Installation

1. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment variables:**

   Edit the `.env` file and add your OpenAI API key:

   ```env
   OPENAI_API_KEY=your_openai_api_key_here
   OPENAI_BASE_URL=https://api.openai.com/v1
   MODEL_NAME=gpt-4o-mini
   ```

   - `OPENAI_API_KEY`: Your OpenAI API key (or compatible endpoint key)
   - `OPENAI_BASE_URL`: Optional, for OpenAI-compatible endpoints (default: `https://api.openai.com/v1`)
   - `MODEL_NAME`: Desired model (e.g., `gpt-4o-mini`, `gpt-4o`, `gpt-4`)

3. **Run the agent:**

   ```bash
   python main.py
   ```

## How It Works

1. **LLM Configuration**: Uses `ChatOpenAI` adaptable for any OpenAI-compatible endpoint via the `OPENAI_BASE_URL` variable.

2. **Custom Tools**:
   - `get_weather`: Simulated weather lookup by city.
   - `calculate`: Evaluates simple mathematical expressions.

3. **Prompt Template**: Includes:
   - `chat_history`: Conversation memory marker.
   - `agent_scratchpad`: Space for the agent's thoughts/actions.
   - System message with behavioral instructions.

4. **Session Memory**: Implemented via `RunnableWithMessageHistory`, which stores and retrieves conversation history per `session_id` using a simple in-memory dictionary (replace with Redis or persistent storage for production).

5. **Two-Turn Demo**: The `main()` function demonstrates:
   - First turn: Agent uses a tool and responds.
   - Second turn: Agent remembers the conversation context from the first turn.

## Example Output

```text
======================================================================
🤖 Conversational Agent with LangChain
======================================================================

🔵 FIRST TURN
----------------------------------------------------------------------
👤 User: What's the weather in Madrid?
🤖 Agent: The weather in Madrid is: Sunny, 28°C

🔵 SECOND TURN (testing memory)
----------------------------------------------------------------------
👤 User: And in Barcelona?
🤖 Agent: The weather in Barcelona is: Cloudy, 24°C

📜 Stored session history:
   User: What's the weather in Madrid?
   Agent: The weather in Madrid is: Sunny, 28°C
   User: And in Barcelona?
   Agent: The weather in Barcelona is: Cloudy, 24°C

✅ Demo completed successfully!
======================================================================
```

## Customization

- **Add more tools**: Decorate new functions with `@tool` and add them to the `tools` list.
- **Change the model**: Modify `MODEL_NAME` in `.env` or the `ChatOpenAI` constructor.
- **Persist memory**: Replace the `session_memory` dictionary with Redis, PostgreSQL, or another storage backend, updating `get_session_history()` accordingly.
- **Adjust the prompt**: Modify the `system_message` or `prompt` template in `main.py`.

## Learn More

- [LangChain Documentation](https://python.langchain.com/)
- [langchain-openai Package](https://python.langchain.com/docs/integrations/chat/openai/)
- [python-dotenv](https://www.npmjs.com/package/dotenv) for environment variable management