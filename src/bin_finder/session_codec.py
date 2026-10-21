"""F016 session codec."""
from __future__ import annotations
from dataclasses import asdict
from bin_finder.models import SceneContext, SceneRecord, SelectedClipRecord

class SessionError(ValueError):
    pass

