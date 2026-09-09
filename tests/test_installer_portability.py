import shutil
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / 'scripts' / 'validate-media-inventory-package.py'


def validate(path):
    # -S proves no site-packages (including PyYAML) are required.
    return subprocess.run([sys.executable, '-X', 'utf8', '-S', str(VALIDATOR), str(path)],
                          capture_output=True, text=True, encoding='utf-8')


def test_validator_accepts_shipped_package_without_site_packages():
    result = validate(ROOT / 'skills' / 'media-inventory')
    assert result.returncode == 0, result.stderr
    assert 'MEDIA_INVENTORY_PACKAGE_VALID' in result.stdout


@pytest.mark.parametrize('damage', ['missing_launcher', 'wrong_name', 'empty_description', 'missing_delimiter'])
def test_validator_rejects_damaged_package(tmp_path, damage):
    package = tmp_path / 'media-inventory'
    shutil.copytree(ROOT / 'skills' / 'media-inventory', package)
    skill = package / 'SKILL.md'
    if damage == 'missing_launcher':
        (package / 'scripts' / 'run_media_catalog.ps1').unlink()
    elif damage == 'wrong_name':
        skill.write_text('---\nname: other\ndescription: valid\n---\n# Body', encoding='utf-8')
    elif damage == 'empty_description':
        skill.write_text('---\nname: media-inventory\ndescription: ""\n---\n# Body', encoding='utf-8')
    else:
        skill.write_text('name: media-inventory\ndescription: valid', encoding='utf-8')
    result = validate(package)
    assert result.returncode == 1
    assert 'MEDIA_INVENTORY_PACKAGE_ERROR' in result.stderr


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows installer')
@pytest.mark.parametrize('failure', ['missing_python', 'invalid_python', 'missing_node', 'old_node', 'broken_npm'])
def test_failed_preflight_does_not_move_existing_installation(tmp_path, failure):
    powershell = shutil.which('powershell.exe')
    # Command-boundary doubles prevent network installs and exercise early failures.
    if failure != 'missing_python':
        python_exit = 1 if failure == 'invalid_python' else 0
        (tmp_path / 'python.cmd').write_text(f'@exit /b {python_exit}\n')
    if failure in ('old_node', 'broken_npm'):
        version = 'v17.0.0' if failure == 'old_node' else 'v22.0.0'
        (tmp_path / 'node.cmd').write_text(f'@echo {version}\n@exit /b 0\n')
        npm_exit = 1 if failure == 'broken_npm' else 0
        (tmp_path / 'npm.cmd').write_text(f'@exit /b {npm_exit}\n')
    destination = tmp_path / 'media-inventory'
    destination.mkdir()
    marker = destination / 'existing.txt'
    marker.write_text('preserve me')
    environment = dict(os.environ, PATH=str(tmp_path))
    result = subprocess.run([powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass',
                             '-File', str(ROOT / 'scripts/install-media-inventory-skill.ps1'),
                             '-Destination', str(destination), '-ProjectRoot', str(ROOT)],
                            env=environment, capture_output=True, timeout=30)
    assert result.returncode == 1
    expected_error = {
        'missing_python': b'python',
        'invalid_python': b'Python 3.11+',
        'missing_node': b'node',
        'old_node': b'Node.js 18 or newer',
        'broken_npm': b'npm is not operational',
    }[failure]
    assert expected_error in result.stderr, result.stderr
    assert marker.is_file(), 'Preflight failure moved the existing installation'
    assert marker.read_text() == 'preserve me'
    assert not list(tmp_path.glob('media-inventory.backup-*'))
