"""Match footage and generate an offline review document."""
import argparse
import json
from pathlib import Path
from dataclasses import replace
from bin_finder.brief import BriefPlan
from bin_finder.footage.service import FootagePlan
from . import MatchConfig, select_footage, apply_decisions
from .review_html import render_review_html


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('footage', type=Path)
    parser.add_argument('--briefs', type=Path, required=True)
    parser.add_argument('-o', '--output', type=Path, required=True)
    parser.add_argument('--html', type=Path)
    parser.add_argument('--decisions', type=Path)
    parser.add_argument('--project-root', type=Path, default=Path.cwd())
    parser.add_argument('--no-vlm', action='store_true')
    parser.add_argument('--limit-cues', type=int)
    args = parser.parse_args(argv)
    try:
        footage = FootagePlan.from_dict(json.loads(args.footage.read_text(encoding='utf-8-sig')))
        briefs = BriefPlan.from_dict(json.loads(args.briefs.read_text(encoding='utf-8-sig')))
        config = MatchConfig.load(args.project_root)
        if args.no_vlm:
            config = replace(config, vlm_enabled=False)
        if args.limit_cues is not None:
            if args.limit_cues < 1:
                raise ValueError('limit')
            footage = replace(footage, cues=footage.cues[:args.limit_cues])
        result = select_footage(footage, briefs, config)
        if args.decisions:
            result = apply_decisions(result, json.loads(args.decisions.read_text(encoding='utf-8-sig')))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding='utf-8')
        if args.html:
            args.html.parent.mkdir(parents=True, exist_ok=True)
            args.html.write_text(render_review_html(result), encoding='utf-8')
    except (OSError, ValueError, TypeError, KeyError):
        parser.exit(2, 'Invalid matching input/configuration or output path.\n')
    stats = result.stats
    cue_count = len(result.cues)
    auto_rate = stats['auto_selected'] / cue_count if cue_count else 0
    print(
        f"Cues: {cue_count}; auto-selected: {stats['auto_selected']}; "
        f"needs_review: {stats['needs_review']}; no_candidates: {stats['no_candidates']}; "
        f"auto rate: {auto_rate:.1%}; text/cue: {stats['text_seconds_per_cue']:.3f}s; "
        f"VLM/cue: {stats['vlm_seconds_per_cue']:.3f}s; "
        f"VLM calls: {stats['vlm_calls']}; unavailable: {stats['vlm_unavailable']}",
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
