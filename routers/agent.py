"""
routers/agent.py — ELN Intelligence Agent
FastAPI router for POST /api/ai/chat
Agent: asst_iujfiErrYF9CfqgyB6BqY4Xn (gpt-5-4, Foundry Assistants API)
"""

import os
import json
import asyncio
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

# ── Config ────────────────────────────────────────────────────────────────────
FOUNDRY_ENDPOINT  = os.environ["FOUNDRY_ENDPOINT"]          # https://aifoundry-eln-covvalent.services.ai.azure.com
FOUNDRY_API_VER   = os.environ.get("FOUNDRY_API_VERSION", "2025-05-15-preview")
AGENT_ID          = os.environ["AGENT_ID"]                  # asst_iujfiErrYF9CfqgyB6BqY4Xn
AGENT_MODEL       = os.environ.get("AGENT_MODEL", "gpt-5-4")
AGENT_FALLBACK_MODEL = os.environ.get("AGENT_FALLBACK_MODEL", "gpt-4o")

# Timeouts (seconds)
CONNECT_TIMEOUT   = 10
TOOL_CALL_TIMEOUT = 60   # per individual tool call (fetch/search/literature)
RUN_POLL_TIMEOUT  = 240  # total time to wait for a run to complete
POLL_INTERVAL     = 1.5  # seconds between status polls

# Tool output size limit — Foundry rejects tool outputs over ~32KB total.
# Large fetch payloads (50-experiment project lists) can exceed this.
# Truncate each tool output to this character limit before submitting.
TOOL_OUTPUT_MAX_CHARS = 3000

# Internal API base for tool calls — separate from Foundry endpoint
API_BASE = os.environ.get(
    "INTERNAL_API_BASE",
    "https://eln-api-covvalent-asfhf0abbvh2bphd.southindia-01.azurewebsites.net"
)

# ── Tool definitions (register with Foundry Assistant or pass at run time) ────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "fetch_project_reports",
            "description": (
                "Retrieve previously generated analysis reports for a project. "
                "Returns report metadata and a concise summary of each report's findings. "
                "Call this FIRST whenever answering any project-level question so that "
                "prior analysis is used as context rather than repeating retrieval "
                "already covered in an existing report."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_code": {
                        "type": "string",
                        "description": "The project code, e.g. P112P00 or P100P02."
                    }
                },
                "required": ["project_code"]
            }
        }
    },
]

# ── Schema ────────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    user_email: Optional[str] = None

class ChatResponse(BaseModel):
    answer: str
    thread_id: str
    tool_calls: list = []
    model_used: str = ""

# ── Auth helper ───────────────────────────────────────────────────────────────
async def get_foundry_token() -> str:
    """Get AAD token for AI Foundry using managed identity."""
    from azure.identity.aio import ManagedIdentityCredential
    credential = ManagedIdentityCredential()
    token = await credential.get_token("https://ai.azure.com/.default")
    await credential.close()
    return token.token

# ── Tool output truncation ────────────────────────────────────────────────────
def truncate_tool_output(raw: str, tool_name: str) -> str:
    """
    Truncate tool output to TOOL_OUTPUT_MAX_CHARS to prevent Foundry
    context overflow. For fetch_experiment project lists (50+ experiments),
    the full payload can exceed 30KB and cause gpt-5-4 run failures.
    Appends a note so the agent knows data was truncated.
    """
    if len(raw) <= TOOL_OUTPUT_MAX_CHARS:
        return raw
    truncated = raw[:TOOL_OUTPUT_MAX_CHARS]
    # Try to close the JSON cleanly at the last complete object boundary
    last_brace = truncated.rfind("},")
    if last_brace > TOOL_OUTPUT_MAX_CHARS * 0.5:
        truncated = truncated[:last_brace + 1]
    return truncated + f'\n[TRUNCATED: full {tool_name} response exceeded {TOOL_OUTPUT_MAX_CHARS} chars. Use specific experiment_id or exp_number_full to fetch individual records.]'

# ── Tool dispatcher ───────────────────────────────────────────────────────────
async def dispatch_tool(tool_name: str, tool_args: dict, tool_client: httpx.AsyncClient, user_email: str = "unknown") -> str:
    """Execute a tool call and return the result as a string."""
    try:
        if tool_name == "fetch_experiment":
            response = await tool_client.post(
                f"{API_BASE}/api/ai/fetch",
                json=tool_args,
                timeout=TOOL_CALL_TIMEOUT
            )
            response.raise_for_status()
            raw = json.dumps(response.json())
            return truncate_tool_output(raw, "fetch_experiment")

        elif tool_name == "search_experiments":
            params = {"q": tool_args.get("q", ""), "top": tool_args.get("top", 5)}
            if "chunk_type" in tool_args:
                params["chunk_type"] = tool_args["chunk_type"]
            response = await tool_client.get(
                f"{API_BASE}/api/search",
                params=params,
                timeout=TOOL_CALL_TIMEOUT
            )
            response.raise_for_status()
            raw = json.dumps(response.json())
            return truncate_tool_output(raw, "search_experiments")

        elif tool_name == "search_literature":
            params = {"q": tool_args.get("q", "")}
            response = await tool_client.get(
                f"{API_BASE}/api/ai/literature",
                params=params,
                timeout=TOOL_CALL_TIMEOUT
            )
            response.raise_for_status()
            raw = json.dumps(response.json())
            return truncate_tool_output(raw, "search_literature")

        elif tool_name == "update_project_notes":
            project_code = tool_args.get("project_code", "")
            note_text    = tool_args.get("note_text", "")
            author       = user_email if user_email and user_email != "unknown" else tool_args.get("author", "agent")
            exp_number_full = tool_args.get("exp_number_full")
            note_type       = tool_args.get("note_type", "decision")
            if not project_code or not note_text:
                return json.dumps({"error": "update_project_notes requires project_code and note_text"})
            response = await tool_client.post(
                f"{API_BASE}/api/ai/notes",
                json={"project_code": project_code, "note_text": note_text,
                      "captured_from": "chat", "author": author,
                      "exp_number_full": exp_number_full, "note_type": note_type},
                timeout=TOOL_CALL_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
            return json.dumps({
                "saved": True,
                "note_id": data.get("note_id"),
                "project_code": project_code,
            })

        elif tool_name == "get_project_notes":
            project_code = tool_args.get("project_code", "")
            if not project_code:
                return json.dumps({"error": "get_project_notes requires project_code"})
            response = await tool_client.get(
                f"{API_BASE}/api/ai/notes/{project_code}",
                timeout=TOOL_CALL_TIMEOUT
            )
            response.raise_for_status()
            raw = json.dumps(response.json())
            return truncate_tool_output(raw, "get_project_notes")

        elif tool_name == "fetch_project_reports":
            project_code = tool_args.get("project_code", "")
            response = await tool_client.get(
                f"{API_BASE}/api/ai/report/list/{project_code}",
                timeout=15,
            )
            response.raise_for_status()
            raw = json.dumps(response.json())
            return truncate_tool_output(raw, "fetch_project_reports")

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    except httpx.TimeoutException:
        return json.dumps({"error": f"Tool {tool_name} timed out after {TOOL_CALL_TIMEOUT}s"})
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"Tool {tool_name} returned HTTP {e.response.status_code}"})
    except Exception as e:
        return json.dumps({"error": f"Tool {tool_name} failed: {str(e)}"})

# ── Create run + poll for completion ─────────────────────────────────────────
async def run_once(model, thread_id, foundry_client, tool_client, base_url, tool_calls_log, user_email: str = "unknown"):
    """
    Create a run on the given thread with the given model, poll it to completion,
    dispatching any tool calls along the way. Returns (status, run) where status
    is one of "completed", "failed", "cancelled", "expired", or "timeout".
    Raises HTTPException only for actual connection/timeout errors on the
    httpx calls themselves — run-level failures are returned, not raised.
    """
    try:
        r = await foundry_client.post(
            f"{base_url}/threads/{thread_id}/runs?api-version={FOUNDRY_API_VER}",
            json={
                "assistant_id":          AGENT_ID,
                "model":                 model,
                "max_completion_tokens": 16384
            }
        )
        r.raise_for_status()
        run_id = r.json()["id"]
    except Exception as e:
        raise HTTPException(503, detail=f"Failed to start agent run: {str(e)}")

    elapsed = 0.0
    status = "queued"
    run = {}

    while elapsed < RUN_POLL_TIMEOUT:
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        try:
            r = await foundry_client.get(
                f"{base_url}/threads/{thread_id}/runs/{run_id}?api-version={FOUNDRY_API_VER}"
            )
            r.raise_for_status()
            run = r.json()
            status = run.get("status", "unknown")
        except httpx.TimeoutException:
            continue  # transient poll timeout — keep waiting
        except Exception as e:
            raise HTTPException(503, detail=f"Lost connection to AI service: {str(e)}")

        if status == "completed":
            break

        elif status == "requires_action":
            # ── Tool calls ────────────────────────────────────────────────
            tool_outputs = []
            calls = (
                run.get("required_action", {})
                   .get("submit_tool_outputs", {})
                   .get("tool_calls", [])
            )

            for call in calls:
                tool_name = call["function"]["name"]
                try:
                    tool_args = json.loads(call["function"]["arguments"])
                except json.JSONDecodeError:
                    tool_args = {}

                tool_calls_log.append({"tool": tool_name, "args": tool_args, "model": model})
                result = await dispatch_tool(tool_name, tool_args, tool_client, user_email)
                tool_outputs.append({"tool_call_id": call["id"], "output": result})

            # Cap total tool output size before submitting (Foundry limit ~32KB)
            total_size = sum(len(o["output"]) for o in tool_outputs)
            if total_size > 20000:
                for o in tool_outputs:
                    if len(o["output"]) > 3000:
                        o["output"] = o["output"][:3000] + "[TRUNCATED: use specific experiment_id for full detail]"

            # Submit tool outputs
            try:
                r = await foundry_client.post(
                    f"{base_url}/threads/{thread_id}/runs/{run_id}/submit_tool_outputs?api-version={FOUNDRY_API_VER}",
                    json={"tool_outputs": tool_outputs}
                )
                r.raise_for_status()
            except Exception as e:
                raise HTTPException(503, detail=f"Failed to submit tool results: {str(e)}")

        elif status in ("failed", "cancelled", "expired"):
            return status, run

    else:
        return "timeout", run

    return status, run

# ── Main chat endpoint ────────────────────────────────────────────────────────
@router.post("/api/ai/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    token = await get_foundry_token()
    foundry_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    base_url = FOUNDRY_ENDPOINT
    tool_calls_log = []

    foundry_timeout = httpx.Timeout(
        connect=CONNECT_TIMEOUT,
        read=60.0,
        write=30.0,
        pool=5.0
    )

    tool_timeout = httpx.Timeout(
        connect=CONNECT_TIMEOUT,
        read=TOOL_CALL_TIMEOUT,
        write=10.0,
        pool=5.0
    )

    # Two separate clients:
    # - foundry_client: talks to AI Foundry with AAD bearer token
    # - tool_client: talks to internal API endpoints (no auth needed)
    async with httpx.AsyncClient(headers=foundry_headers, timeout=foundry_timeout) as foundry_client, \
               httpx.AsyncClient(timeout=tool_timeout) as tool_client:

        # ── 1. Create or reuse thread ─────────────────────────────────────────
        try:
            if request.thread_id:
                thread_id = request.thread_id
            else:
                r = await foundry_client.post(
                    f"{base_url}/threads?api-version={FOUNDRY_API_VER}",
                    json={}
                )
                r.raise_for_status()
                thread_id = r.json()["id"]
        except httpx.TimeoutException:
            raise HTTPException(503, detail="Could not connect to AI service — please retry")
        except Exception as e:
            raise HTTPException(503, detail=f"Failed to create session: {str(e)}")

        # ── 2. Add user message ───────────────────────────────────────────────
        try:
            r = await foundry_client.post(
                f"{base_url}/threads/{thread_id}/messages?api-version={FOUNDRY_API_VER}",
                json={"role": "user", "content": request.message}
            )
            r.raise_for_status()
        except Exception as e:
            raise HTTPException(503, detail=f"Failed to send message: {str(e)}")

        user_email = request.user_email or "unknown"

        # ── 3-4. Create run and poll for completion (with one fallback retry) ─
        status, run = await run_once(AGENT_MODEL, thread_id, foundry_client, tool_client, base_url, tool_calls_log, user_email)
        model_used = AGENT_MODEL

        if (status == "failed"
                and run.get("last_error", {}).get("code") == "server_error"
                and AGENT_FALLBACK_MODEL
                and AGENT_FALLBACK_MODEL != AGENT_MODEL):
            status, run = await run_once(AGENT_FALLBACK_MODEL, thread_id, foundry_client, tool_client, base_url, tool_calls_log, user_email)
            model_used = AGENT_FALLBACK_MODEL

        if status in ("failed", "cancelled", "expired"):
            last_error = run.get("last_error", {})
            code = last_error.get("code", "unknown")
            message = last_error.get("message", "No details available")
            raise HTTPException(
                500,
                detail=f"Agent run {status} (model={model_used}): {code} — {message}"
            )

        elif status == "timeout":
            raise HTTPException(
                504,
                detail=f"Agent did not complete within {RUN_POLL_TIMEOUT}s (model={model_used}). Try a simpler question or break it into steps."
            )

        # ── 5. Retrieve assistant reply ───────────────────────────────────────
        try:
            r = await foundry_client.get(
                f"{base_url}/threads/{thread_id}/messages?api-version={FOUNDRY_API_VER}"
            )
            r.raise_for_status()
            messages = r.json().get("data", [])
        except Exception as e:
            raise HTTPException(503, detail=f"Failed to retrieve response: {str(e)}")

        # Most recent assistant message
        answer = ""
        for msg in messages:
            if msg.get("role") == "assistant":
                content = msg.get("content", [])
                for block in content:
                    if block.get("type") == "text":
                        answer = block["text"]["value"]
                        break
                if answer:
                    break

        if not answer:
            raise HTTPException(500, detail="Agent returned an empty response")

        return ChatResponse(
            answer=answer,
            thread_id=thread_id,
            tool_calls=tool_calls_log,
            model_used=model_used
        )
