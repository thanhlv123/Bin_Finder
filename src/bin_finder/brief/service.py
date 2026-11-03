"""R1 entry point, independent of GUI, discovery and acquisition."""
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from .cues import split_cues
from .models import Cue, ShotBrief
from .providers import HeuristicBriefProvider, OllamaBriefProvider, OpenAICompatibleBriefProvider


@dataclass(frozen=True)
class BriefPlan:
    cues: list[Cue]
    briefs: list[ShotBrief]
    provider_used: str
    fallback_count: int
    script_sha256: str
    version: str = "brief_plan_v1"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{**data, "cues": [Cue.from_dict(c) for c in data["cues"]],
                      "briefs": [ShotBrief.from_dict(b) for b in data["briefs"]]})


def plan_briefs(script_text, config, provider=None):
    cues = split_cues(script_text)
    selected = config.provider
    if provider is None:
        if selected == "auto":
            ollama = OllamaBriefProvider(config)
            api = OpenAICompatibleBriefProvider(config)
            selected = "ollama" if ollama.available() else "openai_compatible" if api.available() else "heuristic"
        provider = {"heuristic": HeuristicBriefProvider, "ollama": OllamaBriefProvider,
                    "openai_compatible": OpenAICompatibleBriefProvider}[selected](config)
    if selected == "auto" and provider is not None:
        selected = ("openai_compatible" if isinstance(provider, OpenAICompatibleBriefProvider) else
                    "ollama" if isinstance(provider, OllamaBriefProvider) else "heuristic")
    briefs = provider.propose(cues, {"cues": cues})
    fallback_count = sum(b.origin == "heuristic" for b in briefs) if selected != "heuristic" else 0
    if config.provider == "auto" and selected == "heuristic":
        fallback_count = len(cues)
        briefs = [replace(b, notes=b.notes + " Fallback: configured LLM unavailable.") for b in briefs]
    return BriefPlan(cues, briefs, selected, fallback_count, sha256(script_text.encode("utf-8")).hexdigest())
