from __future__ import annotations

from typing import Any


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_skill_metadata",
            "description": "Read SKILL.md and metadata for a specified skill package",
            "parameters": {
                "type": "object",
                "properties": {"skill_name": {"type": "string"}},
                "required": ["skill_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_skill_files",
            "description": "List file structure within a specified skill package",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string"},
                    "max_depth": {"type": "integer", "default": 2},
                },
                "required": ["skill_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_skill_file",
            "description": "Read file content from a skill package",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string"},
                    "relative_path": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 12000},
                },
                "required": ["skill_name", "relative_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_skill_command",
            "description": "Execute command within skill package directory (restricted executables)",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string"},
                    "command": {"type": "array", "items": {"type": "string"}},
                    "cwd_relative": {"type": "string"},
                    "auto_install": {"type": "boolean", "default": False},
                },
                "required": ["skill_name", "command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_session_context",
            "description": "Get skill directory and temp directory info for this session",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_temp_file",
            "description": "Write text to temp session directory (relative path)",
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string", "minLength": 1},
                    "content": {"type": "string"},
                },
                "required": ["relative_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_temp_file",
            "description": "Read file content from temp session directory (relative path)",
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string", "minLength": 1},
                    "max_chars": {"type": "integer", "default": 12000},
                },
                "required": ["relative_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_temp_files",
            "description": "List file structure in temp session directory",
            "parameters": {
                "type": "object",
                "properties": {"max_depth": {"type": "integer", "default": 4}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_temp_command",
            "description": "Execute command within temp session directory (restricted executables)",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "array", "items": {"type": "string"}},
                    "cwd_relative": {"type": "string"},
                    "auto_install": {"type": "boolean", "default": False},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_temp_file",
            "description": "Mark temp session file as final deliverable (does not copy)",
            "parameters": {
                "type": "object",
                "properties": {
                    "temp_relative_path": {"type": "string", "minLength": 1},
                    "workspace_relative_path": {"type": "string", "minLength": 1},
                    "overwrite": {"type": "boolean", "default": False},
                },
                "required": ["temp_relative_path", "workspace_relative_path"],
            },
        },
    },
]


def _validate_tool_arguments(tool_name: str, arguments: Any) -> tuple[bool, str]:
    if not isinstance(arguments, dict):
        return False, "arguments must be an object (dict)"

    required: dict[str, list[str]] = {
        "get_skill_metadata": ["skill_name"],
        "list_skill_files": ["skill_name"],
        "read_skill_file": ["skill_name", "relative_path"],
        "run_skill_command": ["skill_name", "command"],
        "get_session_context": [],
        "write_temp_file": ["relative_path", "content"],
        "read_temp_file": ["relative_path"],
        "list_temp_files": [],
        "run_temp_command": ["command"],
        "export_temp_file": ["temp_relative_path", "workspace_relative_path"],
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
        "Please retry strictly following the tool schema (arguments must include all required fields and be non-empty)."
    )
