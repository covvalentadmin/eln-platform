"""
scripts/export_live_agent_config.py
Read-only export of the live Foundry agent's tools + instructions, so they
can be diffed against what's committed in this repo (scripts/update_agent_tools.py,
prompts/system_prompt_patch.json) before planning any migration work.

Usage (Azure Cloud Shell, or locally if `az login` is already active):
    cd ~/eln-api
    python scripts/export_live_agent_config.py

Requires env vars (or falls back to hardcoded defaults):
    FOUNDRY_ENDPOINT, FOUNDRY_API_VERSION, AGENT_ID
Azure CLI must be logged in (az login / managed identity).

This script is GET-only. There is no PATCH/POST capability anywhere in this
file — it cannot modify the live agent.
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
FOUNDRY_API_VER = os.environ.get("FOUNDRY_API_VERSION", "2025-05-15-preview")
AGENT_ID        = os.environ.get("AGENT_ID", "asst_iujfiErrYF9CfqgyB6BqY4Xn")

REPO_ROOT                 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TOOLS_OUTPUT_PATH         = os.path.join(REPO_ROOT, "live_agent_tools_export.json")
INSTRUCTIONS_OUTPUT_PATH  = os.path.join(REPO_ROOT, "live_agent_instructions_export.txt")


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


def foundry_get(path: str) -> dict:
    """GET-only Foundry request — no method parameter, no PATCH/POST path exists in this file."""
    url   = f"{FOUNDRY_ENDPOINT}/{path}?api-version={FOUNDRY_API_VER}"
    token = get_token()
    req   = urllib.request.Request(
        url, method="GET",
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
    print(f"Fetching agent {AGENT_ID} …")
    agent = foundry_get(f"assistants/{AGENT_ID}")

    tools        = agent.get("tools", [])
    instructions = agent.get("instructions", "")

    with open(TOOLS_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(tools, f, indent=2, ensure_ascii=False)

    with open(INSTRUCTIONS_OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(instructions)

    tool_names = [
        t["function"]["name"]
        for t in tools
        if t.get("type") == "function" and "function" in t
    ]

    print(f"Tools found ({len(tool_names)}): {tool_names}")
    print(f"Instructions length: {len(instructions)} characters")
    print(f"Wrote {TOOLS_OUTPUT_PATH}")
    print(f"Wrote {INSTRUCTIONS_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
