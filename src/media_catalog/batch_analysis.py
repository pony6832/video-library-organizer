from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

from .analysis_mode import AnalysisMode
from .database import CatalogDatabase
from .excel_catalog import ExcelCheckpoint, write_excel
from .force_gemini import plan_force_run
from .inference import AnalysisError
from .models import MediaRecord, Status, has_complete_analysis
from .processor import Analyzer
from .source_guard import (
    SourceIntegrityError,
    capture_source,
    sanitize_error,
    verify_record_source,
)
from .segment_pipeline import SafeStopRequested
from .stage_runner import HeartbeatThread
from .workspace import MediaWorkspace


ProgressCallback = Callable[[int, int, MediaRecord], None]

_CLOUD_WARNING_PREFIXES = ("Gemini 強化失敗", "Gemini model discovery failed:")


def _is_cloud_warning(record: MediaRecord) -> bool:
    return (
        record.status is Status.ANALYZED
        and bool(record.error)
        and record.error.startswith(_CLOUD_WARNING_PREFIXES)
    )


class _RunTally:
    """Completed/failed counts kept incrementally.

    Re-reading the whole catalog after every item made a run O(N^2); with
    tens of thousands of records the bookkeeping dwarfed the analysis.
    """

    def __init__(
        self,
        records: Iterable[MediaRecord],
        force_eligible_ids: set[str] | None,
    ) -> None:
        self._force_eligible_ids = force_eligible_ids
        self._completed: set[str] = set()
        self._failed: set[str] = set()
        self.last_cloud_warning: str | None = None
        for record in records:
            self.update(record)

    def update(self, record: MediaRecord) -> None:
        eligible = (
            self._force_eligible_ids is None
            or record.id in self._force_eligible_ids
        )
        is_media = record.media_type.startswith(("image/", "video/"))
        if is_media and (has_complete_analysis(record) or not eligible):
            self._completed.add(record.id)
        else:
            self._completed.discard(record.id)
        if eligible and (record.status is Status.FAILED or _is_cloud_warning(record)):
            self._failed.add(record.id)
        else:
            self._failed.discard(record.id)
        if record.error and record.error.startswith(_CLOUD_WARNING_PREFIXES):
            self.last_cloud_warning = record.error

    @property
    def completed(self) -> int:
        return len(self._completed)

    @property
    def failed(self) -> int:
        return len(self._failed)


@dataclass(frozen=True, slots=True)
class BatchAnalysisResult:
    analyzed: int
    failed: int
    skipped: int
    remaining: int
    excel_sync_pending: bool = False


def analyze_pending(
    workspace: MediaWorkspace,
    analyzer: Analyzer,
    *,
    excel_writer: Callable[[Iterable[MediaRecord], Path], Path] = write_excel,
    progress: ProgressCallback | None = None,
    mode: AnalysisMode = AnalysisMode.AUTO,
    run_id: str | None = None,
    reviewed_paths: set[str] | None = None,
    video_only: bool = False,
) -> BatchAnalysisResult:
    database = CatalogDatabase(workspace.database_path)
    def scoped_records() -> list[MediaRecord]:
        return [r for r in database.list_records() if not video_only or r.media_type.startswith("video/")]

    initial_records = scoped_records()
    analyzed = 0
    completed = 0
    run_state = getattr(analyzer, "run_state", None)
    segment_pipeline = getattr(analyzer, "segment_pipeline", None)
    active_run_id = run_id
    excel_sync_pending = False
    if run_state is not None and segment_pipeline is not None:
        video_count = sum(
            record.media_type.startswith("video/") for record in initial_records
        )
        image_count = sum(
            record.media_type.startswith("image/") for record in initial_records
        )
        _, _, total_bytes = database.media_summary(video_only=video_only)
        if active_run_id is None:
            run, _ = run_state.begin_run(
                root_path=workspace.root,
                video_count=video_count,
                image_count=image_count,
                total_bytes=total_bytes,
                mode=mode,
            )
            active_run_id = run.run_id
            # A standalone invocation explicitly resumes work. Supplied worker
            # runs inherit the supervisor's stop flag, including startup races.
            run_state.clear_stop(active_run_id)

    gemini_client = getattr(segment_pipeline, "gemini_client", None)
    if run_state is not None and active_run_id is not None and gemini_client is not None:
        run_state.set_gemini_model(active_run_id, None)
        run_state.set_gemini_error(active_run_id, None)
    if gemini_client is not None and gemini_client.is_configured:
        try:
            discovery_heartbeat = (
                HeartbeatThread(run_state, active_run_id)
                if run_state is not None and active_run_id is not None
                else nullcontext()
            )
            with discovery_heartbeat:
                selected_model = gemini_client.discover_model()
        except Exception as error:
            safe_error = sanitize_error(str(error))
            if run_state is not None and active_run_id is not None:
                run_state.set_gemini_error(active_run_id, safe_error)
            if mode is AnalysisMode.FORCE_GEMINI:
                raise AnalysisError(f"Gemini model discovery failed: {safe_error}") from error
            gemini_client.discovery_error = safe_error
        else:
            if run_state is not None and active_run_id is not None:
                run_state.set_gemini_model(active_run_id, selected_model)

    if run_state is not None and active_run_id is not None:
        active_run = run_state.get_run(active_run_id)
        if active_run is not None and active_run.stop_requested:
            run_state.update_counts(
                active_run_id,
                completed_media=sum(has_complete_analysis(r) for r in initial_records),
                failed_media=sum(r.status is Status.FAILED for r in initial_records),
                current_media_id=None,
                current_segment_id=None,
                status="incomplete",
            )
            return BatchAnalysisResult(
                analyzed=0,
                failed=sum(r.status is Status.FAILED for r in initial_records),
                skipped=len(initial_records),
                remaining=sum(not has_complete_analysis(r) for r in initial_records),
            )

    force_eligible_ids: set[str] | None = None
    if mode is AnalysisMode.FORCE_GEMINI:
        if run_state is None or active_run_id is None:
            raise AnalysisError("force Gemini mode requires persistent run state")
        estimate, eligible_ids = plan_force_run(
            initial_records, reviewed_paths or set(), video_only=video_only
        )
        del estimate
        force_eligible_ids = set(eligible_ids)
        active_run = run_state.get_run(active_run_id)
        if active_run is None:
            raise AnalysisError("force Gemini run state is missing")
        if active_run.analysis_mode is not AnalysisMode.FORCE_GEMINI:
            raise AnalysisError("run mode does not match force Gemini mode")
        if not active_run.force_prepared:
            eligible_records = {
                record.id: record
                for record in initial_records
                if record.id in force_eligible_ids
            }
            for identity in eligible_ids:
                record = eligible_records[identity]
                if record.media_type.startswith("video/"):
                    run_state.reset_video_for_force(
                        active_run_id, record.id
                    )
            database.requeue_for_force(eligible_ids)
            run_state.mark_force_prepared(active_run_id)
            initial_records = scoped_records()
        else:
            recoverable_ids = tuple(
                record.id
                for record in initial_records
                if record.id in force_eligible_ids
                and (
                    record.status
                    in {Status.PROCESSING, Status.FAILED, Status.SKIPPED}
                    or (
                        record.status
                        in {Status.ANALYZED, Status.COMPLETED}
                        and not has_complete_analysis(record)
                    )
                )
            )
            if recoverable_ids:
                database.requeue_for_force(recoverable_ids)
                initial_records = scoped_records()

    pending = [
        record
        for record in initial_records
        if record.status is Status.PENDING
        and (
            force_eligible_ids is None or record.id in force_eligible_ids
        )
    ]
    total = len(pending)

    def failed_count(records: Iterable[MediaRecord]) -> int:
        scoped = tuple(
            record
            for record in records
            if force_eligible_ids is None
            or record.id in force_eligible_ids
        )
        return sum(
            record.status is Status.FAILED or _is_cloud_warning(record)
            for record in scoped
        )

    def persist_cloud_warning(records: Iterable[MediaRecord]) -> None:
        if run_state is None or active_run_id is None:
            return
        warnings = [
            r.error for r in records
            if r.error and r.error.startswith(_CLOUD_WARNING_PREFIXES)
        ]
        if warnings:
            run_state.set_gemini_error(active_run_id, sanitize_error(warnings[-1]))

    def completed_count(records: Iterable[MediaRecord]) -> int:
        return sum(
            has_complete_analysis(record)
            or (
                force_eligible_ids is not None
                and record.id not in force_eligible_ids
            )
            for record in records
            if record.media_type.startswith(("image/", "video/"))
        )

    def sync_excel() -> None:
        nonlocal excel_sync_pending
        try:
            excel_writer(database.list_records(), workspace.excel_path)
        except PermissionError:
            if run_state is None or active_run_id is None:
                raise
            excel_sync_pending = True
            run_state.set_excel_sync_pending(active_run_id, True)
        else:
            if run_state is not None and active_run_id is not None:
                excel_sync_pending = False
                run_state.set_excel_sync_pending(active_run_id, False)

    tally = _RunTally(initial_records, force_eligible_ids)
    persisted_cloud_warning: list[str | None] = [None]
    checkpoint_excel = ExcelCheckpoint(sync_excel)

    def update_run(current_media_id: str | None = None) -> None:
        if current_media_id is not None:
            current = database.get_record(current_media_id)
            if current is not None:
                tally.update(current)
        if run_state is None or active_run_id is None:
            return
        warning = tally.last_cloud_warning
        if warning and warning != persisted_cloud_warning[0]:
            run_state.set_gemini_error(active_run_id, sanitize_error(warning))
            persisted_cloud_warning[0] = warning
        run_state.update_counts(
            active_run_id,
            completed_media=tally.completed,
            failed_media=tally.failed,
            current_media_id=current_media_id,
            current_segment_id=None,
            status="running",
        )

    heartbeat = (
        HeartbeatThread(run_state, active_run_id)
        if run_state is not None and active_run_id is not None
        else nullcontext()
    )
    with heartbeat:
        for record in pending:
            if run_state is not None and active_run_id is not None:
                run = run_state.get_run(active_run_id)
                if run is not None and run.stop_requested:
                    break
            try:
                snapshot = capture_source(record.path)
                verify_record_source(record, snapshot)
            except (OSError, SourceIntegrityError) as error:
                database.set_status(
                    record.id,
                    Status.FAILED,
                    error=sanitize_error(str(error)),
                )
                completed += 1
                checkpoint_excel(completed)
                update_run(record.id)
                if progress is not None:
                    current = database.get_record(record.id)
                    assert current is not None
                    progress(completed, total, current)
                continue

            database.set_status(record.id, Status.PROCESSING)
            update_run(record.id)
            try:
                warning = None
                if (
                    segment_pipeline is not None
                    and active_run_id is not None
                    and record.media_type.startswith("video/")
                ):
                    result = segment_pipeline.analyze_video(
                        record, active_run_id, mode=mode
                    )
                    warning = result.warning
                    if (
                        not warning
                        and gemini_client is not None
                        and gemini_client.discovery_error
                    ):
                        # Keep the real segment warning; only fall back to
                        # the run-wide discovery failure when there is none.
                        warning = f"Gemini model discovery failed: {gemini_client.discovery_error}"
                elif mode is AnalysisMode.FORCE_GEMINI:
                    forced = analyzer.force_image_analyzer.analyze(record.path)
                    result = forced.analysis
                    warning = forced.warning
                else:
                    result = analyzer.analyze(record.path)
                verify_record_source(record, snapshot)
            except SafeStopRequested:
                database.set_status(record.id, Status.PENDING)
                update_run(record.id)
                break
            except (AnalysisError, OSError, SourceIntegrityError) as error:
                database.set_status(
                    record.id,
                    Status.FAILED,
                    error=sanitize_error(str(error)),
                )
            else:
                try:
                    database.save_analysis(
                        record.id,
                        description=result.description,
                        highlights=result.highlights,
                        keywords=result.keywords,
                        warning=warning,
                    )
                except ValueError as error:
                    # Whitespace-only model output must fail this item, not
                    # crash the worker with the record stuck in PROCESSING.
                    database.set_status(
                        record.id,
                        Status.FAILED,
                        error=sanitize_error(str(error)),
                    )
                else:
                    analyzed += 1
            completed += 1
            checkpoint_excel(completed)
            update_run(record.id)
            if progress is not None:
                current = database.get_record(record.id)
                assert current is not None
                progress(completed, total, current)

        sync_excel()

    final_records = scoped_records()
    persist_cloud_warning(final_records)
    failed = failed_count(final_records)
    remaining = sum(
        not has_complete_analysis(record)
        for record in final_records
        if force_eligible_ids is None or record.id in force_eligible_ids
    )
    if run_state is not None and active_run_id is not None:
        run_state.update_counts(
            active_run_id,
            completed_media=completed_count(final_records),
            failed_media=failed,
            current_media_id=None,
            current_segment_id=None,
            status=(
                "completed"
                if remaining == 0 and not excel_sync_pending
                else "incomplete"
            ),
        )
    return BatchAnalysisResult(
        analyzed=analyzed,
        failed=failed,
        skipped=len(initial_records) - len(pending),
        remaining=remaining,
        excel_sync_pending=excel_sync_pending,
    )
