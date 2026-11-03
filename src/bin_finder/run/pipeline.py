"""Persistent orchestration with content-based invalidation."""
from dataclasses import asdict, dataclass
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import sys
import traceback
from pathlib import Path
from time import perf_counter
from typing import Callable

from bin_finder.production import MissingSelectionError
from .steps import execute_step, read_json, selections, write_json
from .logging import Tee, step_error, redact_text

STEPS = ("brief", "footage", "matching", "production", "qa", "export")
OUTPUTS = (("brief.json", "brief.csv"), ("footage.json",), ("selection.json", "review.html"),
           ("video.mp4", "production.json", "credits.txt"), ("qa-report.json", "qa-report.html"),
           ("final.mp4", "qa-report.final.json", "qa-report.final.html"))
OPTION_KEYS = (("brief_provider", "limit_cues", "project_root"), ("sources", "youtube", "project_root"),
               ("no_vlm", "decisions", "project_root"),
               ("allow_suggested", "music", "no_subtitles", "no_icon", "project_root"),
               ("target_lufs", "strict_qa", "project_root"), ("target_lufs", "no_export", "project_root"))


@dataclass
class RunOptions:
    """Only non-secret orchestration settings."""
    project_root: Path = Path.cwd()
    brief_provider: str | None = None
    sources: list[str] | None = None
    youtube: bool | None = None
    no_vlm: bool = False
    decisions: Path | None = None
    allow_suggested: bool = False
    limit_cues: int | None = None
    music: Path | None = None
    no_subtitles: bool = False
    no_icon: bool = False
    no_export: bool = False
    target_lufs: float = -14
    strict_qa: bool = False
    resume: bool = False
    from_step: str | None = None
    until_step: str | None = None


@dataclass
class RunServices:
    """Replace network, speech, media and QA boundaries in offline tests."""
    brief_provider_factory: Callable | None = None
    footage_registry_factory: Callable | None = None
    matching_scorer: Callable | None = None
    matching_judge: object | None = None
    matching_fetch: Callable | None = None
    speech_engine_factory: Callable | None = None
    media_loader: Callable | None = None
    media_probe: Callable | None = None
    renderer: Callable | None = None
    qa_evaluator: Callable | None = None
    exporter: Callable | None = None


def now() -> str:
    """Return UTC timestamps."""
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    """Hash file contents without loading large videos into memory."""
    checksum = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def persist(path: Path, state: dict) -> None:
    """Replace state atomically within its directory."""
    temporary = path.with_suffix(".json.tmp")
    write_json(temporary, state)
    os.replace(temporary, path)


def inputs_for(index: int, script: Path, directory: Path, options: RunOptions) -> dict:
    """Hash upstream artifacts and the settings affecting this step."""
    paths = [script]
    for upstream in OUTPUTS[:index]:
        paths.extend(directory / name for name in upstream)
    if index == 2 and options.decisions:
        paths.append(options.decisions)
    if index == 3 and options.music:
        paths.append(options.music)
    values = asdict(options)
    relevant = {key: values[key] for key in OPTION_KEYS[index]}
    result = {str(path): digest(path) for path in paths}
    result["options"] = sha256(json.dumps(relevant, sort_keys=True, default=str).encode()).hexdigest()
    return result


def reusable_outputs(prior: dict, index: int, directory: Path) -> bool:
    """Verify completed artifacts against their persisted content hashes."""
    statuses = ("done", "skipped", "needs_review") if index == 2 else ("done", "skipped")
    if prior.get("status") not in statuses:
        return False
    expected = prior.get("output_hashes", {})
    return bool(expected) and all(
        (directory / output).is_file() and expected.get(output) == digest(directory / output)
        for output in OUTPUTS[index])


def validate(script: Path, options: RunOptions) -> None:
    """Reject invalid invocation before creating output artifacts."""
    if not script.is_file():
        raise ValueError(f"Missing script: {script}")
    if options.limit_cues is not None and (type(options.limit_cues) is not int or options.limit_cues < 1):
        raise ValueError("limit_cues must be positive")
    if not isinstance(options.target_lufs, (float, int)) or not -70 <= options.target_lufs <= -5:
        raise ValueError("target_lufs must be between -70 and -5")
    for name in (options.from_step, options.until_step):
        if name is not None and name not in STEPS:
            raise ValueError(f"Unknown step: {name}")
    if STEPS.index(options.from_step or "brief") > STEPS.index(options.until_step or "export"):
        raise ValueError("from-step must precede until-step")
    for path in (options.decisions, options.music):
        if path and not path.is_file():
            raise ValueError(f"Missing input: {path}")
    if options.decisions:
        read_json(options.decisions)
    if options.from_step and options.from_step != "brief" and not options.resume:
        raise ValueError("--from-step requires --resume and validated earlier outputs")


def export_can_fix(summary: dict) -> bool:
    """Allow normalization only when every blocker is fixable."""
    blockers = summary.get("blockers", 0)
    return blockers > 0 and blockers == summary.get("blockers_fixable_by_export", 0)


def run_pipeline(script: Path, out_dir: Path, options: RunOptions, *, services: RunServices | None = None) -> int:
    """Run stages and return a documented process exit code."""
    try:
        validate(Path(script), options)
    except (OSError, ValueError, TypeError) as error:
        print(str(error))
        return 2
    directory = Path(out_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "run.log").open("a", encoding="utf-8") as logfile:
        with redirect_stdout(Tee(sys.stdout, logfile)), redirect_stderr(Tee(sys.stderr, logfile)):
            return _run_pipeline(script, directory, options, services=services)


def _run_pipeline(script: Path, out_dir: Path, options: RunOptions, *, services: RunServices | None = None) -> int:
    """Persist each transition and invalidate downstream stages together."""
    script = Path(script).resolve()
    directory = Path(out_dir).resolve()
    try:
        validate(script, options)
    except ValueError as error:
        print(str(error))
        return 2
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / "run-state.json"
    try:
        previous = read_json(state_path) if options.resume and state_path.exists() else {}
    except (OSError, ValueError):
        print("Invalid run-state.json; run again without --resume")
        return 2
    if options.from_step:
        try:
            for index in range(STEPS.index(options.from_step)):
                prior = previous.get("steps", [])[index]
                if (not reusable_outputs(prior, index, directory)
                        or prior.get("inputs") != inputs_for(index, script, directory, options)
                        or not all((directory / output).is_file() for output in OUTPUTS[index])):
                    raise ValueError("Earlier outputs are stale")
        except (OSError, ValueError, IndexError, KeyError, TypeError):
            print("--from-step requires validated --resume artifacts for all earlier steps")
            return 2
    def log(message: str) -> None:
        print(message)
    if state_path.exists() and not options.resume:
        log("Cảnh báo: chạy lại từ đầu, ghi đè run-state.json")
    state = {"version": 1, "script": {"path": str(script), "sha256": digest(script)},
             "options": json.loads(json.dumps(asdict(options), default=str)), "started_at": now(),
             "finished_at": None, "status": "running", "exit_code": None,
             "steps": [{"name": name, "status": "pending", "started_at": None, "finished_at": None,
                        "seconds": 0, "inputs": {}, "outputs": [], "error": None, "summary": {}} for name in STEPS]}
    persist(state_path, state)
    invalidated = False
    exit_code = 0
    for index, entry in enumerate(state["steps"]):
        name = entry["name"]
        if index > STEPS.index(options.until_step or "export") or (name == "export" and options.no_export):
            entry["status"] = "skipped"
            persist(state_path, state)
            continue
        started = perf_counter()
        try:
            inputs = inputs_for(index, script, directory, options)
            prior = next((item for item in previous.get("steps", []) if item["name"] == name), {})
            reusable = (reusable_outputs(prior, index, directory) and prior.get("inputs") == inputs)
            before_start = index < STEPS.index(options.from_step or "brief")
            if before_start and not reusable:
                raise ValueError(f"--from-step requires validated --resume artifacts: {name}")
            if reusable and not invalidated:
                entry.update(prior, status="skipped")
                log(f"[{index + 1}/6] {name}: bỏ qua, đã xong")
            else:
                invalidated = True
                (directory / "final.mp4").unlink(missing_ok=True)
                entry.update(status="running", inputs=inputs, started_at=now())
                persist(state_path, state)
                log(f"[{index + 1}/6] {name} ...")
                qa_summary = state["steps"][4]["summary"]
                if name == "export" and not (qa_summary.get("passed") or export_can_fix(qa_summary)):
                    entry["status"] = "blocked"
                    state["status"] = "blocked"
                    exit_code = 3
                    break
                for output in OUTPUTS[index]:
                    (directory / output).unlink(missing_ok=True)
                entry["summary"] = execute_step(name, script, directory, options, services or RunServices())
                entry.update(status="done", outputs=[str(directory / output) for output in OUTPUTS[index]])
                entry["output_hashes"] = {output: digest(directory / output) for output in OUTPUTS[index]}
                entry.update(finished_at=now(), seconds=perf_counter() - started)
                log(f"[{index + 1}/6] {name}: xong ({entry['seconds']:.1f} s)")
            persist(state_path, state)
            if name == "matching":
                try:
                    selections(directory, options.allow_suggested)
                except MissingSelectionError as error:
                    lines = str(error).splitlines()[1:]
                    log(f"Cần duyệt {len(lines)} cue:\n" + "\n".join(lines[:10]))
                    log(f"Review: {directory / 'review.html'}")
                    log(f'python -m bin_finder run "{script}" -o "{directory}" --decisions D.json --resume')
                    log("Hoặc: --allow-suggested --resume")
                    entry["status"] = "needs_review"
                    state["status"] = "needs_review"
                    exit_code = 4
                    break
            if name in ("qa", "export") and not entry["summary"].get("passed"):
                if name == "qa" and not options.no_export and export_can_fix(entry["summary"]):
                    log("Loudness sẽ được chuẩn hóa ở bước export")
                    continue
                if options.strict_qa or name == "export" or not options.no_export:
                    state["status"] = "blocked"
                    entry["status"] = "blocked"
                    if name == "qa" and not options.no_export:
                        state["steps"][5]["status"] = "blocked"
                    if name == "export":
                        (directory / "final.mp4").unlink(missing_ok=True)
                    exit_code = 3
                    break
        except Exception as error:
            message = step_error(name, error)
            with (directory / "run.log").open("a", encoding="utf-8") as logfile:
                sys.stdout.flush()
                logfile.write(redact_text(traceback.format_exc()))
            entry.update(status="failed", finished_at=now(), seconds=perf_counter() - started,
                         error={"type": type(error).__name__, "message": message})
            state["status"] = "failed"
            log(f"{name}: {message}; tiếp tục bằng --resume")
            exit_code = 1
            break
    state.update(finished_at=now(), exit_code=exit_code)
    if exit_code == 0:
        state["status"] = "completed"
    persist(state_path, state)
    return exit_code
