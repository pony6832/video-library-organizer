from __future__ import annotations

import math
import os
import re
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .process_utils import (
    HIDDEN_PROCESS_CREATION_FLAGS,
    credential_free_environment,
    run_process_tree,
)


Runner = Callable[..., subprocess.CompletedProcess[str]]
SCENE_THRESHOLD = 0.35
MAX_SEGMENT_SECONDS = 300.0
MIN_TAIL_SECONDS = 2.0
# Fast-cut footage can produce hundreds of scene changes; each segment costs
# three ffmpeg calls and one local model call, so merge slivers and cap the
# total (Gemini only ever sees 12 segments per video anyway).
MIN_SEGMENT_SECONDS = 2.0
MAX_SEGMENTS = 60
# Scene scores are computed on a downscaled copy; full-resolution decoding of
# 4K footage made detection several times slower for no accuracy gain.
SCENE_DETECTION_WIDTH = 320
# One-frame seeks finish in seconds; a hung call must not wait 20 minutes.
FRAME_EXTRACTION_TIMEOUT_SECONDS = 120.0
_PTS_TIME = re.compile(r"pts_time:(\d+(?:\.\d+)?)")


class SceneSegmentationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SegmentRange:
    start_seconds: float
    end_seconds: float

    @property
    def duration(self) -> float:
        return self.end_seconds - self.start_seconds


def _merge_ranges(
    ranges: list[SegmentRange],
    *,
    min_seconds: float,
    max_seconds: float,
) -> list[SegmentRange]:
    merged: list[SegmentRange] = []
    for item in ranges:
        if (
            merged
            and (merged[-1].duration < min_seconds or item.duration < min_seconds)
            and item.end_seconds - merged[-1].start_seconds <= max_seconds
        ):
            merged[-1] = SegmentRange(merged[-1].start_seconds, item.end_seconds)
        else:
            merged.append(item)
    return merged


def consolidate_ranges(
    ranges: Iterable[SegmentRange],
    *,
    min_seconds: float = MIN_SEGMENT_SECONDS,
    max_seconds: float = MAX_SEGMENT_SECONDS,
    max_count: int = MAX_SEGMENTS,
) -> list[SegmentRange]:
    merged = _merge_ranges(
        list(ranges), min_seconds=min_seconds, max_seconds=max_seconds
    )
    if len(merged) <= max_count or not merged:
        return merged
    total = merged[-1].end_seconds - merged[0].start_seconds
    target = total / max_count
    while len(merged) > max_count and target <= max_seconds:
        grown = _merge_ranges(merged, min_seconds=target, max_seconds=max_seconds)
        if len(grown) == len(merged):
            break
        merged = grown
        target *= 1.25
    return merged


def build_ranges(
    duration: float,
    scene_times: Iterable[float],
    max_seconds: float = MAX_SEGMENT_SECONDS,
    min_tail: float = MIN_TAIL_SECONDS,
    *,
    min_segment_seconds: float = MIN_SEGMENT_SECONDS,
    max_segments: int = MAX_SEGMENTS,
) -> tuple[SegmentRange, ...]:
    duration = float(duration)
    max_seconds = float(max_seconds)
    min_tail = float(min_tail)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration must be a positive finite number")
    if not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("max_seconds must be a positive finite number")
    if not math.isfinite(min_tail) or min_tail < 0 or min_tail > max_seconds:
        raise ValueError("min_tail must be between zero and max_seconds")

    boundaries = sorted(
        {
            float(item)
            for item in scene_times
            if math.isfinite(float(item)) and 0 < float(item) < duration
        }
    )
    points = (0.0, *boundaries, duration)
    ranges: list[SegmentRange] = []
    for raw_start, raw_end in zip(points, points[1:]):
        start = raw_start
        while raw_end - start > max_seconds:
            end = start + max_seconds
            ranges.append(SegmentRange(start, end))
            start = end
        if raw_end > start:
            ranges.append(SegmentRange(start, raw_end))

    ranges = consolidate_ranges(
        ranges,
        min_seconds=min(min_segment_seconds, max_seconds),
        max_seconds=max_seconds,
        max_count=max_segments,
    )
    if len(ranges) > 1 and ranges[-1].duration < min_tail:
        previous = ranges[-2]
        tail = ranges[-1]
        if tail.end_seconds - previous.start_seconds <= max_seconds:
            ranges[-2:] = [
                SegmentRange(previous.start_seconds, tail.end_seconds)
            ]
        else:
            adjusted_boundary = tail.end_seconds - min_tail
            ranges[-2] = SegmentRange(
                previous.start_seconds, adjusted_boundary
            )
            ranges[-1] = SegmentRange(adjusted_boundary, tail.end_seconds)
    return tuple(ranges)


class SceneSegmenter:
    def __init__(
        self,
        *,
        ffmpeg_executable: str = "ffmpeg",
        ffprobe_executable: str = "ffprobe",
        runner: Runner = run_process_tree,
        timeout_seconds: float = 1200,
        frame_timeout_seconds: float = FRAME_EXTRACTION_TIMEOUT_SECONDS,
    ) -> None:
        self.ffmpeg_executable = ffmpeg_executable
        self.ffprobe_executable = ffprobe_executable
        self.runner = runner
        self.timeout_seconds = timeout_seconds
        self.frame_timeout_seconds = min(frame_timeout_seconds, timeout_seconds)

    def segment(self, source: Path) -> tuple[SegmentRange, ...]:
        media_path = self._source_file(source)
        probe = self._run(
            [
                self.ffprobe_executable,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(media_path),
            ]
        )
        if probe.returncode != 0:
            raise SceneSegmentationError(
                f"ffprobe failed with exit code {probe.returncode}"
            )
        try:
            duration = float(probe.stdout.strip())
        except ValueError as error:
            raise SceneSegmentationError(
                "ffprobe returned an invalid duration"
            ) from error

        scene_probe = self._run(
            [
                self.ffmpeg_executable,
                "-hide_banner",
                "-i",
                str(media_path),
                "-vf",
                f"scale={SCENE_DETECTION_WIDTH}:-2,"
                f"select=gt(scene\\,{SCENE_THRESHOLD}),showinfo",
                "-an",
                "-f",
                "null",
                "NUL" if os.name == "nt" else "/dev/null",
            ]
        )
        if scene_probe.returncode != 0:
            raise SceneSegmentationError(
                f"ffmpeg scene probe failed with exit code "
                f"{scene_probe.returncode}"
            )
        raw_log = f"{scene_probe.stdout}\n{scene_probe.stderr}"
        scene_times = tuple(
            float(match.group(1)) for match in _PTS_TIME.finditer(raw_log)
        )
        return build_ranges(duration, scene_times)

    def extract_candidates(
        self,
        source: Path,
        segment: SegmentRange,
        output_dir: Path,
    ) -> tuple[Path, ...]:
        media_path = self._source_file(source)
        if segment.duration <= 0:
            raise ValueError("segment duration must be positive")
        destination = Path(output_dir).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        candidates: list[Path] = []
        for percentage in (20, 50, 80):
            timestamp = segment.start_seconds + (
                segment.duration * percentage / 100
            )
            output = destination / f"frame-{percentage:03d}.jpg"
            result = self._run(
                [
                    self.ffmpeg_executable,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{timestamp:.6f}",
                    "-i",
                    str(media_path),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=1280:1280:force_original_aspect_ratio=decrease",
                    "-q:v",
                    "2",
                    "-y",
                    str(output),
                ],
                timeout=self.frame_timeout_seconds,
            )
            if result.returncode != 0:
                raise SceneSegmentationError(
                    f"ffmpeg frame extraction failed with exit code "
                    f"{result.returncode}"
                )
            if not output.is_file():
                raise SceneSegmentationError(
                    "ffmpeg frame extraction produced no image"
                )
            self._normalize_preview(output)
            candidates.append(output)
        return tuple(candidates)

    def _run(
        self, arguments: list[str], *, timeout: float | None = None
    ) -> subprocess.CompletedProcess[str]:
        try:
            return self.runner(
                arguments,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds if timeout is None else timeout,
                check=False,
                creationflags=HIDDEN_PROCESS_CREATION_FLAGS,
                env=credential_free_environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SceneSegmentationError(
                f"media tool failed: {type(error).__name__}"
            ) from error

    @staticmethod
    def _source_file(source: Path) -> Path:
        media_path = Path(source).resolve()
        if not media_path.is_file():
            raise FileNotFoundError(media_path)
        return media_path

    @staticmethod
    def _normalize_preview(path: Path) -> None:
        try:
            with Image.open(path) as original:
                image = original.convert("RGB")
                image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
            image.save(path, format="JPEG", quality=88, optimize=True)
        except OSError as error:
            raise SceneSegmentationError(
                "extracted frame is not a readable image"
            ) from error
