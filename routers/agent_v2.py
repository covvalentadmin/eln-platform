"""
routers/agent_v2.py — DRAFT migration, Foundry Conversations + Responses API
FastAPI router for POST /api/ai/chat — NOT wired into main.py, NOT deployed,
NOT tested against a live Foundry endpoint. Review-only.

This drafts routers/agent.py's chat()/run_once() off the legacy Assistants
REST surface (threads/runs/messages, poll for run status, submit_tool_outputs)
onto the newer surface:
    POST {endpoint}/openai/v1/conversations              — create a conversation
    POST {endpoint}/openai/v1/conversations/{id}/items   — append an item
                                                            (e.g. a new user
                                                            message) to an
                                                            existing conversation
    POST {endpoint}/openai/v1/responses                  — generate a response
                                                            for a conversation;
                                                            synchronous — no
                                                            separate run+poll step
The external contract is unchanged: ChatRequest/ChatResponse are reused
as-is from routers.agent, so `thread_id` still means "thread_id" to the
frontend even though it now holds a conversation_id internally.

A third phase now exists too: provision_agent_version(agent_name, model)
creates a persisted Foundry Agent resource (POST {endpoint}/agents?api-version=v1)
with a given model plus the real tool schemas and full system prompt baked
into its definition — ONCE. generate_response() (the renamed, narrowed
run_once() — see below)'s /responses calls then reference that agent by
name only (via "agent_reference") — no model/tools/instructions travel over
the wire per conversational turn. provision_agent_version() is NOT called
automatically anywhere in this file; it must be run deliberately, by hand —
once for AGENT_NAME_V2 (with the primary model) and once for
AGENT_NAME_V2_FALLBACK (with a distinct fallback model) — against throwaway
test agent names before chat() ever points at production ones.

TWO-AGENT-VERSION FALLBACK DESIGN: the legacy surface (routers/agent.py)
could retry a failed run against a different model with a single field on
one API call, because "model" was just part of the run-creation request.
Under this newer surface, model is baked into a named agent version's
definition at provision time — there is no per-call "model" field on a
/responses request left to swap. So a model-level fallback here necessarily
means maintaining TWO provisioned agent versions (AGENT_NAME_V2, backed by
the primary model, and AGENT_NAME_V2_FALLBACK, backed by a distinct one) and
retrying a failed response generation against the second agent_name, over
the SAME conversation — see chat() below. Message-adding is deliberately
factored out of the retry path entirely (see the next paragraph), so this
retry can never double-send the user's message no matter which agent it's
retried against.

chat() now adds the user's message to the conversation EXACTLY ONCE, before
any retry logic — via conversations.create(items=[...]) for a brand-new
conversation, or conversations.items.create(conversation_id=..., items=[...])
for a continuing one — and this step is never retried. generate_response()
then only ever generates a response for whatever the conversation's current
state already is: input=[] for the first /responses call of an attempt (the
message is already in the conversation), input=<function_call_output items>
for subsequent tool-calling rounds within that same attempt. It takes
agent_name as a parameter and never adds anything to the conversation
itself.

═══════════════════════════════════════════════════════════════════════════
KNOWN GAPS / THINGS I GUESSED AT — READ BEFORE USING THIS FILE FOR ANYTHING
═══════════════════════════════════════════════════════════════════════════

1. [RESOLVED] TOOL SCHEMAS. Previously only 3 of 6 tool schemas were real
   (the other 3 were reconstructed/guessed from the REST endpoints they call,
   since no committed file had them). scripts/export_live_agent_config.py
   was run against the live Foundry Assistant and its GET output committed
   as prompts/agent_tools_current_export.json — the real, live 6-tool JSON
   Schemas. TOOLS_V2 below now loads ALL SIX from that file at runtime (see
   _load_tools_v2()) rather than hardcoding any of them in this .py file, so
   there's no duplicate copy to drift out of sync. TOOLS_V2 is consumed by
   provision_agent_version() only — baked into the named agent version once
   at provisioning time (now parameterized by `model` too — see task list —
   but tools/instructions are unaffected by which model is chosen), NOT
   resent on every /responses call (see gap #2's resolution note below for
   why generate_response() no longer sends tools at all). One guess REMAINS
   here, narrower than before: _load_tools_v2() flattens the source data
   from the Assistants tool-wrapper shape
   ({"type":"function","function":{...}}, which is what's actually in the
   committed export) to the Responses-API flat shape
   ({"type":"function","name":...,...}) for the "tools" field inside
   provision_agent_version()'s agent-definition body. Whether Azure's v1
   Agents surface actually wants tools flat there, rather than still nested
   under "function", has NOT been verified against Azure's actual API
   reference — the DATA is now real, but this structural transform is still
   a guess.

2. [RESOLVED] SYSTEM PROMPT / INSTRUCTIONS. Previously nothing was sent —
   there was no committed file with the full merged prompt (base + PROJECT
   MEMORY additions), only the additions were committed
   (prompts/system_prompt_patch.json). scripts/export_live_agent_config.py's
   GET output for `instructions` was committed as
   prompts/system_prompt_current_export.txt — the real, live, full
   18,591-character system prompt. Instructions are NOT sent on every
   /responses call. They're loaded via _load_instructions() and sent
   exactly ONCE — inside provision_agent_version(), at agent-version-
   creation time — baked into the persisted agent resource's definition
   alongside the model (now a parameter, not the hardcoded AGENT_MODEL) and
   tools. Every ordinary /responses call in generate_response() afterwards
   just references that agent version by name (via "agent_reference") and
   sends nothing else — no model, no tools, no instructions, on every turn.
   The model still ends up running with the same prompt the live Assistant
   has; it's just delivered once at provisioning instead of resent on every
   message.

3. WIRE FORMAT FOR /conversations, /conversations/{id}/items, AND /responses —
   PARTIALLY CONFIRMED by a live run via scripts/test_response_live.py
   against eln-agent-v2-test:
   - [CONFIRMED] The /responses agent reference: top-level key MUST be
     "agent_reference" (nested {"type": "agent_reference", "name": ...}).
     A top-level "agent" key was tried first and Foundry returned a 400:
     "The 'agent' property is deprecated. Use 'agent_reference' instead." —
     so "agent_reference" is not a guess anymore, it's the confirmed,
     required key, and "agent" is confirmed WRONG (deprecated, will 400).
   - [CONFIRMED] A conversation item's "content" must be a structured array
     of blocks ({"type": "input_text", "text": ...}), not a plain string —
     the live conversation-create call succeeded with this shape and the
     subsequent /responses call generated a real reply from it.
   - [STILL UNCONFIRMED] Everything else in this gap remains open: the
     /conversations/{id}/items sub-resource path and its bare
     {"items": [...]} body (used by _conversation_items_create() for a
     CONTINUING conversation) was not exercised by the live test — only
     conversation creation was. Likewise unconfirmed: "output",
     "type": "function_call", "call_id", "function_call_output", and
     "output_text" — the live test only exercised a no-tool-call turn and
     printed the raw response rather than running it through this file's
     own output-parsing logic in chat(), so the "output_text" vs "text"
     content-block branch and the function_call round-trip are both still
     reconstructed from the general publicly documented OpenAI Responses
     API shape, not verified. There is still no azure-ai-projects or
     azure-ai-agents dependency in requirements.txt, and no SDK reference in
     this repo to check the rest against.

   NOTED OBSERVATION (not a gap to fix, just worth knowing): the live
   no-tool-call response's own prose, when asked to describe itself and
   list its tools, mentioned a tool name — "multi_tool_use.parallel" — that
   does NOT appear anywhere in TOOLS_V2 or the six real schemas in
   prompts/agent_tools_current_export.json. The model appears to have
   hallucinated it into its self-description rather than actually invoking
   it (no function_call item was present in the output). Worth re-checking
   once a real tool-call round trip has been tested, in case it turns out to
   be some Foundry-injected meta-tool rather than a pure hallucination.

4. No `?api-version=...` query param is appended to the v1 calls, per your
   instructions giving the paths without one. I don't know whether Azure's
   v1 surface still requires api-version — flagging rather than guessing
   which value to add.

5. RUN-LEVEL "status" HANDLING is reshaped, since the Responses API has no
   Assistants-style run object to poll — see generate_response()'s
   docstring below for exactly how the old status vocabulary
   ("completed"/"failed"/"cancelled"/"expired"/"timeout") maps (or doesn't)
   onto this surface.

6. [UPDATED] FALLBACK IS NOW A REAL TWO-AGENT-VERSION FALLBACK, AND THE
   DOUBLE-MESSAGE RISK FROM THE PREVIOUS REVISION IS STRUCTURALLY GONE — but
   a NEW, unresolved gap replaces it. Previously this was a same-agent retry
   with a real risk of double-sending the user's message (since the message
   was submitted as part of the same /responses call that could fail). That
   risk is now eliminated: chat() adds the user's message to the
   conversation via conversations.create()/conversations.items.create()
   EXACTLY ONCE, before either agent attempt, and generate_response() never
   adds to the conversation itself — so retrying against
   AGENT_NAME_V2_FALLBACK on the SAME conversation cannot resend the
   message, structurally, regardless of what a failed attempt did or didn't
   record server-side.

   NEW, UNRESOLVED GAP: the exact shape of a FAILED /responses response body
   — what generate_response() reads as "last_error" (a "code"/"message"
   pair) to decide whether a failure is retryable — is UNCONFIRMED. It is
   reconstructed from the general pattern of an HTTP error body having an
   "error" key with "code"/"message" fields, exactly as in the previous
   revision of this file, and has NOT been verified against an actual
   failed response from a live Azure Foundry /responses call. Do not assume
   this shape is correct — trigger a real failure (e.g. a deliberately bad
   agent_reference, or an invalid conversation_id) against a throwaway test
   agent and inspect the actual error body before trusting the
   `code == "server_error"` check that gates the fallback retry in chat().
"""

import os
import json
import httpx
from fastapi import APIRouter, HTTPException

from routers.agent import (
    dispatch_tool,
    get_foundry_token,
    ChatRequest,
    ChatResponse,
    FOUNDRY_ENDPOINT,
    CONNECT_TIMEOUT,
    TOOL_CALL_TIMEOUT,
)

router = APIRouter()

# Guard against an infinite function-calling loop. The Responses API has no
# server-side run/poll timeout the way Assistants runs did (RUN_POLL_TIMEOUT
# in agent.py) — each /responses call is a single synchronous round trip, so
# the only unbounded-loop risk is the model calling tools forever. This caps
# the number of tool-calling round trips per turn instead of wall-clock time.
MAX_TOOL_ROUNDS = 8

# Draft/throwaway test agent-version names — the persisted Foundry Agent
# resources created by provision_agent_version(), NOT model names. Kept as
# named constants and threaded through chat()/generate_response() as
# explicit parameters, rather than hardcoded inline in the request flow, so
# swapping between these throwaway test agents and real ones later is a
# one-line change here, not a buried literal. AGENT_NAME_V2_FALLBACK backs
# the model-level fallback described in the module docstring's
# "TWO-AGENT-VERSION FALLBACK DESIGN" section — it must be a SEPARATE
# provisioned agent version (typically pinned to a different model) for the
# fallback to mean anything.
AGENT_NAME_V2          = os.environ.get("AGENT_NAME_V2", "eln-agent-v2-test")
AGENT_NAME_V2_FALLBACK = os.environ.get("AGENT_NAME_V2_FALLBACK", "eln-agent-v2-test-fallback")

# ── Tool definitions + instructions — loaded from committed exports, not
# hardcoded here (see gaps #1 and #2 in the module docstring for provenance) ─
_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prompts")


def _load_tools_v2() -> list:
    """
    Load the live agent's real tool schemas from
    prompts/agent_tools_current_export.json (the GET output of
    scripts/export_live_agent_config.py, run against the live Foundry
    Assistant — see that script for provenance), read the same way
    scripts/update_agent_tools.py reads prompts/system_prompt_patch.json.
    Flattens each entry from the Assistants tool-wrapper shape found in that
    file ({"type":"function","function":{...}}) to the Responses-API flat
    shape ({"type":"function","name":...,"description":...,"parameters":...}).
    GUESS (unresolved, see gap #1 in the module docstring): whether Azure's
    v1 Responses surface actually wants tools flat rather than nested under
    "function" — the SOURCE data is now real/verbatim, only this structural
    transform is still unverified.
    """
    path = os.path.join(_PROMPTS_DIR, "agent_tools_current_export.json")
    with open(path, "r", encoding="utf-8") as f:
        raw_tools = json.load(f)

    flattened = []
    for t in raw_tools:
        if t.get("type") != "function" or "function" not in t:
            continue
        fn = t["function"]
        flattened.append({
            "type":        "function",
            "name":        fn["name"],
            "description": fn.get("description", ""),
            "parameters":  fn.get("parameters", {}),
            "strict":      fn.get("strict", False),
        })
    return flattened


def _load_instructions() -> str:
    """
    Load the live agent's real, full system prompt from
    prompts/system_prompt_current_export.txt (the GET output of
    scripts/export_live_agent_config.py). Closes gap #2 — the model now
    receives the same instructions the live Assistant has, sent explicitly
    per-call since the Responses API has no assistant_id to carry them
    implicitly.
    """
    path = os.path.join(_PROMPTS_DIR, "system_prompt_current_export.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


TOOLS_V2           = _load_tools_v2()
AGENT_INSTRUCTIONS = _load_instructions()


async def provision_agent_version(agent_name: str, model: str, token: str) -> dict:
    """
    ONE-OFF PROVISIONING STEP — NOT called automatically by chat() or
    generate_response(), and not called anywhere else in this file either.
    Creates a persisted Foundry Agent resource named `agent_name`, backed by
    `model`, with the real tool schemas (prompts/agent_tools_current_export.json,
    via the existing _load_tools_v2(), already flattened) and the real full
    system prompt (prompts/system_prompt_current_export.txt, via the
    existing _load_instructions()) baked into its definition — so that
    ordinary /responses calls in generate_response() only need to reference
    this agent by name via "agent_reference", never resending
    model/tools/instructions on every conversational turn.

    Takes a pre-fetched AAD `token` string rather than calling
    get_foundry_token() itself, so the caller controls token acquisition
    (e.g. fetching once and reusing it across both a primary and fallback
    provisioning call).

    Call this deliberately, by hand, against throwaway test agent names —
    e.g. await provision_agent_version(AGENT_NAME_V2, "gpt-5-4", token) for
    the primary version (using whatever model string routers.agent.AGENT_MODEL
    currently resolves to), and
    await provision_agent_version(AGENT_NAME_V2_FALLBACK, "gpt-4o", token)
    (or whatever distinct model should back the fallback) for the fallback
    version — NOT the production agent — before chat() is ever pointed at
    whatever names these create. This makes a real POST to the live Foundry
    endpoint; it is not a dry run. Both calls load tools/instructions from
    the SAME two committed files — only `model` differs between them.

    GUESS: the exact shape of POST {FOUNDRY_ENDPOINT}/agents?api-version=v1's
    request/response body — the "kind": "prompt" agent-definition pattern,
    and the "name"/"id"/"version" fields read off the response below — is
    reconstructed from the general publicly documented shape of a Foundry
    Agents "prompt agent" resource. Not verified against a live endpoint, an
    SDK reference, or any example in this repo.
    """
    tools = _load_tools_v2()
    instructions = _load_instructions()

    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{FOUNDRY_ENDPOINT}/agents?api-version=v1",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "name": agent_name,
                "definition": {
                    "kind":         "prompt",
                    "model":        model,
                    "instructions": instructions,
                    "tools":        tools,
                },
            },
        )
        r.raise_for_status()
        created = r.json()

    created_name    = created.get("name")
    created_id      = created.get("id")
    created_version = created.get("version")
    print(f"Provisioned agent '{created_name}' — id={created_id} version={created_version}")
    return created


async def _conversations_create(foundry_client: httpx.AsyncClient, base_url: str, items: list) -> str:
    """
    POST {base_url}/openai/v1/conversations — create a brand-new conversation
    seeded with `items` (e.g. the initial user message). Returns the new
    conversation's id.
    GUESS: exact shape of a conversation "item" — whether it needs an
    explicit "type": "message", or just {"role": ..., "content": ...} — is
    reconstructed from the general Responses/Conversations API shape, not
    verified against a live Foundry endpoint (see gap #3).
    """
    r = await foundry_client.post(
        f"{base_url}/openai/v1/conversations",
        json={"items": items}
    )
    r.raise_for_status()
    return r.json()["id"]


async def _conversation_items_create(foundry_client: httpx.AsyncClient, base_url: str, conversation_id: str, items: list) -> dict:
    """
    POST {base_url}/openai/v1/conversations/{conversation_id}/items — append
    `items` (e.g. a new user message) to an EXISTING conversation.
    GUESS: this sub-resource path and its bare {"items": [...]} request body
    are reconstructed from the general "conversations.items.create(...)"
    pattern — NOT verified against a live Foundry endpoint or any example in
    this repo (see gap #3).
    """
    r = await foundry_client.post(
        f"{base_url}/openai/v1/conversations/{conversation_id}/items",
        json={"items": items}
    )
    r.raise_for_status()
    return r.json()


# ── Generate a response for the CURRENT conversation state ───────────────────
async def generate_response(agent_name, conversation_id, foundry_client, tool_client, base_url, tool_calls_log, user_email: str = "unknown"):
    """
    Generate a response for `conversation_id` via POST .../openai/v1/responses,
    referencing the already-provisioned agent version `agent_name` (see
    provision_agent_version()). This function NEVER adds anything to the
    conversation itself — the user's message must already be there, added
    exactly once by chat() (via _conversations_create()/
    _conversation_items_create()) before this is ever called.

    The first /responses call of an attempt passes input=[] (the
    conversation already contains the user's message). If the model calls
    tools, subsequent calls within this SAME attempt pass
    input=<function_call_output items> to resubmit results — looping until
    no function_call items remain or MAX_TOOL_ROUNDS is hit.

    Every /responses call sends ONLY "agent_reference", "conversation", and
    "input" — no model/tools/instructions on the wire per turn; those are
    baked into the named agent version once, at provision_agent_version()
    time (see gaps #1/#2 in the module docstring).

    Returns (status, response) where status is one of:
      - "completed" — response ready, no more function calls pending
      - "failed"    — the /responses call itself errored; response is a dict
                       with a "last_error" key ({"code": ..., "message": ...})
                       shaped to match what chat()'s fallback-retry check
                       expects — GUESS, UNCONFIRMED (see gap #6): the exact
                       shape of a failed /responses body has NOT been
                       verified against a real failure. code defaults to
                       "server_error" if the body doesn't parse, which still
                       triggers the fallback path in chat().
      - "timeout"   — MAX_TOOL_ROUNDS exceeded (relabeled from the old
                       wall-clock RUN_POLL_TIMEOUT meaning, since this API has
                       no server-side run timeout to hit instead)
    "cancelled"/"expired" from the old Assistants surface have no equivalent
    here and are never returned by this function.
    """
    input_items = []

    for _round in range(MAX_TOOL_ROUNDS):
        try:
            r = await foundry_client.post(
                f"{base_url}/openai/v1/responses",
                json={
                    # CONFIRMED against a live Foundry 400 error: "agent" is
                    # deprecated ("The 'agent' property is deprecated. Use
                    # 'agent_reference' instead."). Top-level key must be
                    # "agent_reference", nested value shape
                    # {"type": "agent_reference", "name": ...} — see gap #3
                    # in the module docstring.
                    "agent_reference": {"type": "agent_reference", "name": agent_name},
                    "conversation":    conversation_id,
                    "input":           input_items,
                }
            )
            r.raise_for_status()
        except httpx.TimeoutException as e:
            raise HTTPException(503, detail=f"Lost connection to AI service: {str(e)}")
        except httpx.HTTPStatusError as e:
            # GUESS, UNCONFIRMED — see gap #6: exact Azure error body shape
            # for a failed /responses call has NOT been verified against a
            # real failure.
            try:
                err_body = e.response.json()
            except Exception:
                err_body = {}
            last_error = err_body.get("error") or {"code": "server_error", "message": str(e)}
            return "failed", {"last_error": last_error}
        except Exception as e:
            raise HTTPException(503, detail=f"Failed to reach AI service: {str(e)}")

        response = r.json()

        # GUESS: whether Azure's v1 /responses returns a "status" field on
        # every response, and what values besides "completed"/"failed"/
        # "incomplete" it might use, is not verified — defaulting to
        # "completed" when absent.
        status = response.get("status", "completed")
        if status == "failed":
            return "failed", response
        if status == "incomplete":
            # GUESS: mapping "incomplete" (e.g. hit max_output_tokens) to
            # "failed" for now — may deserve its own handling later.
            return "failed", response

        output_items = response.get("output", [])
        function_calls = [item for item in output_items if item.get("type") == "function_call"]

        print(f"generate_response: round {_round + 1}, response_id={response.get('id')}, {len(function_calls)} function_call(s) found")

        if not function_calls:
            return "completed", response

        # ── Execute each function_call and collect outputs ─────────────────
        tool_outputs = []
        for call in function_calls:
            tool_name = call.get("name")
            try:
                tool_args = json.loads(call.get("arguments") or "{}")
            except json.JSONDecodeError:
                tool_args = {}

            tool_calls_log.append({"tool": tool_name, "args": tool_args, "agent_name": agent_name})
            key_arg = tool_args.get("exp_number_full") or tool_args.get("experiment_id")
            print(f"generate_response: round {_round + 1} — dispatching tool={tool_name}, key_arg={key_arg}")
            result = await dispatch_tool(tool_name, tool_args, tool_client, user_email)
            tool_outputs.append({
                "type":    "function_call_output",
                "call_id": call.get("call_id"),
                "output":  result,
            })

        # Same 20KB total-output guard as the legacy Assistants surface's
        # ~32KB submit_tool_outputs limit — GUESS: not verified whether
        # /responses has the same or a different limit; keeping the existing
        # truncation policy as a safe default.
        total_size = sum(len(o["output"]) for o in tool_outputs)
        print(f"generate_response: round {_round + 1} — total tool output size: {total_size} bytes{' (TRUNCATION TRIGGERED)' if total_size > 20000 else ''}")
        if total_size > 20000:
            for o in tool_outputs:
                if len(o["output"]) > 3000:
                    o["output"] = o["output"][:3000] + "[TRUNCATED: use specific experiment_id for full detail]"

        input_items = tool_outputs

    return "timeout", {}


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

    async with httpx.AsyncClient(headers=foundry_headers, timeout=foundry_timeout) as foundry_client, \
               httpx.AsyncClient(timeout=tool_timeout) as tool_client:

        user_email = request.user_email or "unknown"

        # ── 1. Add the user's message to the conversation — EXACTLY ONCE,
        # before any retry logic. This step is never retried. ────────────────
        # GUESS: message content as a structured array of {"type": "input_text",
        # "text": ...} blocks rather than a plain string — pending
        # confirmation in scripts/test_response_live.py.
        message_items = [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": request.message}]}]
        try:
            if request.thread_id:
                conversation_id = request.thread_id
                await _conversation_items_create(foundry_client, base_url, conversation_id, message_items)
            else:
                conversation_id = await _conversations_create(foundry_client, base_url, message_items)
        except httpx.TimeoutException:
            raise HTTPException(503, detail="Could not connect to AI service — please retry")
        except Exception as e:
            raise HTTPException(503, detail=f"Failed to create session: {str(e)}")

        # ── 2-4. Generate a response, looping over tool calls (with fallback
        # to a second, distinct agent version on a retryable failure) ────────
        status, response = await generate_response(AGENT_NAME_V2, conversation_id, foundry_client, tool_client, base_url, tool_calls_log, user_email)
        agent_used = AGENT_NAME_V2

        # Diagnostic print, unconditional — runs regardless of which branch
        # of the if-check below fires, so the real object is visible on the
        # next failure whether or not it matches "server_error" exactly.
        print(f"chat(): generate_response(agent={agent_used}) returned status={response.get('status')!r}, error={response.get('error')!r}")

        # CORRECTED: was checking response.get("last_error", {}).get("code") —
        # "last_error" is the legacy Assistants-API "run" object's field name.
        # The actual Responses API field is top-level "error" (confirmed via
        # the official Response object reference schema and our own captured
        # live response body, which showed "error": null at the top level).
        if (status == "failed"
                and (response.get("error") or {}).get("code") == "server_error"):
            # Retries against a SECOND provisioned agent version
            # (AGENT_NAME_V2_FALLBACK), over the SAME conversation, WITHOUT
            # re-adding any message — the message-add step above already ran
            # exactly once, before either attempt, so this retry cannot
            # double-send it. See the module docstring's "TWO-AGENT-VERSION
            # FALLBACK DESIGN" section for why this is a real model-level
            # fallback again (via a distinct agent_name), and gap #6 for the
            # still-unconfirmed shape of "error" gating this retry.
            status, response = await generate_response(AGENT_NAME_V2_FALLBACK, conversation_id, foundry_client, tool_client, base_url, tool_calls_log, user_email)
            agent_used = AGENT_NAME_V2_FALLBACK

        if status == "failed":
            last_error = response.get("last_error", {})
            code = last_error.get("code", "unknown")
            message = last_error.get("message", "No details available")
            raise HTTPException(
                500,
                detail=f"Agent run {status} (agent={agent_used}): {code} — {message}"
            )

        elif status == "timeout":
            raise HTTPException(
                504,
                detail=f"Agent did not complete within {MAX_TOOL_ROUNDS} tool-call rounds (agent={agent_used}). Try a simpler question or break it into steps."
            )

        # ── 5. Extract assistant reply from response["output"] ───────────────
        # GUESS: exact shape of a Responses-API "message" output item's
        # content blocks (type == "output_text" vs "text"; flat "text" field
        # vs Assistants-style nested {"text": {"value": ...}}) is
        # reconstructed from the general public Responses API shape and NOT
        # verified against a live Azure Foundry response body.
        answer = ""
        for item in response.get("output", []):
            if item.get("type") == "message" and item.get("role") == "assistant":
                for block in item.get("content", []):
                    if block.get("type") in ("output_text", "text"):
                        answer = block.get("text", "")
                        break
                if answer:
                    break

        if not answer:
            # Many Responses API implementations expose a convenience
            # top-level "output_text" aggregate string — GUESS: not verified
            # whether Azure's v1 body includes this.
            answer = response.get("output_text", "")

        if not answer:
            raise HTTPException(500, detail="Agent returned an empty response")

        return ChatResponse(
            answer=answer,
            thread_id=conversation_id,  # external contract: still "thread_id"
            tool_calls=tool_calls_log,
            # ChatResponse's field name is unchanged ("model_used"), but its
            # value is now the agent_name used, not a model string — the
            # model itself is baked into that agent version, not chosen
            # per-call anymore.
            model_used=agent_used
        )
