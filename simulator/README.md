# Alexa+ LifeVault Simulator

A clean, voice-first Alexa+ simulator web app designed to interact with Model Context Protocol (MCP) servers (such as LifeVault) over Streamable HTTP.

It features voice recognition, speech synthesis, an animated Alexa visual orb, configurable connection settings, and collapsible tool inspection panels.

> **Note**: This application is completely standalone and imports nothing from the backend `/server`. It connects purely through standard Streamable HTTP MCP and Google Gemini APIs.

---

## Features

- **Voice In & Voice Out**: Browser Web Speech API (`SpeechRecognition`) for hands-free voice input and `SpeechSynthesis` for natural spoken Alexa responses.
- **Text Fallback**: Full keyboard text input support with fallback notices if a browser lacks speech APIs.
- **Streamable HTTP MCP Client**: Uses the official Python MCP SDK (`mcp.client.streamable_http`) to discover tools and invoke them dynamically.
- **Function Calling Loop**: Integrates with Google Gemini via the official `google-genai` SDK, giving the model real-time access to MCP tools.
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
