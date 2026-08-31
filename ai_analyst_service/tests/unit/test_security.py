from __future__ import annotations

from app.services.security import render_user_template, sanitize_text, truncate_json_context


def test_sanitize_text_strips_control_characters():
    raw = "Hello\x00World\x07!\x1b[31m"
    cleaned = sanitize_text(raw)
    assert "\x00" not in cleaned
    assert "\x07" not in cleaned
    assert "\x1b" not in cleaned
    assert "Hello" in cleaned and "World" in cleaned


def test_sanitize_text_none_and_empty():
    assert sanitize_text(None) == ""
    assert sanitize_text("") == ""
    assert sanitize_text("   ") == ""


def test_sanitize_text_preserves_normal_text():
    text = "Reviewed RELIANCE trade — entry at 1265.40, exit at 1290.10."
    assert sanitize_text(text) == text


def test_truncate_json_context_under_limit_unchanged():
    obj = {"a": 1, "b": [1, 2, 3]}
    result = truncate_json_context(obj, max_chars=10_000)
    assert "TRUNCATED" not in result
    assert '"a": 1' in result


def test_truncate_json_context_over_limit_is_marked():
    obj = {"data": "x" * 5000}
    result = truncate_json_context(obj, max_chars=500)
    assert len(result) <= 500
    assert "TRUNCATED" in result


def test_render_user_template_fills_placeholders():
    template = "Explain this.\n\n<data>\n{context_json}\n</data>\n\n<user_note>\n{user_note}\n</user_note>"
    rendered = render_user_template(template, context_json='{"x": 1}', user_note="please be brief")
    assert '{"x": 1}' in rendered
    assert "please be brief" in rendered


def test_render_user_template_defaults_empty_note():
    template = "<data>{context_json}</data><user_note>{user_note}</user_note>"
    rendered = render_user_template(template, context_json="{}", user_note="")
    assert "(none provided)" in rendered
