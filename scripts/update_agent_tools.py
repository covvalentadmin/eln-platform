"""
scripts/update_agent_tools.py — AIE-404
Adds update_project_notes and get_project_notes tools to the Foundry agent
and appends the PROJECT MEMORY section to the agent system prompt.

Usage (Azure Cloud Shell):
    cd ~/eln-api
    python scripts/update_agent_tools.py

Requires env vars (or falls back to hardcoded defaults):
    FOUNDRY_ENDPOINT, FOUNDRY_API_VERSION, AGENT_ID
Azure CLI must be logged in (az login / managed identity).
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

NEW_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "update_project_notes",
            "description": (
                "Save a project insight or decision to persistent memory. "
                "Call when user shares context not in ELN: final process decisions, "
                "abandoned routes, key learnings, next step plans."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_code": {
                        "type": "string"
                    },
                    "note_text": {
                        "type": "string",
                        "description": "The insight to capture, written as a clear factual statement"
                    },
                    "author": {
                        "type": "string"
                    }
                },
                "required": ["project_code", "note_text", "author"]
            },
            "strict": False
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_project_notes",
            "description": (
                "Retrieve all saved project notes and context for a project. "
                "Call at the start of any project query to check for captured insights."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_code": {
                        "type": "string"
                    }
                },
                "required": ["project_code"]
            },
            "strict": False
        }
    }
]

SYSTEM_PROMPT_ADDITION = """

## PROJECT MEMORY — CAPTURED INSIGHTS

When a user shares context about a project that is NOT in the ELN experiment records — such as:
- "these experiments constitute the final process"
- "we decided to abandon X route"
- "for next steps we are considering Y chemistry"
- "the key insight from this campaign was Z"
- "this project is on hold because..."

You MUST:
1. Confirm: "I'll capture this as a project note for [project_code]: [one-line paraphrase of what you understood]"
2. Call update_project_notes with {project_code, note_text: the insight as a clear statement, author: user login or "unknown"}
3. Confirm: "Saved to [project_code] project memory. This will appear in all future reports and queries."

When answering ANY query about a specific project, ALWAYS call get_project_notes({project_code}) first to check for captured context. Incorporate any notes into your response naturally — cite them as "Project notes:" before the note content.

Notes are visible to all Covvalent users. Treat them as authoritative project context."""


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


def foundry_request(method: str, path: str, body=None) -> dict:
    url   = f"{FOUNDRY_ENDPOINT}/{path}?api-version={FOUNDRY_API_VER}"
    token = get_token()
    data  = json.dumps(body).encode() if body else None
    req   = urllib.request.Request(
        url, data=data, method=method,
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
            print(f"  Replacing existing tool: {name}")
            existing_tools = [t for t in existing_tools
                              if not (t.get("type") == "function" and
                                      t.get("function", {}).get("name") == name)]
        else:
            print(f"  Adding new tool: {name}")
        existing_tools.append(tool)
        added.append(name)

    current_prompt = agent.get("instructions", "")
    if "PROJECT MEMORY" in current_prompt:
        print("  System prompt already contains PROJECT MEMORY section — replacing …")
        # Remove old section (from ## PROJECT MEMORY to end or next ##)
        current_prompt = re.sub(
            r"\n## PROJECT MEMORY.*",
            "",
            current_prompt,
            flags=re.DOTALL
        )
    new_prompt = current_prompt + SYSTEM_PROMPT_ADDITION
    print("  Appending PROJECT MEMORY section to system prompt")

    print(f"  Tools to register: {added}")
    print("Patching agent …")
    updated = foundry_request("POST", f"assistants/{AGENT_ID}", {
        "tools":        existing_tools,
        "instructions": new_prompt,
        "model":        agent.get("model", "gpt-5-4"),
    })

    registered = [
        t["function"]["name"]
        for t in updated.get("tools", [])
        if t.get("type") == "function"
    ]
    print(f"Done. Registered tools: {registered}")


import re

if __name__ == "__main__":
    main()
