"""Mask secrets before anything is written to the trace store."""
from __future__ import annotations

import re

_PATTERNS = [
    ("KEY", re.compile(r"\b(?:sk|pk|rk|ghp|gho|ghs|github_pat|xox[abpr]|AKIA|AIza)[-_A-Za-z0-9]{16,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}\b")),
    ("SECRET", re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|密码|口令)\b(\s*[:=：]\s*)(\S{4,})")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){15,18}\d\b")),
    ("CNID", re.compile(r"\b\d{17}[\dXx]\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("PHONE", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
]


def redact(text: str, extra: list[str] | None = None) -> str:
    if not text:
        return text
    for name, pat in _PATTERNS:
        if name == "SECRET":
            text = pat.sub(lambda m: f"{m.group(1)}{m.group(2)}[SECRET]", text)
        else:
            text = pat.sub(f"[{name}]", text)
    for rx in extra or []:
        text = re.sub(rx, "[REDACTED]", text)
    return text


def is_private(app: str, title: str, deny: list[str]) -> bool:
    s = f"{app} {title}".lower()
    return any(d.lower() in s for d in deny)
