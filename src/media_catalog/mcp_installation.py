"""Shared checks for the managed, pinned MCP installation."""
import json
import os
from pathlib import Path
import stat
from uuid import uuid4

MCP_VIDEO_ANALYZER_VERSION = '0.8.0'


def mcp_ready(target: Path) -> bool:
    package_root = target / 'node_modules/mcp-video-analyzer'
    try:
        package = json.loads((package_root / 'package.json').read_text(encoding='utf-8'))
        if not isinstance(package, dict):
            return False
        bins = package.get('bin')
        return (package.get('name') == 'mcp-video-analyzer'
                and package.get('version') == MCP_VIDEO_ANALYZER_VERSION
                and isinstance(bins, dict)
                and bins.get('mcp-video-analyzer') in ('./dist/index.js', 'dist/index.js')
                and (package_root / 'dist/index.js').is_file()
                and (target / 'node_modules/.bin/mcp-video-analyzer.cmd').is_file())
    except (OSError, ValueError):
        return False


def prepare_mcp_install(root: Path) -> Path:
    """Preserve a broken installation; never traverse reparse points for repair."""
    target = root.absolute() / '.tools/mcp-video-analyzer'
    def reject_link(path):
        if path.is_symlink() or (path.exists() and getattr(path.lstat(), 'st_file_attributes', 0)
                                & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise RuntimeError('MCP 修復拒絕連結／reparse point；請人工檢查工具目錄。')
    for ancestor in [target, *target.parents]:
        reject_link(ancestor)
    if target.exists():
        if not target.is_dir():
            raise RuntimeError('MCP 工具路徑不是資料夾，請人工檢查。')
        for directory, folders, files in os.walk(target, followlinks=False):
            for name in folders + files:
                reject_link(Path(directory) / name)
        backup = target.with_name(f'{target.name}.backup-{uuid4().hex}')
        target.rename(backup)
    target.mkdir(parents=True)
    return target
