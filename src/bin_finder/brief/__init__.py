"""Sentence-level visual briefs for footage discovery."""
from .config import BriefConfig
from .cues import split_cues
from .models import Cue, ShotBrief
from .service import BriefPlan, plan_briefs

__all__ = ["BriefConfig", "Cue", "ShotBrief", "BriefPlan", "split_cues", "plan_briefs"]
