"""Open the media library panel (VideoLibraryViewer) on a workspace.

The installer puts VideoLibraryViewer.exe in ``viewer\\`` beside the desktop
executable. The viewer links the folder's analysis database read-only; when a
copy is already running it hands the folder over to that copy.
"""
from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import subprocess
import sys

from .process_utils import credential_free_environment

VIEWER_EXE = "VideoLibraryViewer.exe"
VIEWER_DOWNLOAD_URL = "https://github.com/pony6832/video-library-viewer/releases"
# Development builds can point at a viewer elsewhere.
VIEWER_ENV = "VIDEO_LIBRARY_VIEWER"


class ViewerNotInstalled(FileNotFoundError):
    pass


def find_viewer(
    *, executable: str | None = None, environ: dict[str, str] | None = None
) -> Path | None:
    environ = os.environ if environ is None else environ
    override = environ.get(VIEWER_ENV)
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None
    bundled = Path(executable or sys.executable).resolve().parent / "viewer" / VIEWER_EXE
    return bundled if bundled.is_file() else None


def open_viewer(
    folder: Path,
    *,
    viewer: Path | None = None,
    popen: Callable[..., object] = subprocess.Popen,
) -> None:
    exe = viewer or find_viewer()
    if exe is None:
        raise ViewerNotInstalled(VIEWER_EXE)
    # The viewer is a console program: its own console window shows its
    # status and closing it stops the viewer. It never needs credentials.
    popen(
        [str(exe), "--import", str(Path(folder))],
        cwd=str(exe.parent),
        env=credential_free_environment(),
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )
