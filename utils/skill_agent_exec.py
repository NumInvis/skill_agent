from __future__ import annotations

import os
import shutil
from typing import Any


def _detect_skills_root(explicit_path: str | None) -> str | None:
    if explicit_path and os.path.isdir(explicit_path):
        return os.path.abspath(explicit_path)

    env_path = os.getenv("SKILLS_ROOT")
    if env_path and os.path.isdir(env_path):
        return os.path.abspath(env_path)

    plugin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    candidates = [os.path.join(plugin_root, "skills")]
    for p in candidates:
        if os.path.isdir(p):
            return os.path.abspath(p)
    return None


def _resolve_executable(exe: str) -> str | None:
    e = str(exe or "").strip()
    if not e:
        return None
    from utils.skill_agent_paths import _is_abs_path

    if _is_abs_path(e):
        return e
    found = shutil.which(e)
    if found:
        return found
    if os.name == "nt":
        for ext in (".cmd", ".exe", ".bat"):
            found = shutil.which(e + ext)
            if found:
                return found
    return None
