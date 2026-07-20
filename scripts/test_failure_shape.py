"""
scripts/test_failure_shape.py
Stdlib-only, one-off live test that DELIBERATELY triggers a failed
/responses call, to capture the real shape of a failed response body —
closing gap #6 in routers/agent_v2.py's module docstring (the exact shape
of a failed /responses body, and which field chat() should check to decide
whether a failure is retryable, was UNCONFIRMED against a live failure).

Mirrors scripts/test_response_live.py's exact pattern: stdlib only (no
httpx, no fastapi, no importing routers/agent_v2.py), az CLI subprocess for
the token, urllib for the request.

Usage (Azure Cloud Shell, or locally if `az login` is already active):
    cd ~/eln-api
    python scripts/test_failure_shape.py

Requires env vars (or falls back to hardcoded defaults):
    FOUNDRY_ENDPOINT
Azure CLI must be logged in (az login / managed identity).

This makes REAL POST calls to {FOUNDRY_ENDPOINT}/openai/v1/conversations and
{FOUNDRY_ENDPOINT}/openai/v1/responses. It is not a dry run. The /responses
call is expected — and intended — to fail: it references an agent_reference
name ("eln-agent-v2-test-DOES-NOT-EXIST") that was never provisioned, purely
to observe what a real failure body looks like.
"""

import os
import sys
import json
import urllib.request
import urllib.error
import subprocess

FOUNDRY_ENDPOINT = os.environ.get(
    "FOUNDRY_ENDPOINT",
    "https://aifoundry-eln-covvalent.services.ai.azure.com/api/projects/eln-agent-project"
)

# Deliberately wrong — guaranteed not to exist, so the /responses call below
# is guaranteed to fail.
BAD_AGENT_NAME = "eln-agent-v2-test-DOES-NOT-EXIST"
TEST_MESSAGE   = "Hello — this call is expected to fail."


def get_token() -> str:
    """Get AAD token via Azure CLI."""
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


def foundry_post(url: str, body: dict) -> dict:
    """POST-only Foundry request — mirrors foundry_post() in test_response_live.py."""
    token = get_token()
    data  = json.dumps(body).encode("utf-8")
    req   = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        }
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    conversations_url = f"{FOUNDRY_ENDPOINT}/openai/v1/conversations"
    responses_url     = f"{FOUNDRY_ENDPOINT}/openai/v1/responses"

    # ── Step 1: create a conversation seeded with a test message ────────────
    conversation_body = {
        "items": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": TEST_MESSAGE}],
            }
        ]
    }
    print("Creating conversation …")
    print(json.dumps(conversation_body, indent=2, ensure_ascii=False))

    conversation = foundry_post(conversations_url, conversation_body)
    print("\nFull conversation-create response:")
    print(json.dumps(conversation, indent=2, ensure_ascii=False))

    conversation_id = conversation.get("id")
    if not conversation_id:
        print("\nERROR: no 'id' field in conversation response — cannot proceed.")
        sys.exit(1)
    print(f"\nConversation id: {conversation_id}")

    # ── Step 2: POST /responses referencing a NON-EXISTENT agent_reference —
    # guaranteed to fail. Whatever comes back (a raised HTTPError with a JSON
    # body, or a 200 with a "failed"/"error" field in the body) is printed in
    # full, raw, unfiltered. ─────────────────────────────────────────────────
    responses_body = {
        "agent_reference": {"type": "agent_reference", "name": BAD_AGENT_NAME},
        "conversation":    conversation_id,
        "input":           [],
    }
    print(f"\nPOSTing /responses with a deliberately nonexistent agent_reference ({BAD_AGENT_NAME!r}):")
    print(json.dumps(responses_body, indent=2, ensure_ascii=False))

    try:
        result = foundry_post(responses_url, responses_body)
        print(f"\n{'=' * 60}")
        print("NO HTTPError raised — got a 200 response body instead.")
        print(f"{'=' * 60}")
        print("Full raw /responses body:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except urllib.error.HTTPError as e:
        raw_body = e.read()
        print(f"\n{'=' * 60}")
        print(f"HTTPError raised — HTTP {e.code} {e.reason}")
        print(f"{'=' * 60}")
        print("Full raw error body (as returned, unparsed):")
        try:
            decoded = raw_body.decode("utf-8")
            print(decoded)
            print("\nSame body, pretty-printed (if valid JSON):")
            print(json.dumps(json.loads(decoded), indent=2, ensure_ascii=False))
        except (UnicodeDecodeError, json.JSONDecodeError):
            print(repr(raw_body))


if __name__ == "__main__":
    main()
