"""
scripts/update_agent_tools.py — AIE-404
Adds update_project_notes and get_project_notes tools to the Foundry agent
and appends the PROJECT NOTES section to the agent system prompt.

Usage (Azure Cloud Shell):
    cd ~/eln-api
    python scripts/update_agent_tools.py

Requires env vars: FOUNDRY_ENDPOINT, FOUNDRY_API_VERSION, AGENT_ID
Azure CLI must be logged in (az login / managed identity).
"""

import os
import sys
import json
import urllib.request
import urllib.error
import subprocess

FOUNDRY_ENDPOINT = os.environ["FOUNDRY_ENDPOINT"]
FOUNDRY_API_VER  = os.environ.get("FOUNDRY_API_VERSION", "2025-05-15-preview")
AGENT_ID         = os.environ["AGENT_ID"]

NEW_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "update_project_notes",
            "description": (
                "Save a context note about a project that is NOT in the ELN database. "
                "Use when the user shares background information, external context, "
                "vendor details, IP considerations, timelines, or any insight that "
                "helps understand a project. Notes are visible to all @covvalent.com users."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_code": {
                        "type": "string",
                        "description": "Project code (e.g. CAS-2024-001)"
                    },
                    "note_text": {
                        "type": "string",
                        "description": "The context or insight to save (plain English, up to 4000 chars)"
                    },
                    "author": {
                        "type": "string",
                        "description": "Username of the person who shared the context"
                    }
                },
                "required": ["project_code", "note_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_project_notes",
            "description": (
                "Retrieve saved context notes for a project. "
                "Always call this before answering questions about a project — "
                "notes may contain crucial context not in the ELN database."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_code": {
                        "type": "string",
                        "description": "Project code to retrieve notes for"
                    }
                },
                "required": ["project_code"]
            }
        }
    }
]

NOTES_SYSTEM_PROMPT_ADDITION = """
## PROJECT NOTES — MEMORY CAPTURE

When a user shares context about a project that is NOT in the ELN database (e.g. vendor conversations, IP constraints, timeline pressures, external synthesis info, regulatory context), call update_project_notes immediately to save it. Do not ask — just save and confirm.

Always call get_project_notes first when the user asks about a specific project. Notes may contain crucial context that changes your analysis.

Format confirmation: "Noted for [PROJECT_CODE]: [one-line summary of what was saved]."

Notes are visible to all @covvalent.com users — do not save anything marked personal or confidential by the user.
"""


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


def foundry_request(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{FOUNDRY_ENDPOINT}/{path}?api-version={FOUNDRY_API_VER}"
    token = get_token()
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
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
    agent = foundry_request("GET", f"assistants/{AGENT_ID}")

    existing_tools = agent.get("tools", [])
    existing_names = {
        t["function"]["name"]
        for t in existing_tools
        if t.get("type") == "function" and "function" in t
    }

    added = []
    for tool in NEW_TOOLS:
        name = tool["function"]["name"]
        if name in existing_names:
            print(f"  Tool already registered: {name} (skip)")
        else:
            existing_tools.append(tool)
            added.append(name)

    current_prompt = agent.get("instructions", "")
    if "PROJECT NOTES" in current_prompt:
        print("  System prompt already contains PROJECT NOTES section (skip)")
        new_prompt = current_prompt
    else:
        new_prompt = current_prompt + NOTES_SYSTEM_PROMPT_ADDITION
        print("  Appending PROJECT NOTES section to system prompt")

    if not added and new_prompt == current_prompt:
        print("Agent is already up to date. Nothing to patch.")
        return

    print(f"  Adding tools: {added}")
    print("Patching agent …")
    updated = foundry_request("POST", f"assistants/{AGENT_ID}", {
        "tools":        existing_tools,
        "instructions": new_prompt,
        "model":        agent.get("model", "gpt-5-4"),
    })
    print(f"Done. Agent tools: {[t['function']['name'] for t in updated.get('tools', []) if t.get('type') == 'function']}")


if __name__ == "__main__":
    main()
