from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .database import CatalogDatabase
from .excel_catalog import write_excel
from .scanner import ScanResult, scan
from .workspace import MediaWorkspace


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    workspace: MediaWorkspace
    scan: ScanResult
    total_records: int


def bootstrap_workspace(root: Path, *, video_only: bool = False) -> BootstrapResult:
    workspace = MediaWorkspace.from_root(root)
    workspace.ensure_directories()

    database = CatalogDatabase(workspace.database_path)
    def checkpoint(count: int) -> None:
        if count % 100 == 0:
            write_excel(database.list_records(), workspace.excel_path)

    scan_result = scan(
        workspace.root,
        database,
        excluded_roots=(workspace.result_root,),
        video_only=video_only,
        on_record=checkpoint,
    )
    records = database.list_records()
    write_excel(records, workspace.excel_path)

    return BootstrapResult(
        workspace=workspace,
        scan=scan_result,
        total_records=sum(r.media_type.startswith("video/") for r in records) if video_only else len(records),
    )
