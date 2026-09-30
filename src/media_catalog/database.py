from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .models import MediaRecord, Status, has_complete_analysis
from .sqlite_utils import connect as sqlite_connect

if TYPE_CHECKING:
    from .schema_migration import MigrationResult


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CatalogDatabase:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._create_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite_connect(self.db_path)

    def _create_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS media_records (
                    id TEXT PRIMARY KEY,
                    normalized_path TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    description TEXT,
                    highlights_json TEXT NOT NULL DEFAULT '[]',
                    keywords_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    markdown_path TEXT,
                    backup_path TEXT,
                    discovered_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(normalized_path, fingerprint)
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(media_records)")
            }
            # Size and mtime let a rescan skip re-hashing unchanged files.
            if "source_size" not in columns:
                connection.execute(
                    "ALTER TABLE media_records ADD COLUMN source_size INTEGER"
                )
            if "source_mtime_ns" not in columns:
                connection.execute(
                    "ALTER TABLE media_records ADD COLUMN source_mtime_ns INTEGER"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS media_records_path_nocase "
                "ON media_records (normalized_path COLLATE NOCASE)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS media_records_fingerprint "
                "ON media_records (fingerprint)"
            )

    def prepare_a_plus_schema(
        self, excel_path: Path | None = None
    ) -> MigrationResult:
        from .schema_migration import ensure_a_plus_schema

        return ensure_a_plus_schema(self.db_path, excel_path)

    def upsert_discovered(
        self,
        path: Path,
        fingerprint: str,
        media_type: str,
        *,
        size: int | None = None,
        mtime_ns: int | None = None,
    ) -> MediaRecord:
        (record,) = self.upsert_discovered_many(
            [(path, fingerprint, media_type, size, mtime_ns)]
        )
        return record

    def upsert_discovered_many(
        self,
        entries: Sequence[tuple[Path, str, str, int | None, int | None]],
    ) -> list[MediaRecord]:
        """Insert or refresh scanned files in one transaction.

        Paths match case-insensitively (NTFS semantics), so renaming a folder
        from "Trip" to "trip" updates the existing row instead of duplicating
        it. A new row whose content already has a complete analysis elsewhere
        (a moved or copied file) reuses that analysis instead of paying again.
        """
        records: list[MediaRecord] = []
        with self._connect() as connection:
            for path, fingerprint, media_type, size, mtime_ns in entries:
                normalized_path = str(Path(path).resolve())
                row = connection.execute(
                    """
                    SELECT * FROM media_records
                    WHERE normalized_path = ? COLLATE NOCASE AND fingerprint = ?
                    ORDER BY discovered_at, id
                    LIMIT 1
                    """,
                    (normalized_path, fingerprint),
                ).fetchone()
                timestamp = _now()
                if row is None:
                    record_id = str(uuid.uuid4())
                    connection.execute(
                        """
                        INSERT INTO media_records (
                            id, normalized_path, fingerprint, media_type, status,
                            discovered_at, updated_at, source_size, source_mtime_ns
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record_id,
                            normalized_path,
                            fingerprint,
                            media_type,
                            Status.PENDING.value,
                            timestamp,
                            timestamp,
                            size,
                            mtime_ns,
                        ),
                    )
                    self._reuse_existing_analysis(
                        connection, record_id, fingerprint
                    )
                else:
                    record_id = row["id"]
                    status = row["status"]
                    if status == Status.MISSING.value:
                        status = (
                            Status.ANALYZED.value
                            if _row_has_analysis(row)
                            else Status.PENDING.value
                        )
                    connection.execute(
                        """
                        UPDATE media_records
                        SET normalized_path = ?, status = ?,
                            source_size = ?, source_mtime_ns = ?
                        WHERE id = ?
                        """,
                        (normalized_path, status, size, mtime_ns, record_id),
                    )
                current = connection.execute(
                    "SELECT * FROM media_records WHERE id = ?", (record_id,)
                ).fetchone()
                records.append(self._to_record(current))
        return records

    @staticmethod
    def _reuse_existing_analysis(
        connection: sqlite3.Connection, record_id: str, fingerprint: str
    ) -> None:
        donors = connection.execute(
            """
            SELECT * FROM media_records
            WHERE fingerprint = ? AND id != ?
              AND status IN (?, ?, ?)
            ORDER BY updated_at DESC
            """,
            (
                fingerprint,
                record_id,
                Status.ANALYZED.value,
                Status.COMPLETED.value,
                Status.MISSING.value,
            ),
        ).fetchall()
        donor = next((row for row in donors if _row_has_analysis(row)), None)
        if donor is None:
            return
        connection.execute(
            """
            UPDATE media_records
            SET status = ?, description = ?, highlights_json = ?,
                keywords_json = ?, error = NULL
            WHERE id = ?
            """,
            (
                Status.ANALYZED.value,
                donor["description"],
                donor["highlights_json"],
                donor["keywords_json"],
                record_id,
            ),
        )

    def scan_index(self) -> dict[str, tuple[str, int | None, int | None]]:
        """Newest known (fingerprint, size, mtime_ns) per case-folded path."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT normalized_path, fingerprint, source_size, source_mtime_ns
                FROM media_records
                WHERE status != ?
                ORDER BY updated_at, discovered_at
                """,
                (Status.MISSING.value,),
            ).fetchall()
        return {
            row["normalized_path"].casefold(): (
                row["fingerprint"],
                row["source_size"],
                row["source_mtime_ns"],
            )
            for row in rows
        }

    def mark_missing_sources(
        self,
        seen: dict[str, str],
        *,
        scanned_types: tuple[str, ...] = ("image/", "video/"),
    ) -> int:
        """Retire rows whose source is gone or was replaced by newer content.

        ``seen`` maps case-folded paths found by the scan to their fingerprint.
        A row whose path was not seen is only retired when the file really no
        longer exists, so an unreadable folder never loses its rows.
        """
        retired: list[str] = []
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, normalized_path, fingerprint, media_type "
                "FROM media_records WHERE status != ?",
                (Status.MISSING.value,),
            ).fetchall()
            for row in rows:
                if not row["media_type"].startswith(scanned_types):
                    continue
                current = seen.get(row["normalized_path"].casefold())
                if current is not None:
                    if current != row["fingerprint"]:
                        retired.append(row["id"])
                elif not Path(row["normalized_path"]).exists():
                    retired.append(row["id"])
            timestamp = _now()
            connection.executemany(
                "UPDATE media_records SET status = ?, updated_at = ? WHERE id = ?",
                [(Status.MISSING.value, timestamp, identity) for identity in retired],
            )
        return len(retired)

    def get_record(self, record_id: str) -> MediaRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM media_records WHERE id = ?", (record_id,)
            ).fetchone()
        return self._to_record(row) if row is not None else None

    def list_records(self, *, include_missing: bool = False) -> list[MediaRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM media_records WHERE ? OR status != ? "
                "ORDER BY discovered_at, id",
                (int(include_missing), Status.MISSING.value),
            ).fetchall()
        return [self._to_record(row) for row in rows]

    def media_summary(self, *, video_only: bool = False) -> tuple[int, int, int]:
        """(video count, image count, total source bytes) in one query.

        Uses the sizes stored by the scan instead of a stat() per record,
        which froze the UI every second on large NAS/USB catalogs.
        """
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COALESCE(SUM(media_type LIKE 'video/%'), 0) AS videos,
                    COALESCE(SUM(media_type LIKE 'image/%'), 0) AS images,
                    COALESCE(SUM(source_size), 0) AS bytes
                FROM media_records
                WHERE status != ? AND (? = 0 OR media_type LIKE 'video/%')
                """,
                (Status.MISSING.value, int(video_only)),
            ).fetchone()
        return int(row["videos"]), int(row["images"]), int(row["bytes"])

    def list_by_status(self, statuses: Sequence[Status]) -> list[MediaRecord]:
        if not statuses:
            return []
        placeholders = ", ".join("?" for _ in statuses)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM media_records WHERE status IN ({placeholders}) "
                "ORDER BY discovered_at, id",
                tuple(status.value for status in statuses),
            ).fetchall()
        return [self._to_record(row) for row in rows]

    def requeue_processing(self, *, video_only: bool = False) -> int:
        return self._requeue_status(Status.PROCESSING, video_only=video_only)

    def requeue_failed(self, *, video_only: bool = False) -> int:
        return self._requeue_status(Status.FAILED, video_only=video_only)

    def _requeue_status(self, status: Status, *, video_only: bool) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE media_records
                SET status = ?, error = NULL, updated_at = ?
                WHERE status = ? AND (? = 0 OR media_type LIKE 'video/%')
                """,
                (
                    Status.PENDING.value,
                    _now(),
                    status.value,
                    int(video_only),
                ),
            )
        return cursor.rowcount

    def requeue_incomplete_analysis(self, *, video_only: bool = False) -> int:
        incomplete = [
            record
            for record in self.list_records()
            if not video_only or record.media_type.startswith('video/')
            if record.status is Status.SKIPPED
            or (
                record.status in {Status.ANALYZED, Status.COMPLETED}
                and not has_complete_analysis(record)
            )
        ]
        for record in incomplete:
            self.set_status(record.id, Status.PENDING)
        return len(incomplete)

    def requeue_for_force(self, record_ids: Sequence[str]) -> int:
        identities = tuple(dict.fromkeys(record_ids))
        if not identities:
            return 0
        placeholders = ", ".join("?" for _ in identities)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE media_records
                SET status = ?, error = NULL, updated_at = ?
                WHERE id IN ({placeholders})
                """,
                (Status.PENDING.value, _now(), *identities),
            )
        return cursor.rowcount

    def set_status(
        self, record_id: str, status: Status, *, error: str | None = None
    ) -> MediaRecord:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE media_records
                SET status = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status.value, error, _now(), record_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown media record: {record_id}")
        record = self.get_record(record_id)
        assert record is not None
        return record

    def save_analysis(
        self,
        record_id: str,
        *,
        description: str,
        highlights: tuple[str, ...],
        keywords: tuple[str, ...],
        warning: str | None = None,
    ) -> MediaRecord:
        cleaned_description = description.strip()
        cleaned_highlights = tuple(
            item.strip() for item in highlights if item.strip()
        )
        cleaned_keywords = tuple(
            item.strip() for item in keywords if item.strip()
        )
        if not cleaned_description or not cleaned_highlights or not cleaned_keywords:
            raise ValueError("Analysis fields must all contain useful text")
        cleaned_warning = (
            " ".join(warning.replace("\r", " ").replace("\n", " ").split())[:240]
            if warning
            else None
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE media_records
                SET status = ?, description = ?, highlights_json = ?,
                    keywords_json = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    Status.ANALYZED.value,
                    cleaned_description,
                    json.dumps(cleaned_highlights, ensure_ascii=False),
                    json.dumps(cleaned_keywords, ensure_ascii=False),
                    cleaned_warning,
                    _now(),
                    record_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown media record: {record_id}")
        record = self.get_record(record_id)
        assert record is not None
        return record

    @staticmethod
    def _to_record(row: sqlite3.Row) -> MediaRecord:
        return MediaRecord(
            id=row["id"],
            path=Path(row["normalized_path"]),
            fingerprint=row["fingerprint"],
            media_type=row["media_type"],
            status=Status(row["status"]),
            description=row["description"],
            highlights=tuple(json.loads(row["highlights_json"])),
            keywords=tuple(json.loads(row["keywords_json"])),
            error=row["error"],
            markdown_path=(Path(row["markdown_path"]) if row["markdown_path"] else None),
            backup_path=(Path(row["backup_path"]) if row["backup_path"] else None),
            discovered_at=row["discovered_at"],
            updated_at=row["updated_at"],
        )


def _row_has_analysis(row: sqlite3.Row) -> bool:
    description = row["description"]
    highlights = json.loads(row["highlights_json"] or "[]")
    keywords = json.loads(row["keywords_json"] or "[]")
    return (
        isinstance(description, str)
        and bool(description.strip())
        and bool(highlights)
        and all(isinstance(item, str) and item.strip() for item in highlights)
        and bool(keywords)
        and all(isinstance(item, str) and item.strip() for item in keywords)
    )
