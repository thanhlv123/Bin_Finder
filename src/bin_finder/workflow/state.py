"""Small atomic reference store. Analysis payloads stay in F003's cache."""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


FORMAT = "bin_finder_workflow_v1"
STAGES = {"pending", "acquiring", "acquired", "analyzing", "analyzed",
          "failed", "cancelled", "skipped"}


class WorkflowStateError(RuntimeError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


def safe_text(value):
    for name, secret in os.environ.items():
        if name.startswith("BIN_FINDER_") and ("KEY" in name or "SECRET" in name) and secret:
            value = value.replace(secret, "[redacted]")
    return value[:4096]


class RunState:
    def __init__(self, root):
        self.path = Path(root) / "workflow.json"
        self.items = {}

    def load(self):
        if self.path.exists():
            try:
                if self.path.is_symlink() or self.path.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError()
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                if payload["format"] != FORMAT or not isinstance(payload["items"], dict):
                    raise ValueError()
                self.items = payload["items"]
            except Exception:
                raise WorkflowStateError("Workflow state cannot be loaded safely.") from None

    def write(self):
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".tmp",
                                             dir=self.path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                # Defense in depth: no arbitrary candidate metadata or exception text.
                handle.write(safe_text_json({"format": FORMAT, "updated_at": now(),
                                            "items": self.items}))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            raise WorkflowStateError("Workflow state could not be persisted.") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass  # Preserve the categorized write error if cleanup also fails.


def safe_text_json(payload):
    # Redact individual values before encoding, preserving valid JSON escaping.
    def clean(value):
        if isinstance(value, str):
            return safe_text(value)
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        return value
    return json.dumps(clean(payload), ensure_ascii=True, indent=2)
