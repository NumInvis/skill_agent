from __future__ import annotations

import logging
from typing import Any

from utils.tools import _safe_get

# Try to use Dify plugin logger handler; fallback to StreamHandler if unavailable
try:
    from dify_plugin.config.logger_format import plugin_logger_handler

    _logger = logging.getLogger("skill_agent")
    if not _logger.handlers:
        _logger.addHandler(plugin_logger_handler)
        _logger.setLevel(logging.DEBUG)
except Exception:
    _logger = logging.getLogger("skill_agent")
    if not _logger.handlers:
        _handler = logging.StreamHandler()
        _handler.setFormatter(logging.Formatter("[skill][%(levelname)s] %(message)s"))
        _logger.addHandler(_handler)
        _logger.setLevel(logging.DEBUG)


def _dbg(msg: str) -> None:
    try:
        _logger.debug(msg)
    except Exception:
        print(f"[skill][debug] {msg}", flush=True)


def _model_brief(model_config: Any) -> str:
    if isinstance(model_config, dict):
        provider = model_config.get("provider")
        model = model_config.get("model")
        mode = model_config.get("mode")
        return f"provider={provider!s} model={model!s} mode={mode!s}"
    provider = _safe_get(model_config, "provider")
    model = _safe_get(model_config, "model")
    mode = _safe_get(model_config, "mode")
    return f"provider={provider!s} model={model!s} mode={mode!s}"
