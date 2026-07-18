"""
scripts/test_response_live.py
Stdlib-only, one-off live test against the Foundry Conversations + Responses
surface routers/agent_v2.py is drafted against. Verifies two of that file's
biggest unverified guesses (see its module docstring, gap #3) against a real
endpoint: (1) whether a conversation item's "content" needs to be a
structured [{"type": "input_text", "text": ...}] array rather than a plain
string, and (2) whether /responses references a provisioned agent version
via a top-level "agent" key or a top-level "agent_reference" key.

This is intentionally standalone — no httpx, no fastapi, no importing
routers/agent_v2.py — mirroring the exact get_token()/urllib pattern already
used in scripts/export_live_agent_config.py and
scripts/provision_agent_v2_live_test.py (az CLI subprocess for the token,
urllib for the request).

Usage (Azure Cloud Shell, or locally if `az login` is already active):
    cd ~/eln-api
    python scripts/test_response_live.py

Requires env vars (or falls back to hardcoded defaults):
    FOUNDRY_ENDPOINT
Azure CLI must be logged in (az login / managed identity).
Requires eln-agent-v2-test to already exist (see
scripts/provision_agent_v2_live_test.py) — this script does not provision it.

This makes REAL POST calls to {FOUNDRY_ENDPOINT}/openai/v1/conversations and
{FOUNDRY_ENDPOINT}/openai/v1/responses. It is not a dry run.
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

TEST_AGENT_NAME = "eln-agent-v2-test"
TEST_MESSAGE    = "Hello — briefly describe what you are and list the tools you have access to, without calling any of them."


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
    """
    POST-only Foundry request for this script — mirrors foundry_get()'s
    pattern in export_live_agent_config.py, but takes a full URL with no
    ?api-version=... appended, since the /openai/v1/... surface is called
    without that query param everywhere else in this repo (see
    routers/agent_v2.py's module docstring, gap #4).
    """
    token = get_token()
    data  = json.dumps(body).encode("utf-8")
    req   = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        print(f"HTTP {e.code} — {body_text}")
        raise


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

    # ── Step 2: Attempt A — top-level "agent" key (agent_v2.py's current,
    # post-fix convention) ───────────────────────────────────────────────────
    attempt_a_body = {
        "agent": {"type": "agent_reference", "name": TEST_AGENT_NAME},
        "conversation": conversation_id,
        "input": [],
    }
    print("\nAttempt A — POST /responses with top-level 'agent' key:")
    print(json.dumps(attempt_a_body, indent=2, ensure_ascii=False))

    final_result = None
    winning_key  = None

    try:
        final_result = foundry_post(responses_url, attempt_a_body)
        winning_key  = "agent"
    except urllib.error.HTTPError:
        # ── Step 3: Attempt A failed — retry as Attempt B with top-level
        # "agent_reference" key instead ─────────────────────────────────────
        print("\nAttempt A failed — see HTTP error body above. Retrying as Attempt B …")

        attempt_b_body = {
            "agent_reference": {"type": "agent_reference", "name": TEST_AGENT_NAME},
            "conversation": conversation_id,
            "input": [],
        }
        print("\nAttempt B — POST /responses with top-level 'agent_reference' key:")
        print(json.dumps(attempt_b_body, indent=2, ensure_ascii=False))

        try:
            final_result = foundry_post(responses_url, attempt_b_body)
            winning_key  = "agent_reference"
        except urllib.error.HTTPError:
            print("\nAttempt B ALSO failed — see HTTP error body above.")
            print("Neither 'agent' nor 'agent_reference' succeeded as the top-level key.")
            sys.exit(1)

    print(f"\n{'=' * 60}")
    print(f"SUCCESS — winning top-level key: '{winning_key}'")
    print(f"{'=' * 60}")
    print("Final /responses result:")
    print(json.dumps(final_result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
