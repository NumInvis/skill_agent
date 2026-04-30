import re
import json
import os
import time
import uuid
import base64
import hashlib
from collections.abc import Generator
from typing import Any

from utils.tools import (
    _build_prompt_message_tools,
    _download_file_content,
    _extract_first_json_object,
    _extract_url_and_name,
    _guess_mime_type,
    _infer_ext_from_url,
    _list_dir,
    _parse_tool_call,
    _safe_filename,
    _safe_get,
    _safe_join,
    _shorten_text,
    _split_message_content,
)

from utils.skill_agent_constants import HISTORY_TRANSCRIPT_MAX_CHARS
from utils.skill_agent_debug import _dbg, _model_brief
from utils.skill_agent_exec import _cleanup_old_temp_sessions, _detect_skills_root
from utils.skill_agent_runtime import _AgentRuntime
from utils.skill_agent_schemas import TOOL_SCHEMAS, _tool_call_retry_prompt, _validate_tool_arguments
from utils.skill_agent_storage import (
    _append_history_turn,
    _get_history_storage_key,
    _get_resume_storage_key,
    _get_session_dir_storage_key,
    _storage_get_json,
    _storage_get_text,
    _storage_set_json,
    _storage_set_text,
)
from utils.skill_agent_uploads import _build_uploads_context
from utils.skill_agent_prompts import (
    SYSTEM_PROMPT_HEADER,
    ERR_SKILL_MD_REQUIRED,
    ERR_SKILL_FILES_REQUIRED,
    HINT_SKILL_MD_REQUIRED,
    HINT_SKILL_FILES_REQUIRED,
    TOOL_STATUS,
    UPLOADS_HEADER,
    MSG_NO_EXECUTABLE,
    ERR_MISSING_QUERY,
    ERR_FILE_URL,
    ERR_FILE_DOWNLOAD,
    ERR_FILE_SAVE,
    ERR_NO_SKILLS,
    ERR_LLM_DNS,
    ERR_LLM_FAILED,
    ERR_MODEL_NO_TOOLS,
    ERR_EMPTY_RESPONSE,
    ERR_EMPTY_REPEATED,
    ERR_MAX_STEPS,
    ERR_CMD_FAILED,
    MSG_FILES_GENERATED,
    MSG_FILES_NO_EXPORT,
    MSG_NO_OUTPUT,
    DEFAULT_SYSTEM_PROMPT,
)

from dify_plugin import Tool
from dify_plugin.entities.model.message import (
    AssistantPromptMessage,
    PromptMessageTool,
    SystemPromptMessage,
    ToolPromptMessage,
    UserPromptMessage,
)
from dify_plugin.entities.tool import ToolInvokeMessage


def _format_skills_index(skills_index: dict) -> str:
    """Format skill index as compact XML to reduce token usage."""
    skills = skills_index.get("skills") or []
    if not skills:
        return ERR_NO_SKILLS
    lines = []
    for s in skills:
        name = s.get("name") or ""
        desc = s.get("description") or ""
        if name:
            lines.append(f'<skill name="{name}">{desc}</skill>')
    return "\n".join(lines)


def _validate_skill_access(tool_name: str, arguments: dict, runtime: "_AgentRuntime") -> dict | None:
    """Check skill access prerequisites. Returns error dict or None if OK."""
    if tool_name not in {"list_skill_files", "read_skill_file", "run_skill_command"}:
        return None
    skill_name = str(arguments.get("skill_name") or "").strip()
    if not skill_name:
        return None
    if not runtime.has_skill_metadata(skill_name):
        return {"error": "skill_md_required", "skill_name": skill_name, "detail": ERR_SKILL_MD_REQUIRED}
    if tool_name == "run_skill_command" and not runtime.has_listed_skill_files(skill_name):
        return {"error": "skill_files_listing_required", "skill_name": skill_name, "detail": ERR_SKILL_FILES_REQUIRED}
    return None


def _skill_access_error_hint(tool_name: str, error: dict) -> str:
    """Generate user-facing hint for skill access errors."""
    skill_name = error.get("skill_name", "")
    if error.get("error") == "skill_md_required":
        return HINT_SKILL_MD_REQUIRED.format(tool_name=tool_name, skill_name=skill_name)
    if error.get("error") == "skill_files_listing_required":
        return HINT_SKILL_FILES_REQUIRED.format(tool_name=tool_name, skill_name=skill_name)
    return ""


def _get_tool_status_msg(tool_name: str, arguments: dict) -> str:
    """Generate tool execution status message."""
    tpl = TOOL_STATUS.get(tool_name)
    if not tpl:
        return ""
    try:
        return "✅" + tpl.format(**arguments)
    except KeyError:
        return "✅" + tpl


def _execute_tool_call(
    tool_name: str,
    arguments: dict,
    runtime: "_AgentRuntime",
    *,
    session_dir: str,
    storage: Any,
    resume_key: str,
    query: str,
    redact_fn: "Any",
) -> tuple[dict, str | None, bool]:
    """Execute tool call. Returns (result, forced_text, resume_saved)."""
    forced_text = None
    resume_saved = False

    if tool_name == "get_skill_metadata":
        return runtime.get_skill_metadata(str(arguments.get("skill_name") or "")), None, False
    if tool_name == "list_skill_files":
        return runtime.list_skill_files(
            str(arguments.get("skill_name") or ""),
            int(arguments.get("max_depth") or 2),
        ), None, False
    if tool_name == "read_skill_file":
        return runtime.read_skill_file(
            str(arguments.get("skill_name") or ""),
            str(arguments.get("relative_path") or ""),
            int(arguments.get("max_chars") or 12000),
        ), None, False
    if tool_name == "run_skill_command":
        result = runtime.run_skill_command(
            skill_name=str(arguments.get("skill_name") or ""),
            command=arguments.get("command") if isinstance(arguments.get("command"), list) else [],
            cwd_relative=str(arguments.get("cwd_relative")) if arguments.get("cwd_relative") else None,
            auto_install=bool(arguments.get("auto_install") or False),
        )
        if isinstance(result, dict) and result.get("returncode") is not None and int(result.get("returncode") or 0) != 0:
            stderr = str(result.get("stderr") or "").strip()
            if stderr:
                pass  # stderr handled by caller
        if isinstance(result, dict) and result.get("error") == "no_executable_found":
            skill = str(result.get("skill") or arguments.get("skill_name") or "")
            module = str(result.get("module") or "")
            forced_text = MSG_NO_EXECUTABLE.format(skill=skill, module=module)
            from utils.skill_agent_storage import _storage_set_json
            _storage_set_json(storage, resume_key, {
                "pending": True,
                "session_dir": session_dir,
                "original_query": query,
                "reason": "no_executable_found",
                "skill": skill,
                "module": module,
                "created_at": int(time.time()),
            })
            resume_saved = True
        return result, forced_text, resume_saved
    if tool_name == "get_session_context":
        return runtime.get_session_context(), None, False
    if tool_name == "write_temp_file":
        return runtime.write_temp_file(
            str(arguments.get("relative_path") or ""),
            str(arguments.get("content") or ""),
        ), None, False
    if tool_name == "read_temp_file":
        return runtime.read_temp_file(
            str(arguments.get("relative_path") or ""),
            int(arguments.get("max_chars") or 12000),
        ), None, False
    if tool_name == "list_temp_files":
        return runtime.list_temp_files(int(arguments.get("max_depth") or 4)), None, False
    if tool_name == "run_temp_command":
        return runtime.run_temp_command(
            command=arguments.get("command") if isinstance(arguments.get("command"), list) else [],
            cwd_relative=str(arguments.get("cwd_relative")) if arguments.get("cwd_relative") else None,
            auto_install=bool(arguments.get("auto_install") or False),
        ), None, False
    if tool_name == "export_temp_file":
        temp_rel = str(arguments.get("temp_relative_path") or "")
        workspace_rel = str(arguments.get("workspace_relative_path") or "")
        result = runtime.export_temp_file(
            temp_relative_path=temp_rel,
            workspace_relative_path=workspace_rel,
            overwrite=bool(arguments.get("overwrite") or False),
        )
        return result, None, False
    return {"error": f"unknown tool: {tool_name}"}, None, False


def _extract_export_meta(result: dict, tool_name: str, arguments: dict) -> dict | None:
    """Extract metadata from export_temp_file result."""
    if tool_name != "export_temp_file":
        return None
    temp_rel = str(arguments.get("temp_relative_path") or "")
    workspace_rel = str(arguments.get("workspace_relative_path") or "")
    out_name = os.path.basename(workspace_rel) if workspace_rel else ""
    if isinstance(result, dict) and not result.get("error") and temp_rel and out_name:
        return {"temp_rel": temp_rel, "filename": out_name, "mime_type": _guess_mime_type(out_name)}
    return None


class SkillAgentTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        model = tool_parameters.get("model") or getattr(getattr(self, "session", None), "model", None) or {}
        _dbg(f"INVOKE model={_shorten_text(model, 200)} params_keys={list(tool_parameters.keys())}")
        query = tool_parameters.get("query")
        max_steps = int(tool_parameters.get("max_steps") or 15)
        memory_turns = int(tool_parameters.get("memory_turns") or 12)
        history_turns = int(tool_parameters.get("history_turns") or 3)
        system_prompt = tool_parameters.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
        skills_root = _detect_skills_root(tool_parameters.get("skills_root"))

        if not query or not isinstance(query, str):
            yield self.create_text_message(f"❌{ERR_MISSING_QUERY}\n")
            return
        user_input = str(query)

        storage = self.session.storage
        resume_key = _get_resume_storage_key(self.session)
        history_key = _get_history_storage_key(self.session)
        session_dir_key = _get_session_dir_storage_key(self.session)
        resume_state = _storage_get_json(storage, resume_key)
        resume_pending = bool(resume_state.get("pending"))
        is_resuming = False

        plugin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        temp_root = os.path.join(plugin_root, "temp")
        os.makedirs(temp_root, exist_ok=True)
        persisted_session_dir = _storage_get_text(storage, session_dir_key).strip()
        if persisted_session_dir and os.path.isdir(persisted_session_dir):
            session_dir = persisted_session_dir
        else:
            session_dir = os.path.join(temp_root, f"dify-skill-{uuid.uuid4().hex[:8]}")
        resume_context = ""

        if resume_pending:
            candidate = str(resume_state.get("session_dir") or "").strip()
            if candidate and os.path.isdir(candidate):
                session_dir = candidate
                os.makedirs(session_dir, exist_ok=True)
                _storage_set_text(storage, session_dir_key, session_dir)
                original_query_for_resume = str(resume_state.get("original_query") or "").strip()
                if original_query_for_resume:
                    query = original_query_for_resume
                is_resuming = True
                _storage_set_json(storage, resume_key, None)
                reason = str(resume_state.get("reason") or "")
                skill = str(resume_state.get("skill") or "")
                resume_context = (
                    f"\n\n[Resume Context]\n"
                    f"The user previously authorized continuing in the temp session directory. "
                    f"Reason: {reason}. Skill: {skill}.\n"
                    f"Original query: {original_query_for_resume}\n"
                    f"Continue from intermediate artifacts in session_dir. "
                    f"If the user's message indicates they do NOT want to continue, "
                    f"acknowledge and stop gracefully.\n"
                )
            else:
                _storage_set_json(storage, resume_key, None)
        os.makedirs(session_dir, exist_ok=True)
        _storage_set_text(storage, session_dir_key, session_dir)
        if not is_resuming:
            _cleanup_old_temp_sessions(temp_root, keep=4, protect_dirs={session_dir})

        file_items: list[Any] = []
        files_param = tool_parameters.get("files")
        if isinstance(files_param, list):
            file_items = [x for x in files_param if x]
        elif files_param:
            file_items = [files_param]
        elif tool_parameters.get("file"):
            file_items = [tool_parameters.get("file")]

        uploads_context = ""
        if file_items:
            uploads_dir = _safe_join(session_dir, "uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            uploaded: list[dict[str, Any]] = []
            for item in file_items:
                url, name = _extract_url_and_name(item)
                if not url:
                    yield self.create_text_message(f"❌{ERR_FILE_URL}\n")
                    return
                try:
                    content = _download_file_content(str(url), timeout=45)
                except Exception as e:
                    yield self.create_text_message(f"❌{ERR_FILE_DOWNLOAD.format(error=str(e))}\n")
                    return
                ext = _infer_ext_from_url(str(url))
                filename = _safe_filename(str(name) if name else None, fallback_ext=ext)
                abs_path = os.path.join(uploads_dir, filename)
                try:
                    with open(abs_path, "wb") as f:
                        f.write(content)
                except Exception as e:
                    yield self.create_text_message(f"❌{ERR_FILE_SAVE.format(error=str(e))}\n")
                    return

                rel_path = f"uploads/{filename}"
                mime = None
                if isinstance(item, dict) and item.get("mime_type"):
                    mime = str(item.get("mime_type") or "").strip() or None
                if not mime:
                    try:
                        mime = _guess_mime_type(filename)
                    except Exception:
                        mime = None
                uploaded.append(
                    {
                        "relative_path": rel_path,
                        "bytes": len(content),
                        "mime_type": mime or "",
                        "filename": filename,
                        "source_url": str(url),
                    }
                )

            lines = UPLOADS_HEADER.copy()
            for f in uploaded:
                lines.append(
                    f"- {f.get('relative_path')} | mime={f.get('mime_type') or ''} | bytes={f.get('bytes') or 0} | filename={f.get('filename') or ''}"
                )
            uploads_context = "\n".join(lines) + "\n"
        else:
            uploads_dir = _safe_join(session_dir, "uploads")
            os.makedirs(uploads_dir, exist_ok=True)

        if not uploads_context:
            uploads_context = _build_uploads_context(session_dir)

        runtime = _AgentRuntime(
            skills_root=skills_root,
            session_dir=session_dir,
            max_steps=max_steps,
            memory_turns=memory_turns,
        )

        history_messages: list[Any] = []
        if history_turns > 0:
            history_state = _storage_get_json(storage, history_key)
            turns = history_state.get("turns")
            if isinstance(turns, list) and turns:
                picked: list[tuple[str, str]] = []
                for t in reversed(turns[-history_turns:]):
                    if not isinstance(t, dict):
                        continue
                    u = str(t.get("user") or "").strip()
                    a = str(t.get("assistant") or "").strip()
                    if not u and not a:
                        continue
                    picked.append((u, a))
                if picked:
                    acc: list[tuple[str, str]] = []
                    total = 0
                    for u, a in picked:
                        block_len = len(u) + len(a)
                        if total + block_len > HISTORY_TRANSCRIPT_MAX_CHARS and acc:
                            break
                        acc.append((u, a))
                        total += block_len
                        if total >= HISTORY_TRANSCRIPT_MAX_CHARS:
                            break
                    acc.reverse()
                    for u, a in acc:
                        if u:
                            history_messages.append(UserPromptMessage(content=u))
                        if a:
                            history_messages.append(AssistantPromptMessage(content=a))

        skills_index = runtime.load_skills_index()
        try:
            skills_count = len(skills_index.get("skills") or []) if isinstance(skills_index, dict) else 0
        except Exception:
            skills_count = 0
        _dbg(
            "start "
            + _model_brief(model)
            + f" session_dir={session_dir} skills_root={skills_root!s} skills_count={skills_count} "
            + f"query_len={len(query)}"
        )
        system_content = (
            system_prompt.strip()
            + SYSTEM_PROMPT_HEADER.format(
                session_dir=session_dir,
                skills_root=skills_root,
                uploads_context=uploads_context or "",
            )
            + _format_skills_index(skills_index)
            + (resume_context or "")
        )

        messages: list[Any] = [SystemPromptMessage(content=system_content)]
        if history_messages:
            messages.extend(history_messages)
        messages.append(UserPromptMessage(content=query))

        def compact() -> None:
            if memory_turns <= 0:
                return
            if len(messages) <= 2:
                return
            system_msg = messages[0]
            rest = messages[1:]
            user_turn_indices = [i for i, m in enumerate(rest) if isinstance(m, UserPromptMessage)]
            if len(user_turn_indices) <= memory_turns:
                return
            cut_idx = user_turn_indices[-memory_turns]
            messages[:] = [system_msg, *rest[cut_idx:]]

        final_text: str | None = None
        final_file_meta: dict[str, dict[str, str]] = {}
        empty_responses = 0
        saved_asset_fingerprints: set[str] = set()
        resume_saved = False
        final_text_already_streamed = False

        def stream_text_to_user(text: str, chunk_size: int = 8) -> Generator[ToolInvokeMessage]:
            s = (text or "").strip()
            if not s:
                return
            step = max(1, int(chunk_size))
            for i in range(0, len(s), step):
                yield self.create_text_message(s[i : i + step])

        def redact_user_visible_text(text: str) -> str:
            s = str(text or "")
            if not s:
                return s
            for p in [session_dir, skills_root]:
                if p and isinstance(p, str):
                    s = s.replace(p, "<REDACTED_PATH>")
                    s = s.replace(p.replace("\\", "/"), "<REDACTED_PATH>")
            s = re.sub(r"[A-Za-z]:\\[^\s\r\n\t\"']+", "<REDACTED_PATH>", s)
            s = re.sub(r"/[^\s\r\n\t\"']+", "<REDACTED_PATH>", s)
            return s

        def persist_llm_assets(parts: Any) -> list[str]:
            if not parts or not isinstance(parts, list):
                return []
            saved: list[str] = []
            out_dir = _safe_join(session_dir, "llm_assets")
            os.makedirs(out_dir, exist_ok=True)
            for i, item in enumerate(parts):
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type") or "")
                if item_type not in {"image", "document", "audio", "video"}:
                    continue
                mime = str(item.get("mime_type") or "")
                filename = str(item.get("filename") or "").strip()
                url = str(item.get("url") or item.get("data") or "").strip()
                b64 = str(item.get("base64_data") or "").strip()
                raw: bytes | None = None
                if b64:
                    try:
                        raw = base64.b64decode(b64, validate=False)
                    except Exception:
                        raw = None
                if raw is None and url.startswith("data:") and ";base64," in url:
                    try:
                        header, payload = url.split(";base64,", 1)
                        if not mime and header.startswith("data:"):
                            mime = header[5:]
                        raw = base64.b64decode(payload, validate=False)
                    except Exception:
                        raw = None
                if raw is None:
                    continue
                try:
                    fp = hashlib.sha1(raw).hexdigest()
                    key = f"{item_type}|{mime}|{fp}"
                except Exception:
                    key = f"{item_type}|{mime}|{len(raw)}"
                if key in saved_asset_fingerprints:
                    continue
                saved_asset_fingerprints.add(key)
                if not filename:
                    ext = ""
                    if mime:
                        if "png" in mime:
                            ext = ".png"
                        elif "jpeg" in mime or "jpg" in mime:
                            ext = ".jpg"
                        elif "pdf" in mime:
                            ext = ".pdf"
                        elif "json" in mime:
                            ext = ".json"
                        elif "text" in mime or "markdown" in mime:
                            ext = ".txt"
                    filename = f"{item_type}-{i+1}{ext or ''}"
                dst = _safe_join(out_dir, filename)
                if os.path.exists(dst):
                    base, ext = os.path.splitext(filename)
                    dst = _safe_join(out_dir, f"{base}-{fp[:8] if 'fp' in locals() else uuid.uuid4().hex[:8]}{ext}")
                try:
                    with open(dst, "wb") as f:
                        f.write(raw)
                    saved.append(os.path.relpath(dst, session_dir))
                except Exception:
                    continue
            return saved

        def invoke_llm_live(
            *, prompt_messages: list[Any], tools: list[Any] | None
        ) -> Generator[ToolInvokeMessage, None, tuple[str, list[Any], Any, int, bool]]:
            nontext_content: list[dict[str, Any]] = []
            tool_calls_all: list[Any] = []
            text_parts: list[str] = []
            chunks_count = 0
            streamed_any = False
            saw_tool_calls = False
            typing_chunk = 6
            emitted_prefix = False
            emitted_len = 0

            def emit_typing(text: str) -> Generator[ToolInvokeMessage, None, None]:
                nonlocal streamed_any
                if not text:
                    return
                tagged = "\n【🤖Skill_Agent】\n" + text.strip() + "\n\n"
                step = max(1, int(typing_chunk))
                for i in range(0, len(tagged), step):
                    yield self.create_text_message(tagged[i : i + step])
                    streamed_any = True

            def should_emit_user_text(text: str) -> bool:
                if not text:
                    return False
                s = str(text)
                stripped = s.lstrip()
                if stripped.startswith("{") and _extract_first_json_object(s) is None:
                    return False
                if stripped.startswith("```") and stripped.count("```") < 2:
                    return False
                json_text = _extract_first_json_object(text)
                if not json_text:
                    return True
                try:
                    obj = json.loads(json_text)
                except Exception:
                    return True
                if not isinstance(obj, dict):
                    return True
                t = obj.get("type")
                return t not in {"tool", "final"}

            try:
                try:
                    response = self.session.model.llm.invoke(
                        model_config=model,
                        prompt_messages=prompt_messages,
                        tools=tools,
                        stream=True,
                    )
                except TypeError:
                    _dbg("LLM does not support tools parameter, falling back to JSON protocol")
                    yield self.create_text_message(ERR_MODEL_NO_TOOLS)
                    tools = None
                    response = self.session.model.llm.invoke(
                        model_config=model,
                        prompt_messages=prompt_messages,
                        stream=True,
                    )

                if _safe_get(response, "message") is not None:
                    msg = _safe_get(response, "message") or {}
                    content = _safe_get(msg, "content")
                    text, parts = _split_message_content(content)
                    if parts:
                        nontext_content.extend(parts)
                    tool_calls = _safe_get(msg, "tool_calls") or []
                    if isinstance(tool_calls, list):
                        tool_calls_all.extend(tool_calls)
                        if tool_calls:
                            saw_tool_calls = True
                    if text:
                        text_parts.append(text)
                    combined_text = "".join(text_parts).strip()
                    if combined_text and not saw_tool_calls and should_emit_user_text(combined_text):
                        yield from emit_typing(combined_text)
                    return combined_text, tool_calls_all, nontext_content, chunks_count, streamed_any

                for chunk in response:
                    chunks_count += 1
                    delta = _safe_get(chunk, "delta") or {}
                    msg = _safe_get(delta, "message") or {}
                    content = _safe_get(msg, "content")
                    t, parts = _split_message_content(content)
                    if parts:
                        nontext_content.extend(parts)
                    tc = _safe_get(msg, "tool_calls") or []
                    if isinstance(tc, list) and tc:
                        tool_calls_all.extend(tc)
                        if not saw_tool_calls:
                            saw_tool_calls = True
                    if t:
                        text_parts.append(t)
                        combined_text_live = "".join(text_parts).strip()
                        if combined_text_live and not saw_tool_calls and should_emit_user_text(combined_text_live):
                            if not emitted_prefix:
                                yield self.create_text_message("\n【🤖Skill_Agent】\n")
                                emitted_prefix = True
                            new = combined_text_live[emitted_len:]
                            if new:
                                step = max(1, int(typing_chunk))
                                for i in range(0, len(new), step):
                                    yield self.create_text_message(new[i : i + step])
                                    streamed_any = True
                                emitted_len = len(combined_text_live)
                combined_text = "".join(text_parts).strip()
                if emitted_prefix:
                    yield self.create_text_message("\n\n")
                elif combined_text and not saw_tool_calls and should_emit_user_text(combined_text):
                    yield from emit_typing(combined_text)
                return combined_text, tool_calls_all, nontext_content, chunks_count, streamed_any
            except Exception as e:
                return "", [], {"error": "stream_parse_failed", "exception": str(e)}, chunks_count, streamed_any

        try:
            for step_idx in range(max_steps):
                compact()
                _dbg(f"step={step_idx+1}/{max_steps} messages={len(messages)}")
                try:
                    res_text, tool_calls, nontext, chunks, streamed_any = yield from invoke_llm_live(
                        prompt_messages=messages,
                        tools=_build_prompt_message_tools(TOOL_SCHEMAS, PromptMessageTool),
                    )
                except Exception as e:
                    msg = str(e)
                    if "NameResolutionError" in msg or "Failed to resolve" in msg:
                        yield self.create_text_message(ERR_LLM_DNS.format(error=msg))
                    else:
                        yield self.create_text_message(ERR_LLM_FAILED.format(error=msg))
                    return

                _dbg(
                    f"llm_return content_len={len(res_text)} tool_calls={len(tool_calls)} chunks={chunks} "
                    f"nontext={_shorten_text(nontext, 200) if nontext else ''}"
                )
                if nontext:
                    saved_assets = persist_llm_assets(nontext)
                    if saved_assets:
                        _dbg(f"nontext_assets_saved={len(saved_assets)} paths={_shorten_text(saved_assets, 300)}")
                if tool_calls:
                    empty_responses = 0
                    messages.append(AssistantPromptMessage(content=res_text or "", tool_calls=tool_calls))
                    forced_text: str | None = None
                    for tc in tool_calls:
                        call_id, name, arguments = _parse_tool_call(tc)
                        tool_name = str(name or "")
                        _dbg(f"tool_call name={tool_name} id={call_id!s} args={_shorten_text(arguments, 400)}")

                        ok_args, arg_detail = _validate_tool_arguments(tool_name, arguments)
                        if not ok_args:
                            result = {
                                "error": "invalid_tool_arguments",
                                "tool": tool_name,
                                "detail": arg_detail,
                                "got": arguments,
                            }
                            _dbg(f"tool_result name={tool_name} result={_shorten_text(result, 700)}")
                            messages.append(
                                ToolPromptMessage(
                                    tool_call_id=str(call_id or ""),
                                    name=tool_name,
                                    content=json.dumps(result, ensure_ascii=False),
                                )
                            )
                            messages.append(UserPromptMessage(content=_tool_call_retry_prompt(tool_name, arg_detail)))
                            continue

                        access_err = _validate_skill_access(tool_name, arguments, runtime)
                        if access_err:
                            _dbg(f"tool_result name={tool_name} result={_shorten_text(access_err, 700)}")
                            messages.append(ToolPromptMessage(
                                tool_call_id=str(call_id or ""),
                                name=tool_name,
                                content=json.dumps(access_err, ensure_ascii=False),
                            ))
                            messages.append(UserPromptMessage(content=_skill_access_error_hint(tool_name, access_err)))
                            continue

                        status_msg = _get_tool_status_msg(tool_name, arguments)
                        if status_msg:
                            yield self.create_text_message(status_msg + "\n")

                        result, forced_text, rs = _execute_tool_call(
                            tool_name, arguments, runtime,
                            session_dir=session_dir, storage=storage,
                            resume_key=resume_key, query=query, redact_fn=redact_user_visible_text,
                        )
                        if rs:
                            resume_saved = True

                        if tool_name == "run_skill_command" and isinstance(result, dict):
                            if result.get("returncode") is not None and int(result.get("returncode") or 0) != 0:
                                stderr = str(result.get("stderr") or "").strip()
                                if stderr:
                                    yield self.create_text_message(
                                        ERR_CMD_FAILED.format(stderr=_shorten_text(redact_user_visible_text(stderr), 1200)) + "\n"
                                    )
                        if tool_name == "run_temp_command" and isinstance(result, dict):
                            if result.get("returncode") is not None and int(result.get("returncode") or 0) != 0:
                                stderr = str(result.get("stderr") or "").strip()
                                if stderr:
                                    yield self.create_text_message(
                                        ERR_CMD_FAILED.format(stderr=_shorten_text(redact_user_visible_text(stderr), 1200)) + "\n"
                                    )
                        export_meta = _extract_export_meta(result, tool_name, arguments)
                        if export_meta:
                            final_file_meta[export_meta["temp_rel"]] = {
                                **(final_file_meta.get(export_meta["temp_rel"]) or {}),
                                "filename": export_meta["filename"],
                                "mime_type": export_meta["mime_type"],
                            }

                        _dbg(f"tool_result name={tool_name} result={_shorten_text(result, 700)}")
                        messages.append(
                            ToolPromptMessage(
                                tool_call_id=str(call_id or ""),
                                name=tool_name,
                                content=json.dumps(result, ensure_ascii=False),
                            )
                        )
                    if forced_text:
                        final_text = forced_text
                        break
                    if step_idx >= max_steps - 1:
                        try:
                            has_files = any(
                                e.get("type") == "file"
                                for e in _list_dir(session_dir, max_depth=2)
                                if isinstance(e, dict)
                            )
                        except Exception:
                            has_files = False
                        if final_file_meta or has_files:
                            final_text = MSG_FILES_GENERATED
                            break
                    continue

                json_text = _extract_first_json_object(res_text)
                action: dict[str, Any] | None = None
                if json_text:
                    try:
                        action = json.loads(json_text)
                    except Exception:
                        action = None
                _dbg(f"json_protocol detected={bool(action)} snippet={_shorten_text(json_text or '', 200)}")

                if not res_text and not action and not nontext:
                    empty_responses += 1
                    _dbg(f"empty_response_count={empty_responses}")
                    if empty_responses < 3:
                        messages.append(
                            UserPromptMessage(content=ERR_EMPTY_RESPONSE)
                        )
                        continue
                    final_text = ERR_EMPTY_REPEATED
                    break

                if not action or action.get("type") == "final":
                    if action and action.get("type") == "final":
                        final_text = str(action.get("content") or "")
                        _dbg(f"final_json content_len={len(final_text)}")
                    else:
                        final_text = res_text
                        _dbg(f"final_text content_len={len(final_text)}")
                        if streamed_any and final_text:
                            final_text_already_streamed = True
                    break

                if action.get("type") != "tool":
                    final_text = res_text
                    _dbg(f"final_non_tool type={action.get('type')!s} content_len={len(final_text)}")
                    break

                name = str(action.get("name") or "")
                arguments = action.get("arguments") or {}
                if not isinstance(arguments, dict):
                    arguments = {}

                ok_args, arg_detail = _validate_tool_arguments(name, arguments)
                if not ok_args:
                    messages.append(UserPromptMessage(content=_tool_call_retry_prompt(name, arg_detail)))
                    result = {
                        "error": "invalid_tool_arguments",
                        "tool": name,
                        "detail": arg_detail,
                        "got": arguments,
                    }
                    _dbg(f"json_tool_result name={name} result={_shorten_text(result, 700)}")
                    messages.append(
                        AssistantPromptMessage(
                            content="TOOL_RESULT\n" + json.dumps({"name": name, "result": result}, ensure_ascii=False)
                        )
                    )
                    continue

                access_err = _validate_skill_access(name, arguments, runtime)
                if access_err:
                    messages.append(UserPromptMessage(content=_skill_access_error_hint(name, access_err)))
                    _dbg(f"json_tool_result name={name} result={_shorten_text(access_err, 700)}")
                    messages.append(AssistantPromptMessage(
                        content="TOOL_RESULT\n" + json.dumps({"name": name, "result": access_err}, ensure_ascii=False)
                    ))
                    continue

                _dbg(f"json_tool name={name} args={_shorten_text(arguments, 400)}")
                messages.append(AssistantPromptMessage(content=json.dumps(action, ensure_ascii=False)))

                status_msg = _get_tool_status_msg(name, arguments)
                if status_msg:
                    yield self.create_text_message(status_msg + "\n")

                result, forced_text, rs = _execute_tool_call(
                    name, arguments, runtime,
                    session_dir=session_dir, storage=storage,
                    resume_key=resume_key, query=query, redact_fn=redact_user_visible_text,
                )
                if rs:
                    resume_saved = True

                export_meta = _extract_export_meta(result, name, arguments)
                if export_meta:
                    final_file_meta[export_meta["temp_rel"]] = {
                        **(final_file_meta.get(export_meta["temp_rel"]) or {}),
                        "filename": export_meta["filename"],
                        "mime_type": export_meta["mime_type"],
                    }

                _dbg(f"json_tool_result name={name} result={_shorten_text(result, 700)}")
                messages.append(
                    AssistantPromptMessage(
                        content="TOOL_RESULT\n" + json.dumps({"name": name, "result": result}, ensure_ascii=False)
                    )
                )
            else:
                try:
                    has_files = any(
                        e.get("type") == "file" for e in _list_dir(session_dir, max_depth=2) if isinstance(e, dict)
                    )
                except Exception:
                    has_files = False
                if final_file_meta or has_files:
                    final_text = MSG_FILES_GENERATED
                else:
                    final_text = ERR_MAX_STEPS.format(max_steps=max_steps)
        finally:
            if not resume_saved and not is_resuming and resume_pending:
                _storage_set_json(storage, resume_key, None)

            files_to_send: list[tuple[str, str, str, str]] = []
            try:
                for rel, meta_override in (final_file_meta or {}).items():
                    if not rel or not isinstance(rel, str):
                        continue
                    rel_norm = rel.replace("\\", "/").lstrip("/")
                    if not rel_norm:
                        continue
                    try:
                        path = _safe_join(session_dir, rel_norm)
                    except Exception:
                        continue
                    if not os.path.isfile(path):
                        continue
                    filename = os.path.basename(rel_norm)
                    out_name = (meta_override.get("filename") if isinstance(meta_override, dict) else None) or filename
                    mime_type = (meta_override.get("mime_type") if isinstance(meta_override, dict) else None) or _guess_mime_type(out_name or filename)
                    files_to_send.append((rel_norm, path, mime_type, out_name))
            except Exception:
                files_to_send = []

            has_any_files = False
            try:
                temp_entries = _list_dir(session_dir, max_depth=10)
                has_any_files = any(e.get("type") == "file" for e in temp_entries if isinstance(e, dict))
            except Exception:
                has_any_files = False

            assistant_text_for_history = ""
            if final_text and final_text.strip():
                if not files_to_send and final_text.strip() == MSG_FILES_GENERATED:
                    final_text = MSG_FILES_NO_EXPORT
                assistant_text_for_history = final_text.strip()
                _append_history_turn(
                    storage,
                    history_key=history_key,
                    user_text=user_input,
                    assistant_text=assistant_text_for_history,
                )
                if not final_text_already_streamed:
                    yield from stream_text_to_user(final_text)
            elif files_to_send:
                assistant_text_for_history = MSG_FILES_GENERATED
                _append_history_turn(
                    storage,
                    history_key=history_key,
                    user_text=user_input,
                    assistant_text=assistant_text_for_history,
                )
                yield from stream_text_to_user(MSG_FILES_GENERATED)
            elif has_any_files:
                assistant_text_for_history = MSG_FILES_NO_EXPORT
                _append_history_turn(
                    storage,
                    history_key=history_key,
                    user_text=user_input,
                    assistant_text=assistant_text_for_history,
                )
                yield from stream_text_to_user(MSG_FILES_NO_EXPORT)
            else:
                assistant_text_for_history = MSG_NO_OUTPUT
                _append_history_turn(
                    storage,
                    history_key=history_key,
                    user_text=user_input,
                    assistant_text=assistant_text_for_history,
                )
                yield from stream_text_to_user(MSG_NO_OUTPUT)

            yielded: set[str] = set()
            yielded_fingerprints: set[str] = set()
            for rel, path, mime_type, out_name in files_to_send:
                if rel in yielded:
                    continue
                yielded.add(rel)
                try:
                    with open(path, "rb") as fp:
                        content = fp.read()
                    try:
                        content_fp = hashlib.sha1(content).hexdigest()
                    except Exception:
                        content_fp = str(len(content))
                    fingerprint_key = f"{out_name}|{mime_type}|{content_fp}"
                    if fingerprint_key in yielded_fingerprints:
                        continue
                    yielded_fingerprints.add(fingerprint_key)
                    yield self.create_blob_message(blob=content, meta={"mime_type": mime_type, "filename": out_name})
                except Exception:
                    continue
            _dbg(f"temp_retained session_dir={session_dir}")
