from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

from utils.skill_agent_constants import ALLOWED_COMMANDS
from utils.skill_agent_exec import _resolve_executable
from utils.skill_agent_paths import _normalize_relative_file_path
from utils.tools import _list_dir, _parse_frontmatter, _read_text, _safe_join


class _AgentRuntime:
    def __init__(
        self,
        *,
        skills_root: str | None,
        session_dir: str,
    ) -> None:
        self.skills_root = skills_root
        self.session_dir = session_dir

    def load_skills_index(self) -> dict[str, Any]:
        if not self.skills_root:
            return {"root": None, "skills": []}
        skills: list[dict[str, Any]] = []
        for folder in sorted(os.listdir(self.skills_root)):
            path = os.path.join(self.skills_root, folder)
            if not os.path.isdir(path):
                continue
            skill_md = os.path.join(path, "SKILL.md")
            meta: dict[str, str] = {}
            if os.path.isfile(skill_md):
                meta = _parse_frontmatter(_read_text(skill_md, 4000))
            skills.append(
                {
                    "name": meta.get("name") or folder,
                    "folder": folder,
                    "description": meta.get("description") or "",
                }
            )
        return {"root": self.skills_root, "skills": skills}

    def get_skill_metadata(self, skill_name: str) -> dict[str, Any]:
        if not self.skills_root:
            return {"error": "skills_root not found"}
        path = _safe_join(self.skills_root, skill_name)
        skill_md = os.path.join(path, "SKILL.md")
        if not os.path.isfile(skill_md):
            return {"error": "SKILL.md not found", "skill": skill_name}
        content = _read_text(skill_md, 12000)
        meta = _parse_frontmatter(content)
        files = _list_dir(path, max_depth=2)
        return {"skill": skill_name, "metadata": meta, "skill_md": content, "files": files}

    def list_skill_files(self, skill_name: str, max_depth: int = 2) -> dict[str, Any]:
        if not self.skills_root:
            return {"error": "skills_root not found"}
        skill_path = _safe_join(self.skills_root, skill_name)
        return {"skill": skill_name, "entries": _list_dir(skill_path, max_depth=max_depth)}

    def read_skill_file(self, skill_name: str, relative_path: str, max_chars: int = 12000) -> dict[str, Any]:
        if not self.skills_root:
            return {"error": "skills_root not found"}
        skill_path = _safe_join(self.skills_root, skill_name)
        file_path = _safe_join(skill_path, relative_path)
        if not os.path.isfile(file_path):
            return {"error": "file not found", "path": relative_path}
        return {"path": file_path, "content": _read_text(file_path, max_chars)}

    def write_file(self, relative_path: str, content: str) -> dict[str, Any]:
        os.makedirs(self.session_dir, exist_ok=True)
        rp = _normalize_relative_file_path(relative_path)
        if not rp:
            return {"error": "invalid path", "path": relative_path}
        try:
            path = _safe_join(self.session_dir, rp)
        except Exception as e:
            return {"error": "invalid path", "path": relative_path, "exception": str(e)}
        if os.path.isdir(path):
            return {"error": "path is a directory", "path": relative_path}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content or "")
        except Exception as e:
            return {"error": "write failed", "path": relative_path, "exception": str(e)}
        return {"path": path, "bytes": len((content or "").encode("utf-8"))}

    def read_file(self, relative_path: str, max_chars: int = 12000) -> dict[str, Any]:
        os.makedirs(self.session_dir, exist_ok=True)
        rp = _normalize_relative_file_path(relative_path)
        if not rp:
            return {"error": "invalid path", "path": relative_path}
        try:
            path = _safe_join(self.session_dir, rp)
        except Exception as e:
            return {"error": "invalid path", "path": relative_path, "exception": str(e)}
        if os.path.isdir(path):
            return {"error": "path is a directory", "path": relative_path}
        if not os.path.isfile(path):
            return {"error": "file not found", "path": relative_path}
        try:
            return {"path": path, "content": _read_text(path, max_chars)}
        except Exception as e:
            return {"error": "read failed", "path": relative_path, "exception": str(e)}

    def list_files(self, max_depth: int = 4) -> dict[str, Any]:
        os.makedirs(self.session_dir, exist_ok=True)
        return {"session_dir": self.session_dir, "entries": _list_dir(self.session_dir, max_depth=max_depth)}

    def run_skill_command(self, skill_name: str, command: list[str]) -> dict[str, Any]:
        if not self.skills_root:
            return {"error": "skills_root not found"}
        if not command:
            return {"error": "command must be a non-empty list"}
        skill_path = _safe_join(self.skills_root, skill_name)
        exe = command[0]
        if exe == "python":
            command = [sys.executable] + command[1:]
        elif exe not in ALLOWED_COMMANDS:
            return {"error": f"command not allowed: {exe}"}
        resolved0 = _resolve_executable(str(command[0] or ""))
        if not resolved0:
            return {"error": "executable not found", "exe": str(command[0] or exe)}
        command = [resolved0] + command[1:]
        try:
            result = subprocess.run(
                command,
                cwd=skill_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=120,
            )
            return {"returncode": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
        except subprocess.TimeoutExpired:
            return {"error": "subprocess_timeout", "timeout": 120}
        except Exception as e:
            return {"error": "subprocess_failed", "exception": str(e)}

    def run_command(self, command: list[str]) -> dict[str, Any]:
        if not command:
            return {"error": "command must be a non-empty list"}
        exe = command[0]
        if exe == "python":
            command = [sys.executable] + command[1:]
        elif exe not in ALLOWED_COMMANDS:
            return {"error": f"command not allowed: {exe}"}
        resolved0 = _resolve_executable(str(command[0] or ""))
        if not resolved0:
            return {"error": "executable not found", "exe": str(command[0] or exe)}
        command = [resolved0] + command[1:]
        os.makedirs(self.session_dir, exist_ok=True)
        try:
            result = subprocess.run(
                command,
                cwd=self.session_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=120,
            )
            return {"returncode": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
        except subprocess.TimeoutExpired:
            return {"error": "subprocess_timeout", "timeout": 120}
        except Exception as e:
            return {"error": "subprocess_failed", "exception": str(e)}

    def export_file(self, relative_path: str) -> dict[str, Any]:
        os.makedirs(self.session_dir, exist_ok=True)
        rp = _normalize_relative_file_path(relative_path)
        if not rp:
            return {"error": "invalid path", "path": relative_path}
        try:
            src = _safe_join(self.session_dir, rp)
        except Exception as e:
            return {"error": "invalid path", "path": relative_path, "exception": str(e)}
        if os.path.isdir(src):
            return {"error": "source path is a directory", "path": relative_path}
        if not os.path.isfile(src):
            return {"error": "source file not found", "path": relative_path}
        return {
            "source": src,
            "path": relative_path,
            "bytes": os.path.getsize(src),
            "note": "export_file marks the file as a final deliverable",
        }
