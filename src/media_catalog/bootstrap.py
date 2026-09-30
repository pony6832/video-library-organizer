from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .database import CatalogDatabase
from .excel_catalog import ExcelCheckpoint, try_write_excel, write_excel
from .scanner import ScanResult, scan
from .workspace import MediaWorkspace


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    workspace: MediaWorkspace
    scan: ScanResult
    total_records: int
    excel_sync_pending: bool = False


def bootstrap_workspace(root: Path, *, video_only: bool = False) -> BootstrapResult:
    workspace = MediaWorkspace.from_root(root)
    workspace.ensure_directories()

    database = CatalogDatabase(workspace.database_path)
    def write(records) -> bool:
        return try_write_excel(records, workspace.excel_path, writer=write_excel)

    checkpoint = ExcelCheckpoint(lambda: write(database.list_records()))

    scan_result = scan(
        workspace.root,
        database,
        excluded_roots=(workspace.result_root,),
        video_only=video_only,
        on_record=checkpoint,
    )
    records = database.list_records()
    # An open workbook only delays the refresh; SQLite remains complete.
    written = write(records)

    return BootstrapResult(
        workspace=workspace,
        scan=scan_result,
        total_records=sum(r.media_type.startswith("video/") for r in records) if video_only else len(records),
        excel_sync_pending=not written,
    )
