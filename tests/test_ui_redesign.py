"""Behaviour of the redesigned desktop/status UI."""
from __future__ import annotations

import functools
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from media_catalog.status_ui import progress_detail
from media_catalog.ui_theme import status_tone



def isolated_native_tk(test):
    """Run each Tk test in its own interpreter, like tests/test_desktop.py."""
    @functools.wraps(test)
    def run(*args, **kwargs):
        if os.environ.get("MEDIA_CATALOG_TK_TEST") == test.__name__:
            return test(*args, **kwargs)
        environment = dict(os.environ, MEDIA_CATALOG_TK_TEST=test.__name__)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", f"{Path(__file__).resolve()}::{test.__name__}", "-q"],
            env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert result.returncode == 0, result.stdout + result.stderr
    return run


@pytest.mark.parametrize(
    ("text", "light", "tone"),
    [
        ("執行中", "green", "running"),
        ("已完成", "red", "done"),
        ("清冊就緒，請選擇分析模式", "red", "ready"),
        ("等待 Excel 關閉", "red", "waiting"),
        ("正在建立／更新清冊", "red", "waiting"),
        ("worker 異常結束", "red", "error"),
        ("建立媒體清冊失敗", "red", "error"),
        ("尚未選擇資料夾", "red", "idle"),
    ],
)
def test_status_tone_reflects_intent_not_just_heartbeat(text, light, tone) -> None:
    assert status_tone(text, light) == tone


def test_progress_detail_formats_counts_and_passes_sentences_through() -> None:
    assert progress_detail("46 / 128", "82") == "已完成 46 / 128　·　未完成 82"
    assert progress_detail("清冊已收錄 3 部影片；尚未開始本次分析", "x").startswith("清冊已收錄")


@isolated_native_tk
def test_next_action_is_highlighted_and_mode_changes_primary_button(tmp_path):
    import tkinter as tk

    from media_catalog.bootstrap import bootstrap_workspace
    from media_catalog.desktop import DesktopApplication
    from media_catalog.status_ui import MODE_GEMINI, MODE_LOCAL

    root = tk.Tk()
    root.withdraw()
    try:
        supervisor = Mock(is_busy=False, catalog_process=None)
        app = DesktopApplication(root, skill_root=tmp_path, supervisor=supervisor)
        assert app.stepper.active == 0
        assert str(app.start_button.cget("state")) == "disabled"
        select_primary = app.select_button.cget("bg")

        (tmp_path / "clip.mp4").write_bytes(b"video")
        app.workspace = bootstrap_workspace(tmp_path).workspace
        app.media_root = app.workspace.root
        app._apply_control_state()
        assert str(app.start_button.cget("state")) == "normal"
        assert app.start_button.cget("text") == "開始／繼續分析"
        assert app.select_button.cget("bg") != select_primary

        app.mode_var.set(MODE_GEMINI)
        assert app.start_button.cget("text") == "開始 Gemini 強化"
        app.mode_var.set(MODE_LOCAL)

        supervisor.is_busy = True
        app._apply_control_state()
        assert app.start_button.cget("text") == "處理中…"
        assert str(app.stop_button.cget("state")) == "normal"
        app.gemini_choice._choose()
        assert app.mode_var.get() == MODE_LOCAL, "mode is locked while busy"
    finally:
        root.destroy()


@isolated_native_tk
def test_disabled_buttons_look_disabled(tmp_path):
    import tkinter as tk

    from media_catalog import ui_theme

    root = tk.Tk()
    root.withdraw()
    try:
        button = ui_theme.button(tk, root, "x", lambda: None, variant="primary")
        enabled_bg = button.cget("bg")
        button.configure(state="disabled")
        assert button.cget("bg") == ui_theme.DISABLED_BG != enabled_bg
        button.configure(state="normal")
        assert button.cget("bg") == enabled_bg
    finally:
        root.destroy()


@isolated_native_tk
def test_compact_layout_fits_a_768_pixel_screen(tmp_path):
    import tkinter as tk

    from media_catalog.desktop import DesktopApplication

    DesktopApplication.COMPACT_SCREEN_HEIGHT = 100_000  # force compact mode
    root = tk.Tk()
    root.withdraw()
    try:
        app = DesktopApplication(root, skill_root=tmp_path, supervisor=Mock(is_busy=False, catalog_process=None))
        root.update_idletasks()
        assert app.compact is True
        # 768 px minus the taskbar and title bar.
        assert root.winfo_reqheight() <= 690
    finally:
        root.destroy()
