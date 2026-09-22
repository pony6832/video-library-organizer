import json
from types import SimpleNamespace

import pytest

from media_catalog.setup_environment import EnvironmentSetup, MODEL


def write_mcp(target):
    package = target / 'node_modules/mcp-video-analyzer'
    package.mkdir(parents=True)
    (package / 'package.json').write_text(json.dumps({'name': 'mcp-video-analyzer', 'version': '0.8.0', 'bin': {'mcp-video-analyzer': './dist/index.js'}}))
    (package / 'dist').mkdir()
    (package / 'dist/index.js').write_text('// synthetic entrypoint')
    shim = target / 'node_modules/.bin/mcp-video-analyzer.cmd'
    shim.parent.mkdir()
    shim.write_text('@echo off')


@pytest.mark.parametrize('damage', ['shim', 'version', 'json', 'name', 'entrypoint'])
def test_partial_mcp_is_not_ready_and_fresh_repair_preserves_original(tmp_path, damage):
    target = tmp_path / '.tools/mcp-video-analyzer'
    write_mcp(target)
    package = target / 'node_modules/mcp-video-analyzer/package.json'
    if damage == 'shim':
        (target / 'node_modules/.bin/mcp-video-analyzer.cmd').unlink()
    elif damage == 'entrypoint':
        (package.parent / 'dist/index.js').unlink()
    elif damage == 'json':
        package.write_text('{broken')
    else:
        data = json.loads(package.read_text())
        data[damage] = 'wrong'
        package.write_text(json.dumps(data))
    before = package.read_bytes()
    def runner(args, **kwargs):
        if args[1] == 'install':
            assert not (target / 'node_modules').exists()
            write_mcp(target)
        return SimpleNamespace(returncode=0, stdout=MODEL, stderr='')
    setup = EnvironmentSetup(tmp_path, which=lambda name: name, runner=runner)
    assert not setup.check()['checks']['mcp-video-analyzer']
    assert setup.install(lambda message: None)['ready']
    backups = list(target.parent.glob('mcp-video-analyzer.backup-*'))
    assert len(backups) == 1
    assert (backups[0] / 'node_modules/mcp-video-analyzer/package.json').read_bytes() == before


@pytest.mark.parametrize('configured,fails', [(True, True), (False, False), (True, False)])
def test_auto_generation_failure_visible_in_persisted_desktop_snapshot(tmp_path, configured, fails):
    from test_batch_analysis import _workspace_with_media
    from test_segment_pipeline import FakeSegmenter, ThreeFrameSelector, RecordingLocalAnalyzer, WEAK, STRONG
    from media_catalog.batch_analysis import analyze_pending
    from media_catalog.database import CatalogDatabase
    from media_catalog.desktop import cloud_status, DesktopApplication
    from media_catalog.gemini_client import GeminiError
    from media_catalog.models import Status
    from media_catalog.run_state import RunStateStore
    from media_catalog.segment_pipeline import SegmentPipeline
    from media_catalog.supervisor import SupervisorSnapshot
    from unittest.mock import Mock
    workspace = _workspace_with_media(tmp_path, ('clip.mp4',))
    store = RunStateStore(workspace.database_path)
    class Client:
        is_configured = configured
        discovery_error = None
        def discover_model(self):
            return 'gemini-discovered'
        def analyze(self, request):
            if fails:
                raise GeminiError('quota denied sensitive-provider-detail')
            return WEAK
    pipeline = SegmentPipeline(segmenter=FakeSegmenter(1), selector=ThreeFrameSelector(),
        local_analyzer=RecordingLocalAnalyzer(WEAK), gemini_client=Client(), store=store,
        output_root=tmp_path / 'frames')
    runtime = SimpleNamespace(run_state=store, segment_pipeline=pipeline)
    result = analyze_pending(workspace, runtime, video_only=True)
    record = CatalogDatabase(workspace.database_path).list_records()[0]
    run = RunStateStore(workspace.database_path).get_run(store.run_id_for_root(workspace.root))
    segment = store.list_segments(record.id)[0]
    assert result.analyzed == 1 and result.remaining == 0
    assert record.status is Status.ANALYZED and record.description == STRONG.description
    assert segment.local_result_json
    assert bool(segment.cloud_result_json) == (configured and not fails)
    assert result.failed == run.failed_media == int(fails)
    app = DesktopApplication.__new__(DesktopApplication)
    app.workspace, app.media_root, app.cloud_var = workspace, workspace.root, Mock()
    view = app._view_model(SupervisorSnapshot('completed', False, run))
    if fails:
        assert 'Gemini' in record.error and '失敗' in run.gemini_error
        assert run.gemini_model == 'gemini-discovered'
        assert '失敗' in cloud_status(run)
        assert view.failure_text == '失敗／降級：1'
        assert 'sensitive-provider-detail' not in str((record, run, segment, view))
        resumed = analyze_pending(workspace, runtime, video_only=True)
        assert resumed.failed == 1
        assert store.get_run(run.run_id).gemini_error
    else:
        assert record.error is None and run.gemini_error is None


@pytest.mark.parametrize('nested', [True, False])
def test_mcp_repair_refuses_junction_without_touching_target(tmp_path, nested):
    import subprocess
    from media_catalog.mcp_installation import prepare_mcp_install
    outside = tmp_path / 'outside'
    outside.mkdir()
    marker = outside / 'keep.txt'
    marker.write_text('preserve')
    root = tmp_path / 'app'
    target = root / '.tools/mcp-video-analyzer'
    if nested:
        target.mkdir(parents=True)
        link = target / 'linked'
    else:
        root.mkdir()
        link = root / '.tools'
    completed = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True)
    assert completed.returncode == 0
    try:
        with pytest.raises(RuntimeError, match='reparse'):
            prepare_mcp_install(root)
        assert marker.read_text() == 'preserve'
        assert not list(root.glob('**/mcp-video-analyzer.backup-*'))
    finally:
        # rmdir removes this exact junction itself, never its destination.
        link.rmdir()
