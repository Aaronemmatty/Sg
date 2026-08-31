from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from app.core.config import settings

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(text: str | None) -> str:
    """Strips control characters that could be used to manipulate terminal/
    log output or smuggle odd formatting into the prompt. Does NOT attempt
    to strip natural language — prompt-injection defence here relies on
    the <data>/<user_note> tag separation and system-prompt instructions in
    prompt_manager.py, not on text filtering, since filtering free-form
    English for "instruction-like" phrasing is unreliable and tends to
    either miss attacks or mangle legitimate notes.
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    return _CONTROL_CHARS_RE.sub("", normalized).strip()


def truncate_json_context(obj: Any, max_chars: int | None = None) -> str:
    """Serializes a context dict to JSON, hard-capped to max_context_chars so
    a pathologically large upstream response can never blow up LLM cost or
    context-window limits. Truncation is marked explicitly so the model
    (and any human reviewing logs) knows data was cut, rather than silently
    losing the tail."""
    max_chars = max_chars or settings.max_context_chars
    text = json.dumps(obj, default=str, indent=2, ensure_ascii=False)
    if len(text) <= max_chars:
        return text
    marker = "\n... [TRUNCATED — context exceeded size limit] ..."
    return text[: max_chars - len(marker)] + marker


def render_user_template(template: str, *, context_json: str, user_note: str) -> str:
    """Renders an admin-authored template against fixed, known placeholder
    names only. Templates come from ai_prompt_templates (admin-controlled,
    not end-user input), so str.format is safe here — the values being
    substituted are sanitized/truncated data, not the template structure
    itself."""
    return template.format(context_json=context_json, user_note=user_note or "(none provided)")
