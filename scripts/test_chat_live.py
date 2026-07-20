"""
scripts/test_chat_live.py
First live exercise of routers/agent_v2.py's own chat() end-to-end. Unlike
scripts/test_response_live.py (stdlib-only, hand-rolled requests that mirror
the wire format by hand), this script imports and calls the actual
chat()/ChatRequest from routers.agent_v2 directly — the point is to test
THIS file's code (conversation creation, generate_response()'s tool-call
loop, dispatch_tool(), the output-parsing branches in chat() — all still
full of GUESS/UNCONFIRMED markers per its module docstring), not a
reimplementation of it.

The test question is chosen to force at least one real function_call round
trip (fetch_experiment and/or search_experiments), since gap #3 in
routers/agent_v2.py's module docstring explicitly flags the function-call
round trip (function_call / call_id / function_call_output / output_text)
as UNCONFIRMED — scripts/test_response_live.py only ever exercised a
no-tool-call turn.

═══════════════════════════════════════════════════════════════════════════
PREREQUISITE — READ BEFORE RUNNING. THIS WILL NOT WORK ON MOST MACHINES.
═══════════════════════════════════════════════════════════════════════════
chat() normally calls routers.agent.get_foundry_token(), which uses
azure.identity.aio.ManagedIdentityCredential — this ONLY works on an Azure
resource that actually has a managed identity attached (an App Service, a
VM, a Container App, etc.), and does NOT fall back to `az login` or any
other credential type. This local machine and Azure Cloud Shell both lack
a managed identity of their own, so get_foundry_token() as originally
written would hang/fail in either place.

To make this script actually runnable from Cloud Shell, get_foundry_token
is monkey-patched (see below) with a test-only replacement that shells out
to `az account get-access-token`, mirroring get_token() in
scripts/export_live_agent_config.py exactly. This sidesteps the managed-
identity problem ONLY for this manual test script — it is not a fix to
routers/agent_v2.py or routers/agent.py, which still call the real
ManagedIdentityCredential-based get_foundry_token() in production.

Also note: importing routers.agent_v2 transitively imports routers.agent,
which reads os.environ["FOUNDRY_ENDPOINT"] and os.environ["AGENT_ID"] at
MODULE IMPORT TIME with no defaults (KeyError if unset). Both are seeded
with os.environ.setdefault(...) below, before the import, so the import
itself doesn't blow up — AGENT_ID only satisfies that module-level read in
routers.agent; agent_v2.py's own code path never uses it, since it
references agents by name via AGENT_NAME_V2/AGENT_NAME_V2_FALLBACK instead.

Usage (Azure Cloud Shell, or anywhere `az login` / `az account get-access-
token` already works):
    cd ~/eln-api   # repo root
    python scripts/test_chat_live.py

This makes REAL calls through chat(): real /conversations, /responses, and
(for the read-only tools) real POSTs/GETs to API_BASE's /api/ai/fetch,
/api/search, /api/ai/literature, /api/ai/notes/{code}, /api/ai/report/{code}.
It is not a dry run — EXCEPT for update_project_notes, which this script
intercepts and never actually sends (see the safety wrapper below).
"""

import os
import sys
import json
import asyncio
import traceback
import subprocess

# ── Seed required env vars BEFORE importing routers.agent_v2 (which
# transitively imports routers.agent) so the module-level os.environ[...]
# reads in routers.agent don't KeyError. ────────────────────────────────────
os.environ.setdefault(
    "FOUNDRY_ENDPOINT",
    "https://aifoundry-eln-covvalent.services.ai.azure.com/api/projects/eln-agent-project"
)
os.environ.setdefault("AGENT_ID", "asst_iujfiErrYF9CfqgyB6BqY4Xn")

# Make the `routers` package importable regardless of the cwd this script
# is invoked from.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from routers import agent_v2

# Real question from the AIE-301 review doc — chosen because it's known to
# require fetch_experiment and/or search_experiments, forcing at least one
# real function_call round trip through generate_response()'s tool loop.
# Overridable via a command-line argument: python scripts/test_chat_live.py "<message>"
TEST_MESSAGE = sys.argv[1] if len(sys.argv) > 1 else "What experiments have we done on tryptophan synthesis?"

# Records every intercepted update_project_notes call, for the final report.
_intercepted_notes_calls = []


# ── Test-only replacement for get_foundry_token() ───────────────────────────
async def _fake_get_foundry_token() -> str:
    """
    Mirrors get_token() in scripts/export_live_agent_config.py exactly:
    shells out to the Azure CLI rather than using ManagedIdentityCredential,
    so this script can run from Cloud Shell (or anywhere `az login` is
    already active) instead of requiring a managed identity.
    """
    try:
        result = subprocess.run(
            ["az", "account", "get-access-token",
             "--resource", "https://ai.azure.com",
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"ERROR: az CLI failed — {e.stderr}")
        sys.exit(1)


# ── Safety wrapper around dispatch_tool ─────────────────────────────────────
# Captured before patching agent_v2.dispatch_tool, so this wrapper can still
# call through to the REAL dispatch_tool for the five read-only tools.
_real_dispatch_tool = agent_v2.dispatch_tool


async def _safe_dispatch_tool(tool_name, tool_args, tool_client, user_email="unknown"):
    """
    Same four parameters as the real dispatch_tool. Intercepts
    update_project_notes so this test run can never write a fake note to
    the live database — all other tools are read-only and pass through to
    the real implementation unmodified.
    """
    if tool_name == "update_project_notes":
        # Same author-resolution precedence as the real dispatch_tool in
        # routers/agent.py — reproduced exactly, not reimplemented loosely.
        resolved_author = (
            user_email if user_email and user_email != "unknown"
            else tool_args.get("author", "agent")
        )

        project_code    = tool_args.get("project_code")
        note_text       = tool_args.get("note_text")
        note_type       = tool_args.get("note_type")
        exp_number_full = tool_args.get("exp_number_full")

        print("\n" + "=" * 60)
        print("INTERCEPTED update_project_notes — NOT written to the live DB")
        print("=" * 60)
        print(f"  project_code:     {project_code}")
        print(f"  note_text:        {note_text}")
        print(f"  note_type:        {note_type}")
        print(f"  exp_number_full:  {exp_number_full}")
        print(f"  would have been written as author: {resolved_author}")
        print("=" * 60 + "\n")

        _intercepted_notes_calls.append({
            "project_code":    project_code,
            "note_text":       note_text,
            "note_type":       note_type,
            "exp_number_full": exp_number_full,
            "resolved_author": resolved_author,
        })

        return json.dumps({
            "saved": True,
            "note_id": "TEST-INTERCEPTED-NOT-WRITTEN",
            "project_code": project_code,
        })

    # All other tools (fetch_experiment, search_experiments,
    # search_literature, get_project_notes, fetch_project_reports) are
    # read-only — pass through to the real implementation.
    return await _real_dispatch_tool(tool_name, tool_args, tool_client, user_email)


async def main():
    # ── Patch over the names agent_v2.py itself imported (routers/agent_v2.py
    # does `from routers.agent import dispatch_tool, get_foundry_token, ...`,
    # which binds them as agent_v2.dispatch_tool / agent_v2.get_foundry_token
    # in agent_v2's OWN module namespace — chat() resolves both names from
    # that namespace, so that's what must be patched, not routers.agent's). ──
    agent_v2.get_foundry_token = _fake_get_foundry_token
    agent_v2.dispatch_tool = _safe_dispatch_tool
    print("Patched agent_v2.get_foundry_token -> az-CLI-based test token fetch")
    print("Patched agent_v2.dispatch_tool -> safety wrapper (update_project_notes intercepted)")
    print()

    request = agent_v2.ChatRequest(
        message=TEST_MESSAGE,
        thread_id=None,
        user_email="test-harness@covvalent.com",
    )

    print("Calling chat() with:")
    print(f"  message:    {request.message!r}")
    print(f"  thread_id:  {request.thread_id!r}")
    print(f"  user_email: {request.user_email!r}")
    print()

    try:
        response = await agent_v2.chat(request)
    except Exception:
        # First-ever execution of this code path — print the full traceback
        # rather than letting it crash silently or get swallowed.
        print("chat() RAISED:")
        traceback.print_exc()
        _report_intercepted_notes()
        sys.exit(1)

    print("chat() returned a ChatResponse:")
    print(f"  answer:     {response.answer}")
    print(f"  thread_id:  {response.thread_id}")
    print(f"  tool_calls: {response.tool_calls}")
    print(f"  model_used: {response.model_used}")

    _report_intercepted_notes()


def _report_intercepted_notes():
    print()
    if not _intercepted_notes_calls:
        print("update_project_notes interception: did NOT fire during this run.")
        return

    print(f"update_project_notes interception: FIRED {len(_intercepted_notes_calls)} time(s):")
    for i, call in enumerate(_intercepted_notes_calls, 1):
        print(f"  [{i}] project_code:     {call['project_code']}")
        print(f"      note_text:        {call['note_text']}")
        print(f"      note_type:        {call['note_type']}")
        print(f"      exp_number_full:  {call['exp_number_full']}")
        print(f"      resolved_author:  {call['resolved_author']}")


if __name__ == "__main__":
    asyncio.run(main())
