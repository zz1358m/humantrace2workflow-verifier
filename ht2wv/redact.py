"""Mask secrets before anything is written to the trace store."""
from __future__ import annotations

import re

# Quote alternatives are disjoint from bare values. Keep spaces inside quotes,
# but stop bare values at delimiters, CJK text, and replacement labels.
_QUOTED_VALUE = (
    r'"(?:\\[^\r\n]|[^"\\\r\n])*"'
    r"|'(?:\\[^\r\n]|[^'\\\r\n])*'"
)
_VALUE = _QUOTED_VALUE + (
    r"""|[^\s"'\x60;,|&{}\[\]"""
    r"\u3000-\u303f\uff00-\uffef\u3400-\u4dbf\u4e00-\u9fff"
    r"\uf900-\ufaff\U00020000-\U0002ffff\U00030000-\U0003ffff]+"
)
_SECRET_NAME = (
    r"(?:[A-Za-z0-9]+[_-])*"
    r"(?:password|passwd|pwd|secret[_-]access[_-]key|private[_-]key|secret|token|api[_-]?key)"
    r"(?:[_-](?:key|token|value))*"
)
_CLI_PASSWORD = re.compile(r"(?<!\S)(-p)([ \t]*)(?!-[A-Za-z])(" + _VALUE + r")")

_PATTERNS = [
    # Remove whole structured credentials before individual token patterns.
    ("KEY", re.compile(
        r"-----BEGIN (?P<kind>(?:[A-Z0-9]+ )*PRIVATE KEY)-----"
        r"[\s\S]*?-----END (?P=kind)-----"
    )),
    ("URL", re.compile(
        r"([A-Za-z][A-Za-z0-9+.-]*://)[^\s/:@]+:[^\s/?#]+@", re.I
    )),
    ("CLI", re.compile(
        r"(?<![A-Za-z0-9_./-])(?:mysql|sshpass)(?=[ \t])"
        r"(?:[ \t]|" + _QUOTED_VALUE + r"""|[^\s"'\x60;|&]+)*"""
    )),
    ("SECRET", re.compile(
        r"(?<![A-Za-z0-9_-])(--(?:password|passwd|token|api-key|secret|access-token))"
        r"([ \t]*=[ \t]*|[ \t]+)(?!-[A-Za-z])("
        + _VALUE + r")"
    )),
    # Explicit authorization headers remain sensitive even with short values.
    ("SECRET", re.compile(
        r"(?<![A-Za-z0-9_-])(Authorization)(:[ \t]*Bearer[ \t]+)("
        + _VALUE + r")", re.I
    )),
    ("SECRET", re.compile(
        r"(?<![A-Za-z0-9_-])(Bearer)([ \t]+)("
        r'"[A-Za-z0-9._~+/=-]{8,}"'
        r"|'[A-Za-z0-9._~+/=-]{8,}'"
        r"|[A-Za-z0-9._~+/=-]{8,})(?![A-Za-z0-9._~+/=-])"
    )),
    ("SECRET", re.compile(
        r"(?<![A-Za-z0-9_-])(" + _SECRET_NAME + r"|密码|口令)"
        r"""(["']?[ \t]*[:=：][ \t]*)(""" + _VALUE + r")", re.I
    )),
    ("SECRET", re.compile(r"(密码|口令)([ \t]*是[ \t]*)(" + _VALUE + r")")),
    # ASCII lookarounds allow underscores and CJK beside standalone tokens.
    ("KEY", re.compile(
        r"(?<![A-Za-z0-9])(?:"
        r"(?:sk|pk|rk|ghp|gho|ghs|github_pat|xox[abpr]|AKIA|AIza)[-_A-Za-z0-9]{16,}"
        r"|hf_[A-Za-z0-9]{16,})(?![A-Za-z0-9])"
    )),
    ("JWT", re.compile(
        r"(?<![A-Za-z0-9])eyJ[A-Za-z0-9_-]{10,}\."
        r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}(?![A-Za-z0-9])"
    )),
    # CN IDs must run before cards, which also match all-numeric CN IDs.
    ("CNID", re.compile(r"(?<![A-Za-z0-9])\d{17}[\dXx](?![A-Za-z0-9])")),
    ("CARD", re.compile(r"(?<![A-Za-z0-9])(?:\d[ -]?){15,18}\d(?![A-Za-z0-9])")),
    ("EMAIL", re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w-])")),
    ("PHONE", re.compile(
        r"(?<![A-Za-z0-9])(?:(?:\+86|0086)[ -]?)?"
        r"1[3-9]\d[ -]?\d{4}[ -]?\d{4}(?![A-Za-z0-9])"
    )),
]


def _mask_secret(match: re.Match) -> str:
    value = match.group(3)
    quote = value[0] if value[0] in "\"'" else ""
    return f"{match.group(1)}{match.group(2)}{quote}[SECRET]{quote}"


def redact(text: str, extra: list[str] | None = None) -> str:
    if not text:
        return text
    for name, pat in _PATTERNS:
        if name == "SECRET":
            text = pat.sub(_mask_secret, text)
        elif name == "CLI":
            text = pat.sub(lambda m: _CLI_PASSWORD.sub(_mask_secret, m.group(0)), text)
        elif name == "URL":
            text = pat.sub(lambda m: f"{m.group(1)}[SECRET]@", text)
        else:
            text = pat.sub(f"[{name}]", text)
    for rx in extra or []:
        text = re.sub(rx, "[REDACTED]", text)
    return text


def is_private(app: str, title: str, deny: list[str]) -> bool:
    s = f"{app} {title}".lower()
    return any(d.lower() in s for d in deny)
