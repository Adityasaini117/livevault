"""Alexa+ Simulator Web Application Backend.

Serves single-page voice UI and provides POST /chat endpoint.
All MCP connections are executed per-request using user-configured settings.
No sensitive server tokens are ever hardcoded or logged.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from llm import process_voice_turn, LLMError
from mcp_client import MCPConnectionError

# Load simulator .env if present; fallback to workspace root .env
sim_dir = Path(__file__).resolve().parent
local_env = sim_dir / ".env"
root_env = sim_dir.parent / ".env"

if local_env.exists():
    load_dotenv(dotenv_path=local_env)
elif root_env.exists():
    load_dotenv(dotenv_path=root_env)

app = FastAPI(title="Alexa+ Simulator for LifeVault", version="1.0.0")

# Mount static folder
static_dir = sim_dir / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User voice or text prompt")
    server_url: str = Field(default="http://localhost:8000/mcp", description="Target MCP server URL")
    bearer_token: Optional[str] = Field(default=None, description="Optional Bearer token for MCP")
    history: Optional[List[Dict[str, str]]] = Field(default_factory=list, description="Recent conversation turns")


class ChatResponse(BaseModel):
    reply: str
    tool_calls: List[Dict[str, Any]]


@app.get("/")
async def get_index():
    """Serve the single-page chat UI."""
    return FileResponse(static_dir / "index.html")


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(payload: ChatRequest):
    """Processes user voice turn against MCP tools and Gemini LLM.

    Ensures server URL and token come strictly from per-request payload,
    never hardcoded and never logged.
    """
    clean_message = payload.message.strip()
    clean_url = payload.server_url.strip()

    try:
        result = await process_voice_turn(
            user_message=clean_message,
            server_url=clean_url,
            bearer_token=payload.bearer_token,
            history=payload.history,
        )
        return ChatResponse(
            reply=result["reply"],
            tool_calls=result["tool_calls"],
        )
    except MCPConnectionError as e:
        return ChatResponse(
            reply=str(e),
            tool_calls=[],
        )
    except LLMError as e:
        return ChatResponse(
            reply=str(e),
            tool_calls=[],
        )
    except Exception as e:
        return ChatResponse(
            reply="I encountered an unexpected issue while processing your request. Please try again.",
            tool_calls=[],
        )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SIMULATOR_PORT", "8080"))
    uvicorn.run("app:app", host="127.0.0.1", port=port, reload=True)
