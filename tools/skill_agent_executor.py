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
    """
    统一执行工具调用，消除 Function Call 与 JSON Protocol 的重复逻辑。

    Returns:
        result: 工具执行结果 dict
        stderr_hint: 如果命令执行失败有 stderr，返回给用户看的提示文本；否则 None
    """
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

    if tool_name == "get_skill_metadata":
        result = runtime.get_skill_metadata(str(arguments.get("skill_name") or ""))

    elif tool_name == "list_skill_files":
        result = runtime.list_skill_files(
            str(arguments.get("skill_name") or ""),
            _get_int_arg(arguments, "max_depth", 2),
        )

    elif tool_name == "read_skill_file":
        result = runtime.read_skill_file(
            str(arguments.get("skill_name") or ""),
            str(arguments.get("relative_path") or ""),
            _get_int_arg(arguments, "max_chars", 12000),
        )

    elif tool_name == "run_skill_command":
        result = runtime.run_skill_command(
            skill_name=str(arguments.get("skill_name") or ""),
            command=arguments.get("command") if isinstance(arguments.get("command"), list) else [],
            cwd_relative=(str(arguments.get("cwd_relative")) if arguments.get("cwd_relative") else None),
            auto_install=bool(arguments.get("auto_install") or False),
        )
        if (
            isinstance(result, dict)
            and result.get("returncode") is not None
            and int(result.get("returncode") or 0) != 0
        ):
            stderr = str(result.get("stderr") or "").strip()
            if stderr:
                stderr_hint = "❌命令执行失败（stderr）：\n" + _shorten_text(_redact_path(stderr), 1200) + "\n"

    elif tool_name == "get_session_context":
        result = runtime.get_session_context()

    elif tool_name == "write_temp_file":
        result = runtime.write_temp_file(
            str(arguments.get("relative_path") or ""),
            str(arguments.get("content") or ""),
        )

    elif tool_name == "read_temp_file":
        result = runtime.read_temp_file(
            str(arguments.get("relative_path") or ""),
            _get_int_arg(arguments, "max_chars", 12000),
        )

    elif tool_name == "list_temp_files":
        result = runtime.list_temp_files(_get_int_arg(arguments, "max_depth", 4))

    elif tool_name == "run_temp_command":
        result = runtime.run_temp_command(
            command=arguments.get("command") if isinstance(arguments.get("command"), list) else [],
            cwd_relative=(str(arguments.get("cwd_relative")) if arguments.get("cwd_relative") else None),
            auto_install=bool(arguments.get("auto_install") or False),
        )
        if (
            isinstance(result, dict)
            and result.get("returncode") is not None
            and int(result.get("returncode") or 0) != 0
        ):
            stderr = str(result.get("stderr") or "").strip()
            if stderr:
                stderr_hint = "❌命令执行失败（stderr）：\n" + _shorten_text(_redact_path(stderr), 1200) + "\n"

    elif tool_name == "export_temp_file":
        temp_rel = str(arguments.get("temp_relative_path") or "")
        workspace_rel = str(arguments.get("workspace_relative_path") or "")
        result = runtime.export_temp_file(
            temp_relative_path=temp_rel,
            workspace_relative_path=workspace_rel,
            overwrite=bool(arguments.get("overwrite") or False),
        )
        out_name = os.path.basename(workspace_rel) if workspace_rel else ""
        if (
            isinstance(result, dict)
            and not result.get("error")
            and temp_rel
            and out_name
        ):
            final_file_meta[temp_rel] = {
                **(final_file_meta.get(temp_rel) or {}),
                "filename": out_name,
                "mime_type": _guess_mime_type(out_name),
            }

    return result, stderr_hint
