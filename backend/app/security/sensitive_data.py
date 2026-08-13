"""Legal-data confidentiality policy (application shared-responsibility layer).

Controls what may leave the process boundary via logs and observability.
Document bodies, prompts, transcripts, and cell values must never be the
default payload for third-party tracing or unstructured application logs.

See ``docs/LEGAL_DATA_SECURITY.md``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from app.config import config

# Keys that typically carry matter text / attorney-client content.
_CONTENT_KEY_RE = re.compile(
    r"("
    r"question|prompt|prompt_preview|messages?|content|text|answer|completion|"
    r"output|input|original_text|transcript|transcription|cell_value|raw_cell_value|"
    r"validated_cell_value|document_context|selected_text|template_file_content|"
    r"document|page_content|chunk|quote|found_text|body|payload_preview"
    r")",
    re.IGNORECASE,
)

_REDACTED = "<redacted:legal_content>"


def langfuse_capture_content_enabled() -> bool:
    """
    When False (legaltech default), Langfuse receives metadata only —
    no questions, prompts, completions, or document excerpts.
    """
    return bool(getattr(config, "LANGFUSE_CAPTURE_CONTENT", False))


def _redact_content(value: Any, *, depth: int, force: bool = False) -> Any:
    if depth > 8:
        return "<max_depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if not force:
            return value
        if len(value) <= 64 and value.startswith("<") and value.endswith(">"):
            return value
        return _REDACTED if value.strip() else value
    if isinstance(value, bytes):
        return _REDACTED if force else f"<bytes:{len(value)}>"
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            if _CONTENT_KEY_RE.search(key_s):
                if isinstance(item, (list, tuple)):
                    out[key_s] = {
                        "redacted": True,
                        "items": len(item),
                    }
                elif isinstance(item, str):
                    out[key_s] = {
                        "redacted": True,
                        "chars": len(item),
                    }
                elif isinstance(item, dict):
                    out[key_s] = _redact_content(item, depth=depth + 1, force=True)
                else:
                    out[key_s] = _REDACTED
            else:
                out[key_s] = _redact_content(item, depth=depth + 1, force=False)
        return out
    if isinstance(value, (list, tuple, set)):
        return [
            _redact_content(v, depth=depth + 1, force=force) for v in list(value)[:20]
        ]
    return _REDACTED if force else value


def redact_observability_value(value: Any, *, depth: int = 0) -> Any:
    """Redact nested observability payloads according to capture policy."""
    if langfuse_capture_content_enabled():
        return value
    # Top-level bare strings (generation input/output) are treated as content.
    if isinstance(value, str):
        return _redact_content(value, depth=depth, force=True)
    return _redact_content(value, depth=depth, force=False)


def safe_log_text_meta(label: str, text: Optional[str]) -> str:
    """Format log-safe metadata for a text field (length only)."""
    n = len(text or "")
    return f"{label}_chars={n}"


def agent_debug_file_logging_enabled() -> bool:
    """NDJSON / .cursor debug file writers — off unless explicitly enabled."""
    return bool(getattr(config, "AGENT_DEBUG_FILE_LOG", False))
