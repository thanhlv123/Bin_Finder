"""UTF-8 file logging alongside Windows-safe console output."""
import re
from typing import TextIO
from urllib.error import URLError


class Tee:
    """Mirror package progress without changing package CLI behavior."""

    def __init__(self, console: TextIO, logfile: TextIO) -> None:
        self.console = console
        self.logfile = logfile

    def write(self, message: str) -> int:
        """Retain Unicode in the log and replace unsupported console glyphs."""
        self.logfile.write(message)
        try:
            self.console.write(message)
        except UnicodeEncodeError:
            encoding = getattr(self.console, "encoding", None) or "utf-8"
            self.console.write(message.encode(encoding, errors="replace").decode(encoding))
        return len(message)

    def flush(self) -> None:
        """Flush both destinations."""
        self.console.flush()
        self.logfile.flush()


def redact_text(message: str) -> str:
    """Mask credential-shaped values without reading provider secrets."""
    patterns = (
        r"\bsk-[A-Za-z0-9_.-]+",
        r"(?i)\bBearer\s+[^\s,;\"']+",
        r"(?i)\b(?:api[_-]?key|key|token)\b[\"']?\s*(?:[:=]\s*[\"']?|\s+)[^\s,;\"']+",
        r"[A-Za-z0-9_-]{32,}",
    )
    for pattern in patterns:
        message = re.sub(pattern, "[redacted]", message)
    return message


def step_error(name: str, error: Exception) -> str:
    """Keep a bounded diagnostic and a connection-specific recovery hint."""
    detail = str(error)
    connection = isinstance(error, (ConnectionError, URLError)) or any(
        marker in detail.lower() for marker in ("connect", "3900", "refused", "voicestudio is not running"))
    hint = "; hãy mở VoiceStudio và kiểm tra kết nối" if name == "production" and connection else ""
    message = " ".join(redact_text(f"{type(error).__name__}: {detail}").split())
    return message[:300 - len(hint)] + hint
