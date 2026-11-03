"""Run project-scoped footage discovery from an R1 BriefPlan."""
import argparse
from dataclasses import replace
import json
from pathlib import Path

from bin_finder.brief import BriefPlan
from bin_finder.provider_config import ProviderConfig
from bin_finder.providers.registry import ProviderRegistry
from .config import FootageConfig
from .credits import LicenseInfo, render_credits
from .service import search_footage


def create_registry(project_root):
    return ProviderRegistry.from_config(ProviderConfig.load(project_root))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("briefs", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--credits", type=Path)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--sources")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--youtube", dest="youtube_enabled", action="store_true")
    group.add_argument("--no-youtube", dest="youtube_enabled", action="store_false")
    parser.set_defaults(youtube_enabled=None)
    parser.add_argument("--limit-cues", type=int)
    args = parser.parse_args(argv)
    try:
        plan = BriefPlan.from_dict(json.loads(args.briefs.read_text(encoding="utf-8")))
        config = FootageConfig.load(args.project_root)
        if args.sources is not None:
            config = replace(config, sources=[s.strip() for s in args.sources.split(",") if s.strip()])
        if args.youtube_enabled is not None:
            config = replace(config, youtube_enabled=args.youtube_enabled)
        if args.limit_cues is not None:
            if args.limit_cues < 1:
                raise ValueError("invalid cue limit")
            plan = replace(plan, cues=plan.cues[:args.limit_cues])
        result = search_footage(plan, create_registry(args.project_root), config)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        if args.credits:
            args.credits.parent.mkdir(parents=True, exist_ok=True)
            args.credits.write_text(render_credits(LicenseInfo(**c["license"])
                for cue in result.cues for c in cue["candidates"]), encoding="utf-8")
    except (OSError, ValueError, TypeError, KeyError):
        parser.exit(2, "Invalid input/configuration or unable to write footage output.\n")
    print(f"Cues: {len(result.cues)}; candidates: {json.dumps(result.candidates_per_source)}; "
          f"empty cues: {sum(not c['candidates'] for c in result.cues)}; "
          f"errors: {sum(len(c['errors']) for c in result.cues)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
