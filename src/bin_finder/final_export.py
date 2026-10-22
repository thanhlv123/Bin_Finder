"""Explicit READY-only materialization of approved footage; no Qt or network."""
from __future__ import annotations

import csv
import json
import math
import re
import shutil
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from bin_finder.acceptance import AcceptanceReport, evaluate_project
from bin_finder.acquisition.service import _provenance, _safe_text
from bin_finder.analysis.fingerprint import fingerprint_file
from bin_finder.analysis.probe import FFprobeMediaProbe
from bin_finder.clips.extractor import FfmpegClipExtractor
from bin_finder.clips.models import ClipPolicy, ClipProposal
from bin_finder.final_selection import build_final_project
from bin_finder.handoff import HANDOFF_FILENAME, build_handoff, verify_handoff_package
from bin_finder.integration_adapter import write_integration_package
from bin_finder.models import CandidateRecord, FootageProject

FORMAT = "bin_finder_final_export_v1"


@dataclass(frozen=True)
class ExportOptions:
    csv_index: bool = True
    integration_adapter: bool = False
    scene_id_filenames: bool = True
    include_metadata: bool = True
    handoff: bool = False  # F017 portable _bin_finder_handoff.json, built inside staging


@dataclass(frozen=True)
class ExportProgress:
    completed: int
    total: int
    scene_id: str


@dataclass(frozen=True)
class FinalExportResult:
    status: str
    readiness: AcceptanceReport
    clip_paths: tuple[Path, ...] = ()
    manifest_path: Path | None = None
    csv_path: Path | None = None
    adapter_paths: tuple[Path, ...] = ()
    exported_count: int = 0
    total_duration: float = 0.0
    error: str = ""
    handoff_path: Path | None = None


class _Cancelled(Exception):
    pass


def _regular(path):
    # Reject links/junctions in every component, including directory aliases.
    return (not any(p.is_symlink() or p.is_junction() for p in (path, *path.parents))
            and path.is_file())


def _filename(scene_id, index, use_id):
    safe = bool(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", scene_id))
    reserved = scene_id.upper() in {"CON", "PRN", "AUX", "NUL", *(
        f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(1, 10))}
    return (scene_id if use_id and safe and not reserved else f"scene_{index:03d}") + ".mp4"


def _final_provenance(clip):
    candidate = CandidateRecord(clip.clip_id, clip.scene_id, clip.provider,
        clip.source_id, clip.title, clip.duration, clip.final_score,
        clip.rights_status, source_url=clip.source_url, creator=clip.creator,
        source_metadata=clip.source_metadata)
    provenance = _provenance(candidate)
    safe = provenance["source_metadata"]
    # These are F014 evidence fields, not arbitrary provider metadata. Retain
    # approved rendition identity rather than synthesizing a new empty-URL ID.
    for key in ("duplicate_group", "proposal_unit_id", "verification_provider"):
        if key in clip.source_metadata:
            safe[key] = _safe_text(clip.source_metadata[key])
    rendition = clip.source_metadata.get("selected_rendition")
    if isinstance(rendition, dict):
        identifier = rendition.get("identifier")
        width, height = rendition.get("width"), rendition.get("height")
        if (isinstance(identifier, str) and re.fullmatch(r"[a-fA-F0-9]{64}", identifier)
                and type(width) is int and width >= 0
                and type(height) is int and height >= 0):
            safe["selected_rendition"] = dict(identifier=identifier, width=width, height=height)
    return provenance


def _validate_materialized(original, report, materialized, stage):
    """Check linkage using staged bytes and final paths, without reinterpreting ranges.

    F010's original-source report authorizes the run. Materialized timestamps are
    coordinates within independent trimmed files, not within provider sources.
    """
    def scene_keys(project):
        return [(s.scene_id, s.order) for s in project.scenes]
    if (not report.ready or report.project_id != original.project_id
            or materialized.project_id != original.project_id
            or scene_keys(original) != scene_keys(materialized)
            or report.scene_count != len(original.scenes)
            or report.selected_count != len(original.selected_clips)
            or len(original.selected_clips) != len(materialized.selected_clips)
            or [(s.scene_id, s.scene_order) for s in report.scenes] != scene_keys(original)):
        raise ValueError("materialized-project-mismatch")
    report_clips = {s.scene_id: s.clip_id for s in report.scenes if s.selected}
    for original_clip, clip in zip(original.selected_clips, materialized.selected_clips):
        if (any(getattr(original_clip, key) != getattr(clip, key) for key in
                ("clip_id", "scene_id", "scene_order", "provider", "source_id",
                 "semantic_score", "vlm_score", "final_score"))
                or report_clips.get(clip.scene_id) != clip.clip_id
                or not math.isfinite(clip.duration)
                or not math.isclose(original_clip.duration, clip.duration, abs_tol=1e-6)
                or clip.start != 0.0 or clip.end != clip.duration):
            raise ValueError("materialized-clip-mismatch")
        relative = Path(clip.local_file).relative_to(materialized.output_dir)
        staged_file = stage / relative
        if ".." in relative.parts or not _regular(staged_file) or staged_file.stat().st_size == 0:
            raise ValueError("materialized-file-missing")
    if not math.isclose(report.selected_duration_seconds,
                        sum(c.duration for c in materialized.selected_clips), abs_tol=1e-6):
        raise ValueError("materialized-duration-mismatch")


class FinalExportService:
    def __init__(self, extractor=None, probe=None):
        self.extractor = extractor or FfmpegClipExtractor()
        self.probe = probe or FFprobeMediaProbe()

    def export(self, project_id, scenes, selections, destination, options=None,
               progress=None, cancelled=None):
        options = options or ExportOptions()
        project = build_final_project(project_id, scenes, selections, destination)
        report = evaluate_project(project)
        if not report.ready:
            return FinalExportResult("not_ready", report)
        stage = None
        try:
            requested = Path(destination).expanduser().absolute()
            if any(p.is_symlink() or p.is_junction() for p in (requested, *requested.parents)):
                raise ValueError("destination-is-link")
            root = requested.resolve()
            repository = Path(__file__).resolve().parents[2]
            if root == repository or repository in root.parents:
                raise ValueError("output-inside-source-tree")
            # Destination is the completed library itself. An empty GUI-selected
            # folder is allowed, but never replace a nonempty directory or file.
            if root.exists() and (not root.is_dir() or any(root.iterdir())):
                raise ValueError("destination-exists")
            if len({s.scene_id for s in project.scenes}) != len(project.scenes):
                raise ValueError("duplicate-scene")
            names = [_filename(c.scene_id, i, options.scene_id_filenames)
                     for i, c in enumerate(project.selected_clips, 1)]
            if len({n.casefold() for n in names}) != len(names):
                raise ValueError("filename-collision")
            def checkpoint():
                if cancelled and cancelled():
                    raise _Cancelled()
            checkpoint()
            root.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix=".bin-finder-export-partial-", dir=root.parent))
            (stage / "footage").mkdir()
            rows, materialized = [], []
            policy = ClipPolicy()
            for index, (clip, name) in enumerate(zip(project.selected_clips, names), 1):
                checkpoint()
                source = Path(clip.local_file).expanduser().absolute()
                if not _regular(source):
                    raise ValueError("source-not-regular")
                if (not all(math.isfinite(v) for v in (clip.start, clip.end, clip.duration))
                        or clip.start < 0 or clip.end <= clip.start
                        or not math.isclose(clip.duration, clip.end - clip.start, abs_tol=1e-6)
                        or not policy.min_duration <= clip.duration <= policy.max_duration):
                    raise ValueError("invalid-range")
                if not all(math.isfinite(v) and 0 <= v <= 1 for v in
                           (clip.semantic_score, clip.vlm_score, clip.final_score)):
                    raise ValueError("invalid-score")
                original_hash = fingerprint_file(source).sha256
                approved_hash = clip.source_metadata.get("media_sha256")
                if approved_hash is not None and approved_hash != original_hash:
                    raise ValueError("source-sha256-changed")
                if progress:
                    progress(ExportProgress(index - 1, len(names), clip.scene_id))
                proposal = ClipProposal(clip.clip_id, str(source), clip.start, clip.end,
                                        clip.final_score, True, "explicit-final-approval")
                output = stage / "footage" / name
                extracted = self.extractor.extract(proposal, output, overwrite=False)
                if (not _regular(output) or output.stat().st_size == 0
                        or Path(extracted.output_path).resolve() != output.resolve()
                        or extracted.bytes_written != output.stat().st_size
                        or not math.isfinite(extracted.duration)
                        or not math.isclose(extracted.duration, clip.duration, abs_tol=1e-6)):
                    raise ValueError("invalid-extraction-result")
                if self.probe.executable:
                    metadata = self.probe.probe(output)
                    if (not math.isfinite(metadata.duration) or metadata.width <= 0
                            or abs(metadata.duration - clip.duration) > 0.25):
                        raise ValueError("output-duration-mismatch")
                if not _regular(source) or fingerprint_file(source).sha256 != original_hash:
                    raise ValueError("source-changed-during-export")
                checkpoint()
                exported_hash = fingerprint_file(output).sha256
                provenance = _final_provenance(clip)
                row = dict(scene_id=_safe_text(clip.scene_id), scene_order=clip.scene_order,
                    clip_id=_safe_text(clip.clip_id), exported_path=f"footage/{name}",
                    filename=name, provider=_safe_text(clip.provider),
                    source_id=provenance["source_id"],
                    original_source_start_seconds=clip.start,
                    original_source_end_seconds=clip.end,
                    duration=clip.duration, exported_file_sha256=exported_hash,
                    original_source_media_sha256=original_hash,
                    semantic_score=clip.semantic_score, vlm_score=clip.vlm_score,
                    final_score=clip.final_score, rights_status=provenance["rights_status"],
                    creator=provenance["creator"])
                if options.include_metadata:
                    row.update(source_url=provenance["source_url"],
                               source_metadata=provenance["source_metadata"])
                rows.append(row)
                materialized.append(replace(clip, local_file=str(root / "footage" / name),
                    start=0.0, end=clip.duration, title=_safe_text(clip.title),
                    provider=_safe_text(clip.provider), source_id=provenance["source_id"],
                    creator=provenance["creator"], rights_status=provenance["rights_status"],
                    source_url=provenance["source_url"], source_metadata={
                        **provenance["source_metadata"], "media_sha256": exported_hash,
                        "f015_original_source_start_seconds": clip.start,
                        "f015_original_source_end_seconds": clip.end,
                        "f015_original_media_sha256": original_hash,
                        "f015_exported_media_sha256": exported_hash,
                        "f015_materialized": True}))
                if progress:
                    progress(ExportProgress(index, len(names), clip.scene_id))
            payload = dict(format=FORMAT, project_id=_safe_text(project_id),
                exported_at=datetime.now(timezone.utc).isoformat(), scene_count=len(project.scenes),
                selected_count=len(rows), exported_count=len(rows),
                total_duration=sum(c.duration for c in project.selected_clips),
                readiness=report.to_dict(), clips=rows)
            (stage / "footage_manifest.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            if options.csv_index:
                columns = ("scene_order", "scene_id", "clip_id", "filename", "provider",
                           "source_id", "duration", "final_score", "rights_status", "creator")
                with (stage / "footage_index.csv").open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(rows)
            adapters = ()
            if options.integration_adapter:
                final_project = FootageProject(project.project_id, root, project.scenes, materialized)
                _validate_materialized(project, report, final_project, stage)
                adapters = write_integration_package(stage, final_project, report)
            if options.handoff:
                ordered = sorted(project.scenes, key=lambda s: (s.order, s.scene_id))
                build_handoff(project_id, ordered, rows, stage,
                              include_metadata=options.include_metadata)
                try:
                    verify_handoff_package(stage)  # the producer must satisfy its own verifier
                except Exception:
                    raise ValueError("handoff-invalid") from None
            checkpoint()
            if root.exists():
                root.rmdir()  # only an empty directory; a concurrent writer makes this fail
            stage.rename(root)  # Windows refuses an existing destination
            stage = None
            return FinalExportResult("success", report,
                tuple(root / "footage" / name for name in names), root / "footage_manifest.json",
                root / "footage_index.csv" if options.csv_index else None,
                tuple(root / p.name for p in adapters), len(rows), payload["total_duration"],
                handoff_path=root / HANDOFF_FILENAME if options.handoff else None)
        except _Cancelled:
            return FinalExportResult("cancelled", report)
        except Exception as error:
            # Avoid leaking subprocess output, source paths or arbitrary provider data.
            code = str(error) if type(error) is ValueError and re.fullmatch(r"[a-z0-9-]+", str(error)) else "export-failed"
            return FinalExportResult("failed", report, error=code)
        finally:
            if stage is not None:
                shutil.rmtree(stage)
