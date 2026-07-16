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
import re
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
                    },
                    "exp_number_full": {
                        "type": "string",
                        "description": "Optional. Set this when the note concerns one specific experiment, e.g. R&D/P013E00/2606/375. Leave unset for project-level or strategic notes."
                    },
                    "note_type": {
                        "type": "string",
                        "enum": ["decision", "data_point"],
                        "description": "'decision' for strategic/process context (route abandoned, project on hold, key learning). 'data_point' for a specific reported number or correction (a yield, purity, or other measured value not yet confirmed in ELN) — set this whenever exp_number_full is also set."
                    }
                },
                "required": ["project_code", "note_text"]
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
    },
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
            },
            "strict": False
        }
    },
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


def load_system_prompt_addition() -> str:
    """Load additions from prompts/system_prompt_patch.json.
    Extracts only the portion from PROJECT MEMORY onward so it can be
    appended to the already-stripped base instructions in main()."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    patch_path = os.path.join(script_dir, '..', 'prompts', 'system_prompt_patch.json')
    with open(patch_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, str):
        instructions = data
    elif isinstance(data, dict):
        instructions = ""
        for key in ('addition', 'content', 'instructions', 'text'):
            if key in data:
                instructions = data[key]
                break
        if not instructions:
            instructions = '\n\n'.join(v for v in data.values() if isinstance(v, str))
    else:
        instructions = str(data)
    # The JSON holds the full prompt (base + additions). Extract only the
    # additions portion so main() doesn't duplicate the base when appending.
    sentinel = '\n\n## PROJECT MEMORY'
    idx = instructions.find(sentinel)
    if idx != -1:
        return instructions[idx:]
    return instructions


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
    addition = load_system_prompt_addition()
    new_prompt = current_prompt + addition
    print("  Appending system prompt additions from system_prompt_patch.json")

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


if __name__ == "__main__":
    main()
