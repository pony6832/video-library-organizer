from pathlib import Path

import pytest

from media_catalog.bootstrap import bootstrap_workspace
from media_catalog.database import CatalogDatabase
from media_catalog.force_gemini import plan_force_run
from media_catalog.gemini_client import GeminiClient, GeminiError
from media_catalog.model_catalog import select_latest_stable_flash
from media_catalog.scanner import scan
from media_catalog.models import Status
from media_catalog.run_state import RunStateStore


def test_latest_general_stable_flash_uses_numeric_version():
    models = [
        {'name': 'models/gemini-3.7-flash', 'supportedGenerationMethods': ['generateContent']},
        {'name': 'models/gemini-3.8-flash', 'supportedGenerationMethods': ['generateContent']},
        {'name': 'models/gemini-4.0-flash-preview', 'supportedGenerationMethods': ['generateContent']},
        {'name': 'models/gemini-9.0-flash-lite', 'supportedGenerationMethods': ['generateContent']},
    ]
    assert select_latest_stable_flash(models) == 'gemini-3.8-flash'


def test_no_stable_flash_fails_closed():
    with pytest.raises(GeminiError):
        select_latest_stable_flash([{'name': 'models/gemini-4.0-flash-preview', 'supportedGenerationMethods': ['generateContent']}])


def test_versioned_stable_flash_suffix_is_allowed():
    assert select_latest_stable_flash([
        {'name': 'models/gemini-2.0-flash-001', 'supportedGenerationMethods': ['generateContent']},
        {'name': 'models/gemini-2.0-flash-lite', 'supportedGenerationMethods': ['generateContent']},
    ]) == 'gemini-2.0-flash-001'


def test_video_only_scan_preserves_existing_image_records(tmp_path: Path):
    root = tmp_path / 'media'
    root.mkdir()
    (root / 'photo.jpg').write_bytes(b'image')
    (root / 'clip.mp4').write_bytes(b'video')
    workspace = bootstrap_workspace(root).workspace
    db = CatalogDatabase(workspace.database_path)
    result = scan(root, db, excluded_roots=(workspace.result_root,), video_only=True)
    assert result.supported == 1
    assert len(db.list_records()) == 2
    estimate, ids = plan_force_run(db.list_records(), set(), video_only=True)
    assert (estimate.video_count, estimate.image_count, len(ids)) == (1, 0, 1)


class PagedTransport:
    def __init__(self):
        self.urls = []

    def get(self, url, *, headers, timeout):
        self.urls.append(url)
        assert headers['x-goog-api-key'] == 'secret'
        if 'pageToken=' not in url:
            return {'models': [{'name': 'models/gemini-3.7-flash', 'supportedGenerationMethods': ['generateContent']}], 'nextPageToken': 'next'}
        return {'models': [{'name': 'models/gemini-3.8-flash', 'supportedGenerationMethods': ['generateContent']}]}


def test_discovery_paginates_and_ignores_stale_env_pin(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'secret')
    monkeypatch.setenv('GEMINI_MODEL', 'gemini-3.7-flash')
    transport = PagedTransport()
    client = GeminiClient(transport=transport)
    assert client.discover_model() == 'gemini-3.8-flash'
    assert len(transport.urls) == 2


def test_video_only_requeue_leaves_legacy_photo_state(tmp_path: Path):
    root = tmp_path / 'media'
    root.mkdir()
    (root / 'photo.jpg').write_bytes(b'image')
    (root / 'clip.mp4').write_bytes(b'video')
    workspace = bootstrap_workspace(root).workspace
    db = CatalogDatabase(workspace.database_path)
    photo, video = sorted(db.list_records(), key=lambda r: r.path.suffix)
    assert photo.media_type.startswith('image/')
    db.set_status(photo.id, Status.FAILED)
    db.set_status(video.id, Status.FAILED)
    assert db.requeue_failed(video_only=True) == 1
    assert db.get_record(photo.id).status is Status.FAILED
    assert db.get_record(video.id).status is Status.PENDING


def test_run_state_persists_selected_model(tmp_path: Path):
    root = tmp_path / 'media'
    root.mkdir()
    workspace = bootstrap_workspace(root).workspace
    store = RunStateStore(workspace.database_path)
    run = store.ensure_run(root_path=root, video_count=1, image_count=0, total_bytes=1)
    store.set_gemini_model(run.run_id, 'gemini-3.8-flash')
    assert RunStateStore(workspace.database_path).get_run(run.run_id).gemini_model == 'gemini-3.8-flash'
    store.set_gemini_error(run.run_id, 'model directory unavailable')
    assert RunStateStore(workspace.database_path).get_run(run.run_id).gemini_error == 'model directory unavailable'
