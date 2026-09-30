from __future__ import annotations

import errno
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .database import CatalogDatabase
from .source_guard import sha256_file
from .workspace import is_link_stat, is_online_only_stat


SUPPORTED_MEDIA: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
}

# Rows are written in batches; Excel checkpoints fire on the same boundary.
_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class ScanResult:
    discovered: int
    existing: int
    supported: int
    unsupported: int
    unreadable: int = 0
    retired: int = 0


def _is_within_excluded(path: Path, excluded_roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    return any(
        resolved == excluded or excluded in resolved.parents
        for excluded in excluded_roots
    )


@dataclass(frozen=True, slots=True)
class _FoundFile:
    path: Path
    size: int
    mtime_ns: int


def _iter_files(
    root: Path,
    excluded_roots: tuple[Path, ...],
    on_unreadable: Callable[[], None] = lambda: None,
) -> Iterator[_FoundFile]:
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                ordered_entries = sorted(
                    entries, key=lambda entry: entry.name.casefold()
                )
        except OSError:
            # A protected or vanished folder must not abort the whole scan.
            on_unreadable()
            continue
        child_directories: list[Path] = []
        for entry in ordered_entries:
            try:
                entry_stat = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or is_link_stat(entry_stat):
                    continue
                is_directory = entry.is_dir(follow_symlinks=False)
                is_file = not is_directory and entry.is_file(follow_symlinks=False)
            except OSError:
                on_unreadable()
                continue
            path = Path(entry.path)
            if is_directory:
                if not _is_within_excluded(path, excluded_roots):
                    child_directories.append(path)
            elif is_file:
                if is_online_only_stat(entry_stat):
                    # Hashing an online-only cloud file would download it.
                    on_unreadable()
                    continue
                yield _FoundFile(path, entry_stat.st_size, entry_stat.st_mtime_ns)
        pending.extend(reversed(child_directories))


def scan(
    root: Path,
    database: CatalogDatabase,
    *,
    excluded_roots: Iterable[Path] = (),
    video_only: bool = False,
    on_record: Callable[[int], None] | None = None,
) -> ScanResult:
    resolved_root = Path(root).resolve()
    if not resolved_root.is_dir():
        raise FileNotFoundError(
            errno.ENOENT, os.strerror(errno.ENOENT), str(resolved_root)
        )

    index = database.scan_index()
    known = {(path, entry[0]) for path, entry in index.items()}
    exclusions = tuple(Path(path).resolve() for path in excluded_roots)
    discovered = 0
    existing = 0
    supported = 0
    unsupported = 0
    unreadable = 0
    seen: dict[str, str] = {}
    batch: list[tuple[Path, str, str, int, int]] = []

    def count_unreadable() -> None:
        nonlocal unreadable
        unreadable += 1

    def flush() -> None:
        if batch:
            database.upsert_discovered_many(batch)
            batch.clear()

    for found in _iter_files(resolved_root, exclusions, count_unreadable):
        path = found.path
        media_type = SUPPORTED_MEDIA.get(path.suffix.casefold())
        if media_type is None:
            unsupported += 1
            continue
        if video_only and not media_type.startswith("video/"):
            continue
        resolved_key = str(path.resolve()).casefold()
        previous = index.get(resolved_key)
        if (
            previous is not None
            and previous[1] == found.size
            and previous[2] == found.mtime_ns
        ):
            # Unchanged size and mtime: reuse the stored fingerprint instead
            # of re-reading the whole file on every rescan.
            fingerprint = previous[0]
        else:
            try:
                fingerprint = sha256_file(path)
            except OSError:
                # Locked by another program or deleted mid-scan.
                unreadable += 1
                continue
        supported += 1
        key = (resolved_key, fingerprint)
        if key not in known:
            discovered += 1
            known.add(key)
        else:
            existing += 1
        seen[resolved_key] = fingerprint
        batch.append((path, fingerprint, media_type, found.size, found.mtime_ns))
        if len(batch) >= _BATCH_SIZE:
            flush()
        if on_record is not None:
            on_record(supported)
    flush()

    retired = database.mark_missing_sources(
        seen,
        scanned_types=("video/",) if video_only else ("image/", "video/"),
    )
    return ScanResult(
        discovered=discovered,
        existing=existing,
        supported=supported,
        unsupported=unsupported,
        unreadable=unreadable,
        retired=retired,
    )
