"""Release audit must reject missing runtime, secrets and non-lite payloads."""
import importlib.util
from pathlib import Path

import pytest


def load_audit():
    path = Path(__file__).resolve().parents[1] / 'packaging' / 'audit_bundle.py'
    assert path.is_file(), 'release audit is not implemented'
    spec = importlib.util.spec_from_file_location('audit_bundle', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bundle(tmp_path):
    (tmp_path / 'MediaCatalogVideoDesktop.exe').write_bytes(b'MZ')
    internal = tmp_path / '_internal'
    internal.mkdir()
    (internal / 'python311.dll').write_bytes(b'runtime')
    (internal / '_tkinter.pyd').write_bytes(b'tk')
    (internal / 'base_library.zip').write_bytes(b'zip')
    (tmp_path / 'README-zh-TW.md').write_text('usage', encoding='utf-8')
    (tmp_path / 'THIRD-PARTY-NOTICES.txt').write_text('licenses', encoding='utf-8')
    return tmp_path


def test_complete_lite_bundle_passes(tmp_path):
    assert load_audit().audit(bundle(tmp_path)) == []


@pytest.mark.parametrize('name,data', [
    ('.env', b'PRIVATE=value'),
    ('model.gguf', b'weights'),
    ('photo.jpg', b'media'),
    ('credential.txt', b'AI' + b'za' + b'A' * 35),
    ('private.txt', b'C:\\Users\\someone\\Documents\\project'),
])
def test_audit_rejects_private_or_non_lite_content(tmp_path, name, data):
    root = bundle(tmp_path)
    (root / name).write_bytes(data)
    errors = load_audit().audit(root)
    assert errors
    assert not any(data.decode(errors='replace') in item for item in errors)


def test_audit_rejects_missing_tk_runtime(tmp_path):
    root = bundle(tmp_path)
    (root / '_internal' / '_tkinter.pyd').unlink()
    assert load_audit().audit(root)


@pytest.mark.parametrize('vendor_path', [
    b'C:\\Users\\Administrator\\AppData\\Local\\Temp\\python-build-ujzk1c0s\\Python-3.11.15\\Objects\\longobject.c',
    b'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\openssl-build-a32e12lo\\x64\\include\\packet.h',
    b'C:\\Users\\Administrator\\AppData\\Local\\Temp\\libffi-build-vj507a9u\\libffi\\libffi-8.pdb',
])
def test_upstream_python_debug_source_path_is_not_a_local_user_path(tmp_path, vendor_path):
    root = bundle(tmp_path)
    (root / '_internal/python311.dll').write_bytes(vendor_path)
    assert load_audit().audit(root) == []


def test_audit_reads_compressed_library_not_just_zip_bytes(tmp_path):
    import zipfile
    root = bundle(tmp_path)
    with zipfile.ZipFile(root / '_internal/base_library.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('bad.pyc', b'AI' + b'za' + b'A' * 35)
    assert load_audit().audit(root)


@pytest.mark.parametrize('data', [
    b'sk' + b'-' + b'a1' * 24,
    b'sk' + b'-proj-' + b'b2' * 40,
    b'sk' + b'-ant-api03-' + b'c3' * 40,
    b'{"api_key": "literal-secret"}',
    b'{"accessToken": "literal-secret"}',
    b'CUSTOM_API_TOKEN=literal-secret\n',
    b'CLIENT_SECRET="literal-secret"\n',
    b'api_key = "literal-secret"\n',
    b'{"token": "literal-secret"}',
    b'TOKEN="literal-secret"\r\n',
    b'CUSTOM_API_TOKEN="literal-secret"\r\n',
    b'ACCESS_TOKEN=literal-secret\r\n',
])
@pytest.mark.parametrize('compressed', [False, True])
def test_audit_rejects_representative_tokens_and_literal_assignments(tmp_path, data, compressed):
    import zipfile
    root = bundle(tmp_path)
    if compressed:
        with zipfile.ZipFile(root / '_internal/base_library.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('config.txt', data)
    else:
        (root / 'config.txt').write_bytes(data)
    findings = load_audit().audit(root)
    assert any('credential' in item for item in findings)
    assert not any(data.decode() in item for item in findings)
    assert not any('literal-secret' in item for item in findings)


@pytest.mark.parametrize('data', [
    b'API_KEY = os.getenv("API_KEY", "")\n',
    b'token = os.environ.get("ACCESS_TOKEN")\n',
    b'{"api_key": "", "access_token": null}',
    b'API_KEY=\nACCESS_TOKEN=${ACCESS_TOKEN}\n',
    b'Use the API_KEY environment variable; never save it.\n',
    b"token='x'",  # SQL/parser token assignment is not a credential field.
    b'mask-' + b'a1' * 500,
])
def test_audit_allows_variable_names_empty_values_and_environment_lookups(tmp_path, data):
    root = bundle(tmp_path)
    (root / 'safe.txt').write_bytes(data)
    assert load_audit().audit(root) == []


def test_audit_checks_windows_utf16_literal_credentials(tmp_path):
    root = bundle(tmp_path)
    (root / 'config.txt').write_bytes('ACCESS_TOKEN="literal-secret"'.encode('utf-16'))
    assert load_audit().audit(root)


def test_audit_rejects_environment_override_files(tmp_path):
    root = bundle(tmp_path)
    (root / '.env.production').write_text('EMPTY=', encoding='utf-8')
    assert load_audit().audit(root)
