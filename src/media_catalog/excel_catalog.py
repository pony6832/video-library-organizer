from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Callable, Iterable
import uuid
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError

from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.cell import WriteOnlyCell

from .models import MediaRecord, Status


CATALOG_HEADERS = (
    "狀態",
    "檔名",
    "完整路徑",
    "媒體類型",
    "內容描述",
    "重點",
    "關鍵字",
    "拍攝時間",
    "處理時間",
    "Markdown 路徑",
    "備份路徑",
    "錯誤原因",
)

_STATUS_LABELS = {
    Status.PENDING: "待處理",
    Status.PROCESSING: "處理中",
    Status.ANALYZED: "待確認",
    Status.COMPLETED: "完成",
    Status.SKIPPED: "略過",
    Status.FAILED: "失敗",
    Status.MISSING: "來源已移除",
}

_MEDIA_LABELS = {
    "image/jpeg": "照片 (JPEG)",
    "image/png": "照片 (PNG)",
    "image/webp": "照片 (WebP)",
    "image/heic": "照片 (HEIC)",
    "video/mp4": "影片 (MP4)",
    "video/quicktime": "影片 (MOV)",
    "video/x-matroska": "影片 (MKV)",
    "video/webm": "影片 (WebM)",
}


# Excel supports roughly 66,530 hyperlinks per worksheet; past that it asks to
# repair the workbook. Stay well below the limit and leave the path as text.
MAX_HYPERLINKS = 60_000

# Leftover temporary workbooks from a killed writer are swept after this age.
_STALE_TEMPORARY_SECONDS = 3600


class ReviewedPathsError(RuntimeError):
    pass


def read_reviewed_paths(excel_path: Path) -> set[str]:
    source = Path(excel_path)
    if not source.is_file():
        return set()
    try:
        workbook = load_workbook(source, read_only=True, data_only=True)
    except (BadZipFile, InvalidFileException):
        return set()
    try:
        sheet = workbook["媒體清冊"]
        headers = {
            cell.value: index
            for index, cell in enumerate(sheet[1], start=1)
            if isinstance(cell.value, str)
        }
        status_column = headers.get("狀態")
        path_column = headers.get("完整路徑")
        if status_column is None or path_column is None:
            return set()
        return {
            str(row[path_column - 1])
            for row in sheet.iter_rows(min_row=2, values_only=True)
            if len(row) >= max(status_column, path_column)
            and row[status_column - 1] == "已審核"
            and row[path_column - 1]
        }
    finally:
        workbook.close()


def read_reviewed_paths_strict(excel_path: Path) -> set[str]:
    source = Path(excel_path)
    if not source.is_file():
        raise ReviewedPathsError("找不到 Excel 媒體清冊")
    try:
        workbook = load_workbook(source, read_only=True, data_only=True)
    except PermissionError:
        raise
    except (OSError, BadZipFile, InvalidFileException, ParseError, KeyError, ValueError) as error:
        raise ReviewedPathsError("Excel 媒體清冊無法讀取") from error
    try:
        if "媒體清冊" not in workbook.sheetnames:
            raise ReviewedPathsError("Excel 缺少媒體清冊工作表")
        sheet = workbook["媒體清冊"]
        rows = sheet.iter_rows(values_only=True)
        headers = {
            value: index
            for index, value in enumerate(next(rows, ()))
            if isinstance(value, str)
        }
        status_column = headers.get("狀態")
        path_column = headers.get("完整路徑")
        if status_column is None or path_column is None:
            raise ReviewedPathsError("Excel 缺少狀態或完整路徑欄位")
        return {
            str(row[path_column])
            for row in rows
            if len(row) > max(status_column, path_column)
            and row[status_column] == "已審核"
            and row[path_column]
        }
    except (BadZipFile, ParseError, KeyError, ValueError) as error:
        raise ReviewedPathsError("Excel 媒體清冊內容損壞，請先修復或還原備份") from error
    finally:
        workbook.close()


def write_excel(records: Iterable[MediaRecord], output_path: Path) -> Path:
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    reviewed_paths = (
        {str(Path(path).resolve()).casefold() for path in read_reviewed_paths_strict(destination)}
        if destination.exists() else set()
    )

    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet()
    sheet.title = "媒體清冊"
    widths = (12, 28, 64, 18, 44, 36, 30, 20, 24, 54, 54, 40)
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"
    sheet.sheet_view.showGridLines = False
    header_fill = PatternFill("solid", fgColor="1F4E78")
    header = []
    for value in CATALOG_HEADERS:
        cell = WriteOnlyCell(sheet, value=value)
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center")
        header.append(cell)
    sheet.append(header)

    row_count = 0
    hyperlink_count = 0
    for record in records:
        # Catalog paths are stored resolved; avoid a resolve() syscall per row.
        source_path = (
            record.path if record.path.is_absolute() else record.path.resolve()
        )
        path_text = str(source_path)
        values = (
                (
                    "已審核"
                    if path_text.casefold() in reviewed_paths
                    else _STATUS_LABELS[record.status]
                ),
                record.path.name,
                path_text,
                _MEDIA_LABELS.get(record.media_type, record.media_type),
                record.description,
                "；".join(record.highlights),
                "、".join(record.keywords),
                None,
                (
                    record.updated_at
                    if record.status in {Status.ANALYZED, Status.COMPLETED}
                    else None
                ),
                str(record.markdown_path) if record.markdown_path else None,
                str(record.backup_path) if record.backup_path else None,
                record.error,
            )
        # Filenames and model output are data, even when they start with '='.
        row = []
        for value in values:
            cell = WriteOnlyCell(sheet, value=value)
            if isinstance(cell.value, str):
                cell.data_type = "s"
            row.append(cell)
        path_cell = row[2]
        if hyperlink_count < MAX_HYPERLINKS and source_path.is_file():
            path_cell.hyperlink = source_path.as_uri()
            path_cell.style = "Hyperlink"
            hyperlink_count += 1
        sheet.append(row)
        row_count += 1

    if row_count:
        review_validation = DataValidation(
            type="list",
            formula1='"待確認,已審核"',
            allow_blank=False,
            showDropDown=False,
        )
        review_validation.errorTitle = "無效狀態"
        review_validation.error = "請從下拉選單選擇待確認或已審核。"
        review_validation.showErrorMessage = True
        sheet.data_validations.append(review_validation)
        review_validation.add(f"A2:A{row_count + 1}")

    sheet.auto_filter.ref = f"A1:L{row_count + 1}"
    _sweep_stale_temporaries(destination)
    temporary = destination.with_name(
        f".{destination.stem}.{uuid.uuid4().hex}.tmp{destination.suffix}"
    )
    try:
        workbook.save(temporary)
        workbook.close()
        os.replace(temporary, destination)
    finally:
        workbook.close()
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass
    return destination


def _sweep_stale_temporaries(destination: Path) -> None:
    cutoff = time.time() - _STALE_TEMPORARY_SECONDS
    pattern = f".{destination.stem}.*.tmp{destination.suffix}"
    for leftover in destination.parent.glob(pattern):
        try:
            if leftover.stat().st_mtime < cutoff:
                leftover.unlink()
        except OSError:
            pass


def try_write_excel(
    records: Iterable[MediaRecord],
    output_path: Path,
    *,
    writer: Callable[[Iterable[MediaRecord], Path], Path] = write_excel,
) -> bool:
    """Write the catalog, returning False when Excel holds the file open.

    SQLite stays the source of truth, so a locked workbook only delays the
    refresh; the next successful write rebuilds it completely.
    """
    try:
        writer(records, output_path)
    except PermissionError:
        if not Path(output_path).exists():
            raise
        return False
    return True


class ExcelCheckpoint:
    """Refresh Excel every ``every_items`` items, but not more often than
    ``min_interval_seconds``; rewriting a large catalog every 100 items makes
    the total cost quadratic."""

    def __init__(
        self,
        write: Callable[[], object],
        *,
        every_items: int = 100,
        min_interval_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._write = write
        self._every_items = max(1, every_items)
        self._min_interval_seconds = max(0.0, min_interval_seconds)
        self._clock = clock
        self._last_write: float | None = None

    def __call__(self, count: int) -> None:
        if count % self._every_items:
            return
        now = self._clock()
        if (
            self._last_write is not None
            and now - self._last_write < self._min_interval_seconds
        ):
            return
        self._write()
        self._last_write = self._clock()
