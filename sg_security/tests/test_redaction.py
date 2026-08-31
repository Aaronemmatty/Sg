from sg_security.redaction import redact_sensitive_fields


def test_redaction_masks_sensitive_fields():
    event = redact_sensitive_fields(
        None,
        "info",
        {"password": "secret", "nested": {"access_token": "abc"}, "message": "hello"},
    )

    assert event["password"] == "***REDACTED***"
    assert event["nested"]["access_token"] == "***REDACTED***"
    assert event["message"] == "hello"
