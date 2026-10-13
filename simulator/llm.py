"""LLM integration for Alexa+ Simulator using Google Gemini (google-genai).

Provides a tool-calling chat loop: passes MCP tools as function declarations,
lets Gemini select and call them, invokes them on the MCP server, and produces
concise speech-friendly answers.
"""

from datetime import date
import os
from typing import Any, Dict, List, Optional, Tuple

from google import genai
from google.genai import types
from google.genai import errors as genai_errors
import httpx

from mcp_client import execute_mcp_tool_turn, MCPConnectionError


class LLMError(Exception):
    """Spoken-friendly error for LLM quota or configuration issues."""
    pass


SYSTEM_INSTRUCTION = """You are Alexa+, the voice assistant speaking with the user.
You are connected to LifeVault, a personal life-admin assistant that tracks warranties, renewals, subscriptions, bills, and documents.

CRITICAL VOICE INSTRUCTIONS:
1. Keep replies concise, natural, direct, and speech-friendly. Speak as Alexa.
2. Avoid markdown formatting like asterisks, bullet points, code blocks, or raw JSON. Say things naturally so they sound great when read aloud.
3. Today's date is {today_str}.
4. Always call the appropriate LifeVault tool when the user asks about records, deadlines, warranties, bills, or adding new items.
5. Never invent or hallucinate records. If a tool reports that no record or deadline was found, state that clearly.
"""


def _get_gemini_client() -> Tuple[genai.Client, str]:
    """Instantiate the Gemini client from environment variables."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key in ("your_gemini_api_key_here", ""):
        raise LLMError("I couldn't process that because the Gemini API key is missing. Please set GEMINI_API_KEY in the simulator .env file.")

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    return genai.Client(api_key=api_key), model


async def process_voice_turn(
    user_message: str,
    server_url: str,
    bearer_token: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Process a single conversational turn with MCP tool calling.

    Returns:
        {
            "reply": str,
            "tool_calls": [{"name": str, "args": dict, "result": any}]
        }
    """
    # 1. Fetch tool declarations from MCP server
    tools_meta, _ = await execute_mcp_tool_turn(
        server_url=server_url,
        bearer_token=bearer_token,
        tool_declarations_only=True,
    )

    # 2. Convert to google-genai FunctionDeclarations
    fn_declarations = []
    for t in tools_meta:
        fn_declarations.append(types.FunctionDeclaration(
            name=t["name"],
            description=t["description"],
            parameters=t["input_schema"],
        ))

    gemini_tools = [types.Tool(function_declarations=fn_declarations)] if fn_declarations else None

    # 3. Initialize Gemini
    client, model_name = _get_gemini_client()

    today = date.today()
    today_str = f"{today.isoformat()} ({today.strftime('%A')})"
    instructions = SYSTEM_INSTRUCTION.format(today_str=today_str)

    # 4. Cap history at the last 10 turns
    clean_history = (history or [])[-10:]

    # Build chat history contents for Gemini
    contents = []
    for turn in clean_history:
        role = turn.get("role")
        content_text = turn.get("content", "")
        if role == "user":
            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_text(text=content_text)]
            ))
        elif role == "assistant":
            contents.append(types.Content(
                role="model",
                parts=[types.Part.from_text(text=content_text)]
            ))

    # Add current user prompt
    contents.append(types.Content(
        role="user",
        parts=[types.Part.from_text(text=user_message)]
    ))

    executed_tool_records: List[Dict[str, Any]] = []

    try:
        chat = client.chats.create(
            model=model_name,
            config=types.GenerateContentConfig(
                system_instruction=instructions,
                tools=gemini_tools,
                temperature=0.2,
            ),
            history=contents[:-1]
        )

        response = chat.send_message(user_message)

        # Loop while model requests function calls (up to 5 iterations for safety)
        loop_count = 0
        while response.function_calls and loop_count < 5:
            loop_count += 1
            function_response_parts = []

            for fc in response.function_calls:
                call_dict = [{"name": fc.name, "args": fc.args or {}}]
                _, run_results = await execute_mcp_tool_turn(
                    server_url=server_url,
                    bearer_token=bearer_token,
                    tool_declarations_only=False,
                    tool_calls=call_dict,
                )

                tool_result_str = run_results[0]["result"] if run_results else ""
                executed_tool_records.append({
                    "name": fc.name,
                    "args": fc.args or {},
                    "result": tool_result_str,
                })

                function_response_parts.append(
                    types.Part.from_function_response(
                        name=fc.name,
                        response={"result": tool_result_str}
                    )
                )

            # Send function responses back to Gemini
            response = chat.send_message(function_response_parts)

        reply_text = response.text or "I completed that for you."
        return {
            "reply": reply_text.strip(),
            "tool_calls": executed_tool_records,
        }

    except genai_errors.APIError as e:
        status_code = getattr(e, "code", None)
        msg = str(e).lower()
        if status_code == 429 or "quota" in msg or "resource_exhausted" in msg:
            raise LLMError("I'm temporarily over my AI quota limit. Please check your Gemini plan or try again in a moment.")
        if status_code in (400, 401, 403) or "api_key" in msg or "key" in msg:
            raise LLMError("There is a problem with the Gemini API key. Please check your GEMINI_API_KEY setting.")
        raise LLMError("The AI service encountered an error while processing your request.")

    except (httpx.TimeoutException, TimeoutError):
        raise LLMError("The request to the AI service timed out. Please try again.")

    except (httpx.ConnectError, httpx.NetworkError):
        raise LLMError("I couldn't reach the AI service. Please check your internet connection.")

    except MCPConnectionError:
        raise

    except Exception as e:
        raise LLMError("I had trouble generating a response. Please try again.")
