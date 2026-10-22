"""F016 read-only, non-authoritative F013 workflow references.

Persist only identifiers and hashes. The F013 state stays in its original
app-data directory; restoring a reference never reconstructs analysis, review,
acquisition authorization, final approval or readiness.
"""
from __future__ import annotations

from pathlib import Path

from bin_finder.analysis.fingerprint import fingerprint_file
from bin_finder.session_codec import SessionError, validate_workflow_ref
from bin_finder.session_store import SessionStoreError, _read
from bin_finder.workflow import WorkflowResult, default_work_root
from bin_finder.workflow.state import FORMAT as F013_FORMAT, digest


def _state(project_id):
    path = default_work_root(project_id) / "workflow.json"
    try:
        payload = _read(path)  # Bounded, duplicate-key rejecting, no linked paths.
        if (not isinstance(payload, dict) or payload.get("format") != F013_FORMAT
                or not isinstance(payload.get("items"), dict)):
            return {}
        return payload["items"]
    except (SessionStoreError, OSError, TypeError, ValueError):
        return {}


def _identity(row):
    return [row["scene_id"], row["candidate_id"], row["provider"], row["source_id"]]


def _matching(state, row):
    item = state.get(digest(_identity(row)))
    if not isinstance(item, dict) or item.get("stage") != "analyzed":
        return None
    if (any(item.get(key) != row[key] for key in
            ("scene_id", "candidate_id", "provider", "source_id",
             "signature", "media_sha256"))):
        return None
    return item


def _media_matches(item, expected_sha):
    path_text = item.get("local_path")
    if not isinstance(path_text, str) or not path_text:
        return False
    path = Path(path_text)
    if not path.is_absolute():
        return False
    try:
        if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)()
               for p in (path, *path.parents)):
            return False
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        return fingerprint_file(path).sha256 == expected_sha
    except (OSError, ValueError):
        return False


def capture_workflow_refs(project_id, result):
    """Capture completed F013 identities from the actual project state file."""
    if not isinstance(result, WorkflowResult):
        return ()
    if Path(result.state_path) != default_work_root(project_id) / "workflow.json":
        return ()
    state = _state(project_id)
    captured = []
    for item in result.items:
        if item.stage != "analyzed":
            continue
        candidate = item.candidate
        identity = [candidate.scene_id, candidate.candidate_id,
                    candidate.provider, candidate.source_id]
        record = state.get(digest(identity))
        if not isinstance(record, dict):
            continue
        row = {key: record.get(key) for key in
               ("scene_id", "candidate_id", "provider", "source_id",
                "signature", "media_sha256")}
        try:
            row = validate_workflow_ref(row)
        except SessionError:
            continue
        if (_identity(row) != identity or _matching(state, row) is None or
                record.get("local_path") != str(item.local_path)):
            continue
        captured.append(row)
    return tuple(captured)


def restore_workflow_refs(project_id, refs):
    """Keep only state+media-verified historical references, not runnable results."""
    if not refs:
        return ()
    state = _state(project_id)
    restored = []
    for raw in refs:
        row = validate_workflow_ref(raw)
        item = _matching(state, row)
        if item is not None and _media_matches(item, row["media_sha256"]):
            restored.append(row)
    return tuple(restored)
