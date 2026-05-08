import re
import json
import os
import uuid
import base64
import hashlib
from collections.abc import Generator
from typing import Any

from utils.tools import (
    _build_prompt_message_tools,
    _download_file_content,
    _extract_first_json_object,
    _extract_json_tool_calls_from_text,
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

from utils.skill_agent_debug import _dbg, _model_brief
from utils.skill_agent_exec import _detect_skills_root
from utils.skill_agent_runtime import _AgentRuntime
from utils.skill_agent_schemas import TOOL_SCHEMAS, _build_tool_result_text, _validate_tool_arguments
from utils.skill_agent_uploads import _build_uploads_context

from dify_plugin import Tool
from dify_plugin.entities.model.message import (
    AssistantPromptMessage,
    PromptMessageTool,
    SystemPromptMessage,
    UserPromptMessage,
)
from dify_plugin.entities.tool import ToolInvokeMessage


class SkillAgentTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        model = tool_parameters.get("model") or getattr(getattr(self, "session", None), "model", None) or {}
        query = tool_parameters.get("query")

        def _get_int(params: dict, key: str, default: int) -> int:
            val = params.get(key)
            if val is None:
                return default
            try:
                return int(val)
            except (ValueError, TypeError):
                return default

        max_steps = _get_int(tool_parameters, "max_steps", 15)
        skills_root = _detect_skills_root(tool_parameters.get("skills_root"))

        if not query or not isinstance(query, str):
            yield self.create_text_message("❌缺少 query 参数\n")
            return
        user_input = str(query)

        plugin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        temp_root = os.path.join(plugin_root, "temp")
        os.makedirs(temp_root, exist_ok=True)
        session_dir = os.path.join(temp_root, f"dify-skill-{uuid.uuid4().hex[:8]}-")
        os.makedirs(session_dir, exist_ok=True)

        file_items: list[Any] = []
        files_param = tool_parameters.get("files")
        if isinstance(files_param, list):
            file_items = [x for x in files_param if x]
        elif files_param:
            file_items = [files_param]
        elif tool_parameters.get("file"):
            file_items = [tool_parameters.get("file")]

        uploads_dir = _safe_join(session_dir, "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        if file_items:
            for item in file_items:
                url, name = _extract_url_and_name(item)
                if not url:
                    yield self.create_text_message("❌未能获取上传文件 URL（files[i].url）。\n")
                    return
                try:
                    download_url = str(url).replace("http://api:5001", "http://127.0.0.1:5001")
                    content = _download_file_content(download_url, timeout=45)
                except Exception as e:
                    yield self.create_text_message(f"❌文件下载失败：{str(e)}\n")
                    return
                ext = _infer_ext_from_url(str(url))
                filename = _safe_filename(str(name) if name else None, fallback_ext=ext)
                abs_path = os.path.join(uploads_dir, filename)
                try:
                    with open(abs_path, "wb") as f:
                        f.write(content)
                except Exception as e:
                    yield self.create_text_message(f"❌保存上传文件失败：{str(e)}\n")
                    return

        uploads_context = _build_uploads_context(session_dir)

        runtime = _AgentRuntime(
            skills_root=skills_root,
            session_dir=session_dir,
        )

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

        system_content = self._build_system_prompt(
            session_dir=session_dir,
            skills_root=skills_root,
            skills_index=skills_index,
            uploads_context=uploads_context,
        )

        messages: list[Any] = [SystemPromptMessage(content=system_content)]
        messages.append(UserPromptMessage(content=query))

        final_text: str | None = None
        final_file_meta: dict[str, dict[str, str]] = {}
        empty_responses = 0
        saved_asset_fingerprints: set[str] = set()
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
                    fp = hashlib.sha256(raw).hexdigest()
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
                tagged = "\n【🤖Agent处理】\n" + text.strip() + "\n\n"
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
                # 检测 {"name": "...", "arguments": {...}} 工具 JSON 格式
                if "name" in obj and "arguments" in obj and isinstance(obj.get("name"), str):
                    known_tools = {"skill", "read_file", "write_file", "bash", "export_file", "invalid"}
                    if obj["name"] in known_tools:
                        return False
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
                except TypeError as _e:
                    if "tools" not in str(_e).lower():
                        raise
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
                    if combined_text and not saw_tool_calls:
                        json_tool_calls = _extract_json_tool_calls_from_text(combined_text)
                        if json_tool_calls:
                            tool_calls_all.extend(json_tool_calls)
                            saw_tool_calls = True
                    if combined_text and not saw_tool_calls and should_emit_user_text(combined_text):
                        yield from emit_typing(combined_text)
                    return combined_text, tool_calls_all, nontext_content, chunks_count, streamed_any

                for chunk in response:
                    chunks_count += 1
                    delta = _safe_get(chunk, "delta") or {}
                    msg = _safe_get(delta, "message") or {}
                    content = _safe_get(msg, "content")
                    tc = _safe_get(msg, "tool_calls") or []

                    # 诊断日志：打印 chunk 结构（帮助定位原生 function call 问题）
                    if chunks_count <= 3 or (isinstance(tc, list) and tc):
                        chunk_type = type(chunk).__name__
                        delta_type = type(delta).__name__
                        msg_type = type(msg).__name__
                        tc_len = len(tc) if isinstance(tc, list) else "N/A"
                        content_preview = _shorten_text(str(content)[:80], 80) if content else "None"
                        _dbg(
                            f"chunk#{chunks_count} type={chunk_type} delta={delta_type} msg={msg_type} "
                            f"content_preview={content_preview} tool_calls_len={tc_len}"
                        )

                    t, parts = _split_message_content(content)
                    if parts:
                        nontext_content.extend(parts)
                    if isinstance(tc, list) and tc:
                        tool_calls_all.extend(tc)
                        if not saw_tool_calls:
                            saw_tool_calls = True
                    if t:
                        text_parts.append(t)
                        combined_text_live = "".join(text_parts).strip()
                        if combined_text_live and not saw_tool_calls and should_emit_user_text(combined_text_live):
                            if not emitted_prefix:
                                yield self.create_text_message("\n【🤖Agent处理】\n")
                                emitted_prefix = True
                            new = combined_text_live[emitted_len:]
                            if new:
                                step = max(1, int(typing_chunk))
                                for i in range(0, len(new), step):
                                    yield self.create_text_message(new[i : i + step])
                                    streamed_any = True
                                emitted_len = len(combined_text_live)
                combined_text = "".join(text_parts).strip()
                if combined_text and not saw_tool_calls:
                    json_tool_calls = _extract_json_tool_calls_from_text(combined_text)
                    if json_tool_calls:
                        tool_calls_all.extend(json_tool_calls)
                        saw_tool_calls = True
                if emitted_prefix:
                    yield self.create_text_message("\n\n")
                elif combined_text and not saw_tool_calls and should_emit_user_text(combined_text):
                    yield from emit_typing(combined_text)
                return combined_text, tool_calls_all, nontext_content, chunks_count, streamed_any
            except Exception as e:
                return "", [], {"error": "stream_parse_failed", "exception": str(e)}, chunks_count, streamed_any

        try:
            for step_idx in range(max_steps):
                _dbg(f"step={step_idx+1}/{max_steps} messages={len(messages)}")
                try:
                    res_text, tool_calls, nontext, chunks, streamed_any = yield from invoke_llm_live(
                        prompt_messages=messages,
                        tools=_build_prompt_message_tools(TOOL_SCHEMAS, PromptMessageTool),
                    )
                except Exception as e:
                    msg = str(e)
                    if "NameResolutionError" in msg or "Failed to resolve" in msg:
                        yield self.create_text_message(
                            "❌ LLM 调用失败：无法解析模型服务域名（DNS/网络问题）。\n"
                            "当前报错信息：\n"
                            + msg
                            + "\n\n请检查：\n"
                            + "1) 运行插件的环境是否能访问公网/是否需要代理\n"
                            + "2) DNS 是否可用\n"
                            + "3) Dify 的模型供应商网络出站是否被限制\n"
                        )
                    else:
                        yield self.create_text_message("❌ LLM 调用失败：\n" + msg)
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
                                UserPromptMessage(
                                    content=_build_tool_result_text(
                                        call_id=call_id, tool_name=tool_name,
                                        result=result, is_error=True,
                                        error_detail=arg_detail,
                                    )
                                )
                            )
                            continue

                        if tool_name == "skill":
                            yield self.create_text_message(
                                f"✅正在加载技能《{str(arguments.get('name') or '')}》…\n"
                            )
                        elif tool_name == "read_file":
                            skill_name = str(arguments.get("skill_name") or "")
                            path = str(arguments.get("path") or "")
                            if skill_name:
                                yield self.create_text_message(
                                    f"✅正在读取技能《{skill_name}》文件：{path}…\n"
                                )
                            else:
                                yield self.create_text_message(f"✅正在读取文件：{path}…\n")
                        elif tool_name == "write_file":
                            yield self.create_text_message(
                                f"✅正在写入文件：{str(arguments.get('path') or '')}…\n"
                            )
                        elif tool_name == "bash":
                            yield self.create_text_message("✅正在执行命令…\n")
                        elif tool_name == "export_file":
                            yield self.create_text_message(
                                f"✅正在标记交付文件：{str(arguments.get('path') or '')}…\n"
                            )

                        from tools.skill_agent_executor import _execute_tool_call

                        result, stderr_hint = _execute_tool_call(
                            runtime, tool_name, arguments,
                            session_dir=session_dir,
                            final_file_meta=final_file_meta,
                        )
                        if stderr_hint:
                            yield self.create_text_message(stderr_hint)

                        # 工具调用容错修复（大小写不敏感匹配）
                        if isinstance(result, dict) and str(result.get("error") or "").startswith("unknown tool"):
                            known_names = [str(s.get("function", {}).get("name", "")) for s in TOOL_SCHEMAS]
                            matched = None
                            for known in known_names:
                                if known and tool_name.lower() == known.lower():
                                    matched = known
                                    break
                            if matched and matched != tool_name:
                                _dbg(f"tool_repair '{tool_name}' -> '{matched}'")
                                tool_name = matched
                                result, stderr_hint = _execute_tool_call(
                                    runtime, tool_name, arguments,
                                    session_dir=session_dir,
                                    final_file_meta=final_file_meta,
                                )
                                if stderr_hint:
                                    yield self.create_text_message(stderr_hint)
                            elif not matched:
                                available = ", ".join(n for n in known_names if n)
                                result = {
                                    "error": "invalid_tool_call",
                                    "tool": tool_name,
                                    "reason": f"Unknown tool '{tool_name}'. Available tools: {available}",
                                }
                                _dbg(f"tool_invalid name={tool_name} available={available}")

                        _dbg(f"tool_result name={tool_name} result={_shorten_text(result, 700)}")
                        messages.append(
                            UserPromptMessage(
                                content=_build_tool_result_text(
                                    call_id=call_id, tool_name=tool_name,
                                    result=result, is_error=False,
                                )
                            )
                        )
                    continue

                if not res_text:
                    empty_responses += 1
                    _dbg(f"empty_response_count={empty_responses}")
                    if empty_responses < 3:
                        messages.append(
                            UserPromptMessage(
                                content="你刚才没有输出任何内容。请继续完成任务：调用工具或给出最终答案。"
                            )
                        )
                        continue
                    final_text = "模型连续返回空响应，未生成任何结果。"
                    break

                final_text = res_text
                _dbg(f"final_text content_len={len(final_text)}")
                if streamed_any and final_text:
                    final_text_already_streamed = True
                break
            else:
                try:
                    has_files = any(
                        e.get("type") == "file"
                        for e in _list_dir(session_dir, max_depth=2)
                        if isinstance(e, dict)
                    )
                except Exception:
                    has_files = False
                if final_file_meta or has_files:
                    final_text = "已生成文件。"
                else:
                    final_text = f"❌超过最大执行轮数 max_steps={max_steps}，仍未得到最终结果"
        finally:
            temp_files_text = ""
            try:
                temp_entries = _list_dir(session_dir, max_depth=10)
                rel_paths = [
                    str(e.get("relative_path"))
                    for e in temp_entries
                    if e.get("type") == "file" and isinstance(e.get("relative_path"), str)
                ]
                if rel_paths:
                    temp_files_text = "\n\n[temp_files]\n" + "\n".join(rel_paths)
                _dbg(f"temp_files_count={len(rel_paths)}")
            except Exception:
                temp_files_text = ""

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
                if not files_to_send and final_text.strip() == "已生成文件。":
                    final_text = "已生成中间文件，但未调用 export_file 标记交付文件。"
                assistant_text_for_history = final_text.strip()
                if not final_text_already_streamed:
                    yield from stream_text_to_user(final_text)
            elif files_to_send:
                assistant_text_for_history = "已生成文件。"
                yield from stream_text_to_user("已生成文件。")
            elif has_any_files:
                assistant_text_for_history = "已生成中间文件，但未调用 export_file 标记交付文件。"
                yield from stream_text_to_user("已生成中间文件，但未调用 export_file 标记交付文件。")
            else:
                assistant_text_for_history = "未生成任何文本或文件输出。"
                yield from stream_text_to_user("未生成任何文本或文件输出。")

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
                        content_fp = hashlib.sha256(content).hexdigest()
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

    def _build_system_prompt(
        self,
        *,
        session_dir: str,
        skills_root: str | None,
        skills_index: dict[str, Any],
        uploads_context: str,
    ) -> str:
        lines: list[str] = [
            "你是一个使用 Skills 文件夹作为工具箱的通用 Agent。",
            "",
            "[会话路径]",
            f"- session_dir: {session_dir}",
            f"- skills_root: {skills_root}",
            "",
            "Skills 为特定任务提供专门的指令和工作流。",
            "当任务匹配某个 skill 的描述时，使用 skill tool 加载它。",
            "加载后按 skill 的说明执行任务。",
            "只有调用 export_file 标记的文件才会作为最终交付文件返回给用户。",
            "",
            _fmt_skills_xml(skills_index),
            "",
            "可用动作：",
            "- skill(name): 加载指定 skill，返回 SKILL.md 内容和文件列表",
            "- read_file(path, skill_name?, max_chars?): 读取文件。提供 skill_name 时读取 skill 目录内文件，否则读取 session 目录",
            "- write_file(path, content): 在 session 目录写入文件",
            "- bash(command, cwd?): 执行命令。cwd 可以是 'skill:<skill_name>'（在 skill 目录执行）或省略（在 session 目录执行）",
            "- export_file(path): 标记 session 目录中的文件为最终交付物",
            uploads_context or "",
            "",
            "【重要】工具调用规则：",
            "1. 优先使用 function call（工具调用）发起动作。",
            "2. 如果模型不支持 function call，允许输出如下 JSON 代码块作为备选：",
            '   ```json',
            '   {"name": "<tool_name>", "arguments": {<args>}}',
            '   ```',
            "3. 每次工具执行后，结果会以如下格式出现在后续的 user message 中：",
            '   <tool_result id="<call_id>" name="<tool_name>" status="success|error">',
            '   {...结果 JSON...}',
            '   </tool_result>',
            "   请根据 tool_result 中的结果继续完成任务。",
            "4. 执行命令时尽量一次获取完整输出，不要先过滤再补充。如果第一次命令失败或结果为空，再尝试其他方式。",
            "5. 加载 skill 后，仔细阅读 SKILL.md 中的指令，并按其说明执行任务。skill 中的相对路径（如 scripts/、reference/）均相对于 skill 目录。",
            "6. 不要重复执行相同或高度相似的工具调用。如果上一步已经获取了所需信息，直接利用该信息继续，不要重新获取。"
        ]
        return "\n".join(lines)


def _fmt_skills_xml(skills_index: dict[str, Any]) -> str:
    skills = skills_index.get("skills") or [] if isinstance(skills_index, dict) else []
    if not skills:
        return "<available_skills>\n  (No skills available)\n</available_skills>"
    lines = ["<available_skills>"]
    for s in skills:
        name = str(s.get("name") or s.get("folder") or "")
        desc = str(s.get("description") or "")
        lines.append("  <skill>")
        lines.append(f"    <name>{name}</name>")
        lines.append(f"    <description>{desc}</description>")
        lines.append("  </skill>")
    lines.append("</available_skills>")
    return "\n".join(lines)
