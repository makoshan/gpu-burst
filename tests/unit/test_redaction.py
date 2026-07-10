from gpu_burst.redaction import redact_text


def test_redacts_common_secret_assignments_and_presigned_query() -> None:
    raw = (
        "AWS_SECRET_ACCESS_KEY=abc123\n"
        "session_token: xyz789\n"
        "https://bucket.example/key?X-Amz-Signature=sig&X-Amz-Credential=cred"
    )

    redacted = redact_text(raw)

    assert "abc123" not in redacted
    assert "xyz789" not in redacted
    assert "X-Amz-Signature" not in redacted
    assert "[REDACTED]" in redacted

