from __future__ import annotations

import os
from typing import Any

from utils.skill_agent_runtime import _AgentRuntime
from utils.tools import _guess_mime_type, _shorten_text


def _execute_tool_call(
    runtime: _AgentRuntime,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    session_dir: str,
    final_file_meta: dict[str, dict[str, str]],
) -> tuple[dict[str, Any], str | None]:
    result: dict[str, Any] = {"error": f"unknown tool: {tool_name}"}
    stderr_hint: str | None = None

    def _redact_path(text: str) -> str:
        s = str(text or "")
        for p in [session_dir, runtime.skills_root]:
            if p and isinstance(p, str):
                s = s.replace(p, "<REDACTED_PATH>")
                s = s.replace(p.replace("\\", "/"), "<REDACTED_PATH>")
        return s

    def _get_int_arg(args: dict, key: str, default: int) -> int:
        val = args.get(key)
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    if tool_name == "skill":
        result = runtime.get_skill_metadata(str(arguments.get("name") or ""))

    elif tool_name == "read_file":
        skill_name = str(arguments.get("skill_name") or "").strip()
        path = str(arguments.get("path") or "")
        if skill_name:
            result = runtime.read_skill_file(skill_name, path, _get_int_arg(arguments, "max_chars", 12000))
        else:
            result = runtime.read_file(path, _get_int_arg(arguments, "max_chars", 12000))

    elif tool_name == "write_file":
        result = runtime.write_file(
            str(arguments.get("path") or ""),
            str(arguments.get("content") or ""),
        )

    elif tool_name == "bash":
        command = arguments.get("command") if isinstance(arguments.get("command"), list) else []
        cwd = str(arguments.get("cwd") or "").strip()
        if cwd.startswith("skill:"):
            skill_name = cwd[6:].strip()
            result = runtime.run_skill_command(skill_name, command)
        else:
            result = runtime.run_command(command)
        if (
            isinstance(result, dict)
            and result.get("returncode") is not None
            and int(result.get("returncode") or 0) != 0
        ):
            stderr = str(result.get("stderr") or "").strip()
            if stderr:
                stderr_hint = "❌命令执行失败（stderr）：\n" + _shorten_text(_redact_path(stderr), 1200) + "\n"

    elif tool_name == "export_file":
        path = str(arguments.get("path") or "")
        result = runtime.export_file(path)
        out_name = os.path.basename(path) if path else ""
        if (
            isinstance(result, dict)
            and not result.get("error")
            and path
            and out_name
        ):
            final_file_meta[path] = {
                **(final_file_meta.get(path) or {}),
                "filename": out_name,
                "mime_type": _guess_mime_type(out_name),
            }

    return result, stderr_hint
