"""
scripts/provision_agent_v2_live_test.py
Stdlib-only, one-off provisioning script for the AIE-406b/agent_v2 migration
draft. Creates the two throwaway test agent versions
(routers/agent_v2.py's AGENT_NAME_V2 / AGENT_NAME_V2_FALLBACK) against the
live Foundry endpoint, so routers/agent_v2.py's chat()/generate_response()
have something real to reference.

This is intentionally standalone — no httpx, no fastapi, no importing
routers/agent_v2.py — mirroring the exact get_token()/foundry_get() pattern
already used in scripts/export_live_agent_config.py (az CLI subprocess for
the token, urllib for the request).

Usage (Azure Cloud Shell, or locally if `az login` is already active):
    cd ~/eln-api
    python scripts/provision_agent_v2_live_test.py

Requires env vars (or falls back to hardcoded defaults):
    FOUNDRY_ENDPOINT
Azure CLI must be logged in (az login / managed identity).

This makes REAL POST calls to {FOUNDRY_ENDPOINT}/agents?api-version=v1 — an
endpoint this repo has never called before. It is not a dry run.
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

REPO_ROOT               = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TOOLS_EXPORT_PATH       = os.path.join(REPO_ROOT, "prompts", "agent_tools_current_export.json")
INSTRUCTIONS_EXPORT_PATH = os.path.join(REPO_ROOT, "prompts", "system_prompt_current_export.txt")

AGENTS_TO_PROVISION = [
    {"name": "eln-agent-v2-test",          "model": "gpt-5-4"},
    {"name": "eln-agent-v2-test-fallback", "model": "gpt-4o"},
]

# Real production agent names for the actual cutover. Kept in a SEPARATE
# list so a bare re-run of this script (no env var set) can never touch
# these by accident — only used when PROVISION_TARGET=prod is set explicitly.
PROD_AGENTS_TO_PROVISION = [
    {"name": "eln-agent-v2-prod",          "model": "gpt-5-4"},
    {"name": "eln-agent-v2-prod-fallback", "model": "gpt-4o"},
]


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


def foundry_post(path: str, body: dict) -> dict:
    """POST-only Foundry request for this script — mirrors foundry_get()'s pattern in export_live_agent_config.py."""
    url   = f"{FOUNDRY_ENDPOINT}/{path}?api-version=v1"
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


def load_tools() -> list:
    """
    Read the six committed tool schemas directly — no duplicate copy of
    their content inline — then flatten each from the Assistants
    tool-wrapper shape on disk ({"type":"function","function":{"name":...}})
    to the flat shape Foundry's /agents endpoint expects
    ({"type":"function","name":...,"description":...,"parameters":...}).
    This mirrors routers/agent_v2.py's _load_tools_v2() exactly (duplicated
    here, not imported, per this script's standalone-only requirement) —
    the earlier version of this function skipped this step entirely and
    submitted the raw nested shape, which is why Foundry rejected all six
    tools with "Required properties [\"name\"] are not present".
    """
    with open(TOOLS_EXPORT_PATH, "r", encoding="utf-8") as f:
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


def load_instructions() -> str:
    """Read the committed full system prompt directly — no duplicate copy inline."""
    with open(INSTRUCTIONS_EXPORT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def main():
    target = os.environ.get("PROVISION_TARGET", "test").lower()
    if target == "test":
        agents_to_provision = AGENTS_TO_PROVISION
    elif target == "prod":
        agents_to_provision = PROD_AGENTS_TO_PROVISION
    else:
        print(f"ERROR: Unknown PROVISION_TARGET={target!r} — must be 'test' or 'prod'")
        sys.exit(1)
    print(f"PROVISION_TARGET={target!r} — will provision: {[a['name'] for a in agents_to_provision]}")

    tools        = load_tools()
    instructions = load_instructions()
    print(f"Loaded {len(tools)} tool schemas from {TOOLS_EXPORT_PATH}")
    print(f"Loaded {len(instructions)}-character instructions from {INSTRUCTIONS_EXPORT_PATH}")

    for agent in agents_to_provision:
        name  = agent["name"]
        model = agent["model"]
        print(f"\nProvisioning agent '{name}' (model={model}) …")

        body = {
            "name": name,
            "definition": {
                "kind":         "prompt",
                "model":        model,
                "instructions": instructions,
                "tools":        tools,
            },
        }

        try:
            created = foundry_post("agents", body)
        except urllib.error.HTTPError:
            print(f"FAILED to provision '{name}' — see HTTP error body above.")
            continue

        print(f"Response for '{name}':")
        print(json.dumps(created, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
