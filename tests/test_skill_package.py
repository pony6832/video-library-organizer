import os
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path("skills/media-inventory")


def test_skill_package_has_required_entrypoints() -> None:
    assert (SKILL_ROOT / "SKILL.md").is_file()
    assert (SKILL_ROOT / "agents/openai.yaml").is_file()
    assert (SKILL_ROOT / "scripts/run_media_catalog.ps1").is_file()
    assert (SKILL_ROOT / "scripts/run_media_analysis.ps1").is_file()
    assert (SKILL_ROOT / "scripts/run_media_analysis_ui.ps1").is_file()


def test_skill_contains_standalone_ui_launcher() -> None:
    launcher = SKILL_ROOT / "scripts/run_media_analysis_ui.ps1"

    assert launcher.is_file()
    text = launcher.read_text(encoding="utf-8")
    assert ".runtime\\Scripts\\pythonw.exe" in text
    assert "[string]$RootPath = ''" in text


def test_skill_package_passes_bundled_validation_without_site_packages() -> None:
    validator = Path('scripts/validate-media-inventory-package.py')
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"

    result = subprocess.run(
        [sys.executable, '-S', str(validator), str(SKILL_ROOT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
