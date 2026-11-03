"""Headless visual brief JSON and optional review CSV."""
import argparse
import csv
from dataclasses import replace
import json
from pathlib import Path
from . import BriefConfig, plan_briefs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path)
    parser.add_argument("-o", required=True, type=Path)
    parser.add_argument("--provider", choices=["auto", "heuristic", "ollama", "openai_compatible"])
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args()
    config = BriefConfig.load(args.project_root)
    if args.provider:
        config = replace(config, provider=args.provider)
    plan = plan_briefs(args.script.read_text(encoding="utf-8-sig"), config)
    args.o.parent.mkdir(parents=True, exist_ok=True)
    args.o.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        fields = ["cue_id", "chapter", "text", "est_duration_sec", "subject", "action", "setting", "shot_type"]
        fields += ["queries_" + s for s in config.sources]
        with args.csv.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for cue, brief in zip(plan.cues, plan.briefs):
                data = {**cue.to_dict(), **brief.to_dict()}
                row = {f: data[f] for f in fields if not f.startswith("queries_")}
                row.update({"queries_" + s: " | ".join(brief.queries[s]) for s in config.sources})
                writer.writerow(row)
    print(f"{len(plan.cues)} cues; provider={plan.provider_used}; fallbacks={plan.fallback_count}")


if __name__ == "__main__":
    main()
