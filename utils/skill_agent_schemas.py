from __future__ import annotations

import json
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
                        "type": "string",
                        "description": "Shell command to execute. Can be a single string (e.g. 'echo hello') or a JSON array of strings (e.g. [\"echo\", \"hello\"]).",
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
    {
        "type": "function",
        "function": {
            "name": "export_file",
            "description": "Mark a file in the session directory as a final deliverable to be returned to the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path of the file to mark as final output.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "invalid",
            "description": "Called automatically when a tool call is invalid or uses an unknown tool name. Reports the error so the agent can self-correct.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Explanation of what went wrong with the tool call.",
                    }
                },
                "required": ["reason"],
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
        if key == "command" and not val:
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


def _build_tool_result_text(
    *,
    call_id: str,
    tool_name: str,
    result: dict[str, Any],
    is_error: bool = False,
    error_detail: str = "",
) -> str:
    """Build a user-visible text that carries tool result.

    Because some model providers (e.g. openai_api_compatible with qwen) fail
    when ``tool`` role messages are present, we embed the result in a plain
    ``user`` message.  The format is explicit so the LLM can correlate the
    result with the previous tool_call.
    """
    status = "error" if is_error else "success"
    attrs = f'id="{call_id or ""}" name="{tool_name}" status="{status}"'

    # Annotate returncode for bash commands
    if tool_name == "bash" and isinstance(result, dict) and result.get("returncode") is not None:
        attrs += f' returncode="{result["returncode"]}"'

    lines: list[str] = [f"<tool_result {attrs}>"]

    if is_error and error_detail:
        lines.append(f"<error>{error_detail}</error>")

    # Structured output for bash commands with stdout/stderr
    if tool_name == "bash" and isinstance(result, dict):
        stdout = str(result.get("stdout") or "")
        stderr = str(result.get("stderr") or "")
        if stdout:
            lines.append(f"<stdout_length>{len(stdout)} chars</stdout_length>")
            lines.append("<stdout>")
            lines.append(stdout[:4000])
            if len(stdout) > 4000:
                lines.append(f"... ({len(stdout) - 4000} more chars truncated)")
            lines.append("</stdout>")
        if stderr:
            lines.append("<stderr>")
            lines.append(stderr[:2000])
            if len(stderr) > 2000:
                lines.append(f"... ({len(stderr) - 2000} more chars truncated)")
            lines.append("</stderr>")
        if not stdout and not stderr and result.get("returncode") is not None:
            lines.append("<note>Command executed successfully with no output.</note>")
        if not stdout and not stderr and result.get("error"):
            lines.append(json.dumps(result, ensure_ascii=False, indent=2))
    elif tool_name == "skill" and isinstance(result, dict) and result.get("output"):
        # Skill already formatted as XML, output directly
        lines.append(str(result["output"]))
    else:
        lines.append(json.dumps(result, ensure_ascii=False, indent=2))

    lines.append("</tool_result>")
    lines.append("Continue the task based on the tool results above.")
    return "\n".join(lines)
