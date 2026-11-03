"""Function adapters for the existing package boundaries."""
import csv
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from bin_finder.brief import BriefConfig, BriefPlan, plan_briefs
from bin_finder.footage.config import FootageConfig
from bin_finder.footage.service import FootagePlan, search_footage
from bin_finder.footage.__main__ import create_registry
from bin_finder.matching import MatchConfig, select_footage, apply_decisions
from bin_finder.matching.models import SelectionPlan
from bin_finder.matching.review_html import render_review_html
from bin_finder.production.__main__ import parser as production_parser, produce
from bin_finder.production.config import ProductionConfig
from bin_finder.production.media import acquire_media, probe_media
from bin_finder.production.render import render_video
from bin_finder.production.timeline import Timeline, resolve_selections
from bin_finder.qa.__main__ import evaluate, save_report, validate_input
from bin_finder.qa.export import normalize_loudness
from bin_finder.qa.checks import EXPORT_FIXABLE_CODES


def read_json(path: Path) -> dict:
    """Read a UTF-8 document."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict) -> None:
    """Write a portable document."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def selections(directory: Path, allow_suggested: bool, options: Any = None) -> None:
    """Use the exact production eligibility gate."""
    resolve_selections(SelectionPlan.from_dict(read_json(directory / "selection.json")),
                       FootagePlan.from_dict(read_json(directory / "footage.json")), allow_suggested,
                       effective_reuse(options) if options else False,
                       ProductionConfig.load(options.project_root).youtube_transform if options else None)


def write_brief_csv(path: Path, plan: BriefPlan, config: BriefConfig) -> None:
    """Retain the standalone brief CLI's review columns."""
    columns = ["cue_id", "chapter", "text", "est_duration_sec", "subject", "action", "setting", "shot_type"]
    columns.extend("queries_" + source for source in config.sources)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for cue, brief in zip(plan.cues, plan.briefs):
            values = {**cue.to_dict(), **brief.to_dict()}
            row = {column: values[column] for column in columns if not column.startswith("queries_")}
            row.update({"queries_" + source: " | ".join(brief.queries[source]) for source in config.sources})
            writer.writerow(row)


def run_brief(script: Path, directory: Path, options: Any, services: Any) -> dict:
    """Execute the brief stage through existing package functions."""
    root = options.project_root
    config = BriefConfig.load(root)
    if options.brief_provider:
        config = replace(config, provider=options.brief_provider)
    provider = services.brief_provider_factory(config) if services.brief_provider_factory else None
    plan = plan_briefs(script.read_text(encoding="utf-8-sig"), config, provider, limit_cues=options.limit_cues)
    write_json(directory / "brief.json", plan.to_dict())
    write_brief_csv(directory / "brief.csv", plan, config)
    return {"cues": len(plan.cues)}


def effective_reuse(options: Any) -> bool:
    """Resolve project opt-in consistently at every stage boundary."""
    if options.youtube_reuse is not None:
        return options.youtube_reuse
    return FootageConfig.load(options.project_root).youtube_reuse


def run_footage(script: Path, directory: Path, options: Any, services: Any) -> dict:
    """Execute the footage stage through existing package functions."""
    root = options.project_root
    config = FootageConfig.load(root)
    if options.sources is not None:
        config = replace(config, sources=options.sources)
    if options.youtube is not None:
        config = replace(config, youtube_enabled=options.youtube)
    config = replace(config, youtube_reuse=effective_reuse(options),
                     cache_dir=str(root / config.cache_dir), usage_dir=str(root / config.usage_dir) if config.usage_dir else str(directory))
    youtube_service = services.youtube_service_factory(config) if services.youtube_service_factory and config.youtube_reuse else None
    registry = (services.footage_registry_factory or create_registry)(root)
    plan = search_footage(BriefPlan.from_dict(read_json(directory / "brief.json")), registry, config, youtube_service=youtube_service)
    write_json(directory / "footage.json", plan.to_dict())
    return {"sources": plan.candidates_per_source, "candidates": sum(plan.candidates_per_source.values())}


def run_matching(script: Path, directory: Path, options: Any, services: Any) -> dict:
    """Execute the matching stage through existing package functions."""
    root = options.project_root
    config = MatchConfig.load(root)
    if options.no_vlm:
        config = replace(config, vlm_enabled=False)
    scorer = services.matching_scorer or select_footage
    plan = scorer(FootagePlan.from_dict(read_json(directory / "footage.json")),
                  BriefPlan.from_dict(read_json(directory / "brief.json")), config,
                  judge=services.matching_judge, fetch=services.matching_fetch)
    if options.decisions:
        plan = apply_decisions(plan, read_json(options.decisions))
    write_json(directory / "selection.json", plan.to_dict())
    (directory / "review.html").write_text(render_review_html(plan), encoding="utf-8")
    return {"auto": sum(cue.get("status") == "auto_selected" for cue in plan.cues),
            "needs_review": sum(not cue.get("selected_source_id") for cue in plan.cues),
            "suggested": sum(bool(cue.get("suggested_source_id")) and not cue.get("selected_source_id") for cue in plan.cues)}


def run_production(script: Path, directory: Path, options: Any, services: Any) -> dict:
    """Execute the production stage through existing package functions."""
    root = options.project_root
    command = [str(directory / "selection.json"), "--footage", str(directory / "footage.json"),
               "-o", str(directory / "video.mp4"), "--work-dir", str(directory / "work"),
               "--project-root", str(root)]
    for enabled, flag in ((options.allow_suggested, "--allow-suggested"),
                          (options.no_subtitles, "--no-subtitles"), (options.no_icon, "--no-icon")):
        if enabled:
            command.append(flag)
    if options.music:
        command.extend(["--music", str(options.music)])
    command.append("--youtube-reuse" if effective_reuse(options) else "--no-youtube-reuse")
    engine = services.speech_engine_factory() if services.speech_engine_factory else None
    produce(production_parser().parse_args(command), engine, services.media_loader or acquire_media,
            services.media_probe or probe_media, services.renderer or render_video)
    return {"duration": read_json(directory / "production.json")["duration"]}


def run_qa(name: str, directory: Path, options: Any, services: Any) -> dict:
    """Evaluate source or final media and write both report formats."""
    root = options.project_root
    timeline = Timeline.from_dict(read_json(directory / "production.json"))
    validate_input(timeline, options.target_lufs)
    config = ProductionConfig.load(root)
    credits = (directory / "credits.txt").read_text(encoding="utf-8-sig")
    video = directory / ("final.mp4" if name == "export" else "video.mp4")
    if name == "export":
        exporter = services.exporter or normalize_loudness
        exporter(directory / "video.mp4", video, options.target_lufs, config=config)
    evaluator = services.qa_evaluator or evaluate
    report = evaluator(video, directory / "production.json", timeline, credits, config, False, options.target_lufs)
    save_report(report, timeline, directory, ".final" if name == "export" else "")
    return {"passed": report.passed, "blockers": sum(item.severity == "blocker" for item in report.findings),
            "blockers_fixable_by_export": sum(item.severity == "blocker" and item.code in EXPORT_FIXABLE_CODES
                                              for item in report.findings),
            "warnings": sum(item.severity == "warning" for item in report.findings),
            "lufs": report.metrics.get("lufs")}


def execute_step(name: str, script: Path, directory: Path, options: Any, services: Any) -> dict:
    """Dispatch a stable stage name to its function adapter."""
    if name in ("qa", "export"):
        return run_qa(name, directory, options, services)
    handlers = {"brief": run_brief, "footage": run_footage,
                "matching": run_matching, "production": run_production}
    return handlers[name](script, directory, options, services)
