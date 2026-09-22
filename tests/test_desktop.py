from pathlib import Path
from unittest.mock import Mock
import importlib.util


def test_desktop_entry_exists():
    assert importlib.util.find_spec('media_catalog.desktop') is not None


def test_frozen_commands_route_and_filter(tmp_path):
    from media_catalog.supervisor import build_worker_command
    command = build_worker_command(frozen=True, executable='app.exe', root=tmp_path)
    assert command == ['app.exe', '--worker', 'analyze-all', str(tmp_path), '--video-only']


def test_setup_reports_missing_and_installs_explicitly(tmp_path):
    from media_catalog.setup_environment import EnvironmentSetup
    calls = []
    def runner(args, **kwargs):
        calls.append(args)
        return Mock(returncode=0, stdout='', stderr='')
    setup = EnvironmentSetup(tmp_path, which=lambda name: None, runner=runner)
    assert not setup.check()['ready']
    assert calls == []
    result = setup.install(lambda message: None)
    assert not result['ready']
    assert any('Gyan.FFmpeg' in call for call in calls)
    assert any('OpenJS.NodeJS.LTS' in call for call in calls)
    assert any('Ollama.Ollama' in call for call in calls)


def test_diagnostics_writes_json_without_ui(tmp_path):
    from media_catalog.desktop import main
    output = tmp_path / 'diagnostics.json'
    assert main(['--diagnostics', str(output)]) in (0, 1)
    import json
    assert 'checks' in json.loads(output.read_text(encoding='utf-8'))


def test_session_key_is_not_persisted(tmp_path, monkeypatch):
    from media_catalog.desktop import set_session_key
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    set_session_key('  secret-test  ')
    import os
    assert os.environ['GEMINI_API_KEY'] == 'secret-test'


def test_desktop_selection_only_catalogs_videos(tmp_path):
    from media_catalog.desktop import select_video_root
    supervisor = Mock()
    workspace = select_video_root(str(tmp_path), supervisor, tmp_path / 'app')
    assert workspace.root == tmp_path.resolve()
    assert supervisor.start_catalog.call_args.kwargs == {'video_only': True}


def test_desktop_status_uses_actual_model_and_error():
    from media_catalog.desktop import cloud_status
    assert 'gemini-test' in cloud_status(Mock(gemini_model='gemini-test', gemini_error='quota exhausted'))
    assert 'quota exhausted' in cloud_status(Mock(gemini_model='gemini-test', gemini_error='quota exhausted'))


def test_setup_timeout_is_actionable(tmp_path):
    from media_catalog.setup_environment import EnvironmentSetup
    import subprocess
    import pytest
    def runner(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs['timeout'])
    with pytest.raises(RuntimeError, match='逾時'):
        EnvironmentSetup(tmp_path, which=lambda name: None, runner=runner).install(lambda msg: None)


def test_desktop_idle_layout_and_single_primary_action(tmp_path):
    import tkinter as tk
    from media_catalog.desktop import DesktopApplication
    root = tk.Tk()
    root.withdraw()
    supervisor = Mock(is_busy=False)
    try:
        app = DesktopApplication(root, skill_root=tmp_path, supervisor=supervisor)
        root.update_idletasks()
        assert app.workspace is None
        assert app.start_button.cget('state') == 'disabled'
        assert app.path_var.get() == '尚未選擇'
        supervisor.start.assert_not_called()
        supervisor.start_catalog.assert_not_called()
    finally:
        root.destroy()


def test_desktop_inventory_excludes_existing_photo_size(tmp_path):
    from media_catalog.bootstrap import bootstrap_workspace
    from media_catalog.desktop import DesktopApplication
    from media_catalog.supervisor import SupervisorSnapshot
    (tmp_path / 'old.jpg').write_bytes(b'x' * 100)
    (tmp_path / 'new.mp4').write_bytes(b'x' * 10)
    app = DesktopApplication.__new__(DesktopApplication)
    app.workspace = bootstrap_workspace(tmp_path).workspace
    app.media_root = tmp_path
    app.cloud_var = Mock()
    model = app._view_model(SupervisorSnapshot('catalog_ready', False, None))
    assert model.total_size_text == '10 B'
    assert model.image_count == 0


def test_catalog_entry_creates_only_video_records(tmp_path):
    from media_catalog.desktop import main
    from media_catalog.workspace import MediaWorkspace
    from media_catalog.database import CatalogDatabase
    (tmp_path / 'old.jpg').write_bytes(b'photo')
    (tmp_path / 'clip.mp4').write_bytes(b'video')
    assert main(['--catalog', 'start', str(tmp_path), '--video-only']) == 0
    records = CatalogDatabase(MediaWorkspace.from_root(tmp_path).database_path).list_records()
    assert [r.path.name for r in records] == ['clip.mp4']


def test_stop_requested_but_worker_alive_is_not_claimed_stopped(tmp_path):
    from media_catalog.desktop import DesktopApplication
    from media_catalog.run_state import AnalysisRun
    from media_catalog.supervisor import SupervisorSnapshot
    from datetime import datetime, timezone
    run = AnalysisRun(run_id='test', root_path=tmp_path, status='running',
        video_count=1, image_count=0, total_bytes=10, total_media=1, completed_media=0,
        failed_media=0, current_media_id=None, current_segment_id=None, worker_pid=1,
        last_heartbeat=datetime.now(timezone.utc).isoformat(), stop_requested=True,
        recovery_count=0, excel_sync_pending=False)
    app = DesktopApplication.__new__(DesktopApplication)
    app.cloud_var = Mock()
    assert '停止中' in app._view_model(SupervisorSnapshot('running', True, run)).status_text


def test_setup_dialog_is_single_instance_and_checks_do_not_install(tmp_path):
    import tkinter as tk
    from media_catalog.desktop import DesktopApplication
    root = tk.Tk()
    root.withdraw()
    try:
        app = DesktopApplication(root, skill_root=tmp_path, supervisor=Mock(is_busy=False))
        app._setup_dialog()
        app._setup_dialog()
        windows = [child for child in root.winfo_children() if isinstance(child, tk.Toplevel)]
        assert len(windows) == 1
        assert app.setup_busy is False
    finally:
        root.destroy()
