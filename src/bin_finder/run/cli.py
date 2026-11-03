"""Single-script and batch command line interface."""
import argparse
from dataclasses import fields
import json
from pathlib import Path
import sys
from time import perf_counter

from .pipeline import RunOptions, RunServices, STEPS, run_pipeline
from .steps import read_json, write_json

CONFIG_KEYS = {
    "brief": {"provider": "brief_provider"},
    "footage": {"sources": "sources", "youtube": "youtube"},
    "matching": {"no_vlm": "no_vlm"},
    "production": {"music": "music", "no_subtitles": "no_subtitles", "no_icon": "no_icon"},
    "qa": {"target_lufs": "target_lufs", "strict": "strict_qa"},
}


def load_options(arguments: argparse.Namespace) -> RunOptions:
    """Merge allowlisted configuration with explicit CLI overrides."""
    values = {}
    payload = read_json(arguments.config) if arguments.config else {}
    if not isinstance(payload, dict):
        raise ValueError("run config must be an object")
    for key, value in payload.items():
        if key in CONFIG_KEYS:
            if not isinstance(value, dict):
                raise ValueError(f"Invalid config section: {key}")
            for child, setting in value.items():
                if child not in CONFIG_KEYS[key]:
                    raise ValueError(f"Unknown config key: {key}.{child}")
                values[CONFIG_KEYS[key][child]] = setting
        elif key in ("limit_cues", "allow_suggested", "no_export"):
            values[key] = value
        else:
            raise ValueError(f"Unknown config key: {key}")
    for field in fields(RunOptions):
        value = getattr(arguments, field.name, None)
        if value is not None:
            values[field.name] = value
    for key in ("project_root", "decisions", "music"):
        if values.get(key) is not None:
            if not isinstance(values[key], (str, Path)):
                raise ValueError(f"Invalid config value: {key}")
            values[key] = Path(values[key]).resolve()
    for key in ("allow_suggested", "no_vlm", "no_subtitles", "no_icon", "no_export", "strict_qa", "youtube"):
        if key in values and type(values[key]) is not bool:
            raise ValueError(f"Invalid config boolean: {key}")
    if "brief_provider" in values and values["brief_provider"] not in ("auto", "heuristic", "ollama", "openai_compatible"):
        raise ValueError("Invalid brief.provider")
    if "sources" in values and (not isinstance(values["sources"], list) or any(not isinstance(source, str) for source in values["sources"])):
        raise ValueError("Invalid footage.sources")
    return RunOptions(**values)


def parser() -> argparse.ArgumentParser:
    """Build the stable headless CLI."""
    command = argparse.ArgumentParser(prog="python -m bin_finder run")
    command.add_argument("script", nargs="?", type=Path)
    command.add_argument("--batch", type=Path)
    command.add_argument("-o", required=True, type=Path)
    command.add_argument("--config", type=Path)
    command.add_argument("--from-step", choices=STEPS)
    command.add_argument("--until-step", choices=STEPS)
    for flag in ("resume", "allow-suggested", "strict-qa", "no-vlm", "no-subtitles", "no-icon", "no-export"):
        command.add_argument("--" + flag, action="store_true", default=None)
    command.add_argument("--no-youtube", dest="youtube", action="store_false", default=None)
    command.add_argument("--limit-cues", type=int)
    command.add_argument("--target-lufs", type=float)
    for flag in ("decisions", "music", "project-root"):
        command.add_argument("--" + flag, type=Path)
    return command


def main(argv: list[str] | None = None, *, services: RunServices | None = None) -> int:
    """Run every batch member even when an earlier member fails."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    command = parser()
    arguments = command.parse_args(argv)
    try:
        if bool(arguments.script) == bool(arguments.batch):
            raise ValueError("Specify exactly one SCRIPT or --batch")
        options = load_options(arguments)
        if not arguments.batch:
            return run_pipeline(arguments.script, arguments.o, options, services=services)
        if not arguments.batch.is_dir():
            raise ValueError("Missing batch directory")
        scripts = sorted((path for path in arguments.batch.iterdir() if path.is_file() and path.suffix.lower() in (".txt", ".md")), key=lambda path: path.name)
        if not scripts:
            raise ValueError("No scripts in batch")
        if len({path.stem.casefold() for path in scripts}) != len(scripts):
            raise ValueError("Batch script stems must be unique")
        arguments.o.mkdir(parents=True, exist_ok=True)
        results = []
        for script in scripts:
            started = perf_counter()
            directory = arguments.o / script.stem
            exit_code = run_pipeline(script, directory, options, services=services)
            state_path = directory / "run-state.json"
            state = read_json(state_path) if state_path.exists() else {}
            stopped = next((step["name"] for step in reversed(state.get("steps", [])) if step["status"] not in ("pending", "skipped")), None)
            results.append({"script": str(script), "status": state.get("status", "failed"), "stopped_step": stopped,
                            "exit_code": exit_code, "seconds": perf_counter() - started,
                            "final_mp4": str(directory / "final.mp4") if (directory / "final.mp4").exists() else None})
            write_json(arguments.o / "batch-summary.json", {"scripts": results})
        print("Script | Status | Step | Exit | Seconds | Final MP4")
        for result in results:
            print(" | ".join(str(result[key]) for key in ("script", "status", "stopped_step", "exit_code", "seconds", "final_mp4")))
        priority = {0: 0, 4: 1, 1: 2, 2: 3, 3: 4}
        return max((result["exit_code"] for result in results), key=priority.get)
    except (OSError, ValueError, TypeError) as error:
        command.error(str(error))
    return 2
