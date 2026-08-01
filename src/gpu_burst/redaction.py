from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit


SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b("
    r"aws_secret_access_key|aws_access_key_id|secret_access_key|session_token|"
    r"aws_session_token|vast_api_key|api_key|access_token"
    r")\b\s*[:=]\s*([^\s]+)"
)
RUNPOD_TOKEN_RE = re.compile(r"\brpa_[A-Za-z0-9_-]{20,}\b")


def _redact_presigned_url(value: str) -> str:
    parts = urlsplit(value)
    if not parts.query:
        return value
    lowered = parts.query.lower()
    if "x-amz-" not in lowered and "signature=" not in lowered:
        return value
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "[REDACTED]", parts.fragment))


def redact_text(text: str) -> str:
    redacted = SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    redacted = RUNPOD_TOKEN_RE.sub("[REDACTED]", redacted)
    return re.sub(r"https?://[^\s]+", lambda m: _redact_presigned_url(m.group(0)), redacted)
