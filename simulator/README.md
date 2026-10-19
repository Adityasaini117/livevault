# Alexa+ Voice Simulator & MCP Test Harness

A reusable, voice-first **Alexa+ Streamable HTTP MCP test harness** designed to test and interact with any Model Context Protocol (MCP) server over the standard Streamable HTTP transport.

While built and demonstrated with LifeVault, this harness can be pointed at **any MCP server URL** (local development or remote cloud endpoints like AWS Lambda Function URLs) and includes optional **Bearer token authentication** for secured servers.

It features bidirectional voice interaction (Web Speech API recognition + synthesis), an animated Alexa visual orb, runtime connection controls, and collapsible tool inspection panels for full visibility into tool dispatch and responses.

> **Architecture & Swappable LLM**:
> - **Standalone MCP Client**: Completely decoupled from backend application logic. It communicates strictly via standard Streamable HTTP MCP protocol messages.
> - **Swappable LLM Engine**: Uses Google Gemini (`gemini-2.5-flash` via the `google-genai` SDK) as its default conversational agent and tool-calling orchestrator. The agentic loop in [`llm.py`](llm.py) is cleanly separated, allowing the LLM backend to be swapped for Amazon Bedrock, Anthropic Claude, OpenAI, or local models without modifying the voice UI or MCP transport layer.

---

## Features

- **Reusable Test Harness**: Point to **any MCP server URL** (e.g., `http://localhost:8000/mcp`, an AWS Lambda Function URL, or a remote container) with an optional per-request **Bearer Token**.
- **Voice In & Voice Out**: Browser Web Speech API (`SpeechRecognition`) for hands-free voice input and `SpeechSynthesis` for natural spoken Alexa responses.
- **Text Fallback**: Full keyboard text input support with fallback notices if a browser lacks speech APIs.
- **Streamable HTTP MCP Client**: Uses the official Python MCP SDK (`mcp.client.streamable_http`) to discover tools dynamically and execute them with isolated error handling.
- **Swappable Function Calling Loop**: Integrates out-of-the-box with Google Gemini for agentic tool use, but designed so alternative LLM providers can easily replace it.
- **Zero Token Logging**: MCP server URLs and Bearer tokens are entered per-session in the UI settings drawer and sent per-request. Tokens are never hardcoded and never logged.
- **Friendly Voice Error Handling**: Replaces raw stack traces with natural voice notifications for unreachable servers, 401 unauthorized errors, and Gemini quota or key issues.
- **Collapsible Tool Tray**: View tool names, input arguments, and raw server output for complete execution visibility.
- **Quick Demo Chips**: One-click demo buttons to run test scenarios.

---

## Prerequisites

- Python 3.10+
- A Google Gemini API key (from [Google AI Studio](https://aistudio.google.com/))
- A running MCP server (e.g., LifeVault at `http://localhost:8000/mcp`)

---

## Setup & Installation

1. Navigate to the simulator directory:
   ```powershell
   cd simulator
   ```

2. (Optional) Create and activate an isolated virtual environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install required dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

4. Configure environment variables:
   Copy `.env.example` to `.env` and fill in your Gemini API key:
   ```powershell
   Copy-Item .env.example .env
   ```
   Edit `.env`:
   ```env
   GEMINI_API_KEY=your_actual_gemini_api_key_here
   GEMINI_MODEL=gemini-2.5-flash
   SIMULATOR_PORT=8080
   ```

---

## Running the Simulator

Start the FastAPI simulator server:

```powershell
python app.py
```

Open your browser to:
[http://localhost:8080](http://localhost:8080)

---

## Using the Simulator

1. **Configure MCP Connection**:
   - Click the gear icon in the top right to open settings.
   - Set **MCP Server URL** (default is `http://localhost:8000/mcp`).
   - If your server has bearer token access enabled (`LIFEVAULT_API_TOKEN`), paste the token into the **Bearer Token** field.
   - Click **Apply Settings**.

2. **Interact by Voice or Text**:
   - Click the **Microphone** button and speak, or type into the input field and hit Enter.
   - Alexa+ will execute the necessary tools on your MCP server, display the tool calls in a collapsible panel, and speak the answer aloud.

3. **Sample Phrases**:
   - *"what's due this week?"*
   - *"is my laptop still under warranty?"*
   - *"I bought AirPods for 249 dollars last Tuesday, one year warranty"*

---

## License

MIT License. See [LICENSE](LICENSE) for details.
