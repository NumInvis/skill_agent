from __future__ import annotations

from typing import Any

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "skill",
            "description": "Load a specialized skill that provides domain-specific instructions and workflows. Returns the full SKILL.md content and a list of adjacent files in the skill directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The name of the skill to load.",
                    }
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file. Provide skill_name to read from a skill directory; omit it to read from the session directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path of the file to read.",
                    },
                    "skill_name": {
                        "type": "string",
                        "description": "Optional. If provided, reads from skills_root/<skill_name>/path.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "default": 12000,
                        "description": "Maximum characters to read.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write text content to a file in the session directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path within the session directory.",
                    },
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a shell command. Use cwd='skill:<skill_name>' to run inside a skill directory. Omit cwd or use relative paths to run in the session directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Command and arguments as a list of strings.",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Optional working directory. Use 'skill:<skill_name>' to run in a skill directory.",
                    },
                },
                "required": ["command"],
            },
        },
    },
]


def _validate_tool_arguments(tool_name: str, arguments: Any) -> tuple[bool, str]:
    if not isinstance(arguments, dict):
        return False, "arguments must be an object (dict)"

    required: dict[str, list[str]] = {
        "skill": ["name"],
        "read_file": ["path"],
        "write_file": ["path", "content"],
        "bash": ["command"],
    }

    if tool_name not in required:
        return True, ""

    missing: list[str] = []
    for key in required[tool_name]:
        val = arguments.get(key)
        if val is None:
            missing.append(key)
            continue
        if isinstance(val, str) and not val.strip():
            missing.append(key)
            continue
        if key == "command" and (not isinstance(val, list) or not val):
            missing.append(key)
            continue

    if missing:
        return False, "Missing or empty required parameters: " + ", ".join(missing)
    return True, ""


def _tool_call_retry_prompt(tool_name: str, detail: str) -> str:
    return (
        f"Your tool call `{tool_name}` has invalid arguments: {detail}. "
        "Please retry strictly following the tool schema."
    )
