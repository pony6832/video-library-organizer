import subprocess
from pathlib import Path

import pytest

from media_catalog.viewer_launcher import (
    VIEWER_ENV,
    ViewerNotInstalled,
    find_viewer,
    open_viewer,
)


def test_finds_viewer_installed_beside_the_desktop_app(tmp_path: Path) -> None:
    app = tmp_path / "MediaCatalogVideoDesktop.exe"
    app.write_bytes(b"")
    assert find_viewer(executable=str(app), environ={}) is None
    viewer = tmp_path / "viewer" / "VideoLibraryViewer.exe"
    viewer.parent.mkdir()
    viewer.write_bytes(b"")
    assert find_viewer(executable=str(app), environ={}) == viewer.resolve()


def test_environment_override_wins_and_must_exist(tmp_path: Path) -> None:
    viewer = tmp_path / "dev" / "VideoLibraryViewer.exe"
    assert find_viewer(executable=str(tmp_path / "x.exe"), environ={VIEWER_ENV: str(viewer)}) is None
    viewer.parent.mkdir()
    viewer.write_bytes(b"")
    assert find_viewer(executable=str(tmp_path / "x.exe"), environ={VIEWER_ENV: str(viewer)}) == viewer


def test_opens_the_folder_in_its_own_console_without_credentials(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    viewer = tmp_path / "viewer" / "VideoLibraryViewer.exe"
    viewer.parent.mkdir()
    viewer.write_bytes(b"")
    calls = []
    open_viewer(tmp_path / "影片", viewer=viewer, popen=lambda *a, **k: calls.append((a, k)))
    (args, kwargs), = calls
    assert args[0] == [str(viewer), "--import", str(tmp_path / "影片")]
    assert kwargs["cwd"] == str(viewer.parent)
    assert "GEMINI_API_KEY" not in kwargs["env"]
    assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NEW_CONSOLE", 0)


def test_missing_viewer_is_reported(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("media_catalog.viewer_launcher.find_viewer", lambda: None)
    with pytest.raises(ViewerNotInstalled):
        open_viewer(tmp_path, popen=lambda *a, **k: pytest.fail("must not launch"))
