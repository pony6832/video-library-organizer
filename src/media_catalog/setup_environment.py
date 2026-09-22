"""Explicit, bounded first-run setup. Checking never installs or uploads media."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
from .process_utils import HIDDEN_PROCESS_CREATION_FLAGS

MODEL = 'qwen3-vl:8b-instruct'


def app_data_root() -> Path:
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'share'))) / 'MediaCatalogVideoDesktop'


def refresh_tool_path() -> None:
    # npm lifecycle scripts run through cmd.exe, which drops PATH when it
    # exceeds its 8191-character environment limit. Reserve room for npm's
    # node_modules/.bin additions and keep required executables first.
    priority = [str(Path(value).parent) for name in ('node', 'npm', 'ffmpeg', 'ffprobe', 'ollama', 'winget')
                if (value := shutil.which(name))]
    priority.append(str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32'))
    paths = []
    if sys.platform == 'win32':
        import winreg
        for hive, name in [(winreg.HKEY_CURRENT_USER, 'Environment'),
                           (winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment')]:
            try:
                with winreg.OpenKey(hive, name) as key:
                    paths.append(os.path.expandvars(winreg.QueryValueEx(key, 'Path')[0]))
            except OSError:
                pass
    paths += [str(Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Ollama'),
              str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'nodejs')]
    entries, seen = [], set()
    for group in [*priority, os.environ.get('PATH', ''), *paths]:
        for raw in group.split(os.pathsep):
            entry = os.path.expandvars(raw.strip().strip('"'))
            key = os.path.normcase(os.path.normpath(entry))
            if not entry or key in seen:
                continue
            seen.add(key)
            if len(os.pathsep.join([*entries, entry])) <= 4096:
                entries.append(entry)
    os.environ['PATH'] = os.pathsep.join(entries)


def run_external(args, *, timeout=120):
    # Frozen Python's DLL directory must not leak into system tools.
    if sys.platform == 'win32' and getattr(sys, 'frozen', False):
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        return subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding='utf-8', errors='replace', timeout=timeout,
            creationflags=HIDDEN_PROCESS_CREATION_FLAGS)
    finally:
        if sys.platform == 'win32' and getattr(sys, 'frozen', False):
            ctypes.windll.kernel32.SetDllDirectoryW(sys._MEIPASS)


class EnvironmentSetup:
    def __init__(self, root=None, *, which=shutil.which, runner=run_external):
        self.root = Path(root) if root else app_data_root()
        self.which = which
        self.runner = runner

    def check(self):
        refresh_tool_path()
        checks = {name: bool(self.which(name)) for name in ('ffmpeg', 'ffprobe', 'node', 'npm', 'ollama')}
        checks['mcp-video-analyzer'] = (self.root / '.tools/mcp-video-analyzer/node_modules/mcp-video-analyzer/package.json').is_file()
        error = ''
        checks[MODEL] = False
        if checks['ollama']:
            try:
                result = self.runner([self.which('ollama'), 'list'], timeout=20)
                checks[MODEL] = result.returncode == 0 and MODEL in result.stdout.lower()
                if result.returncode:
                    error = 'Ollama 服務尚未就緒；請開啟 Ollama 後按「檢查環境」。'
            except (OSError, subprocess.TimeoutExpired):
                error = 'Ollama 沒有回應；請啟動 Ollama，再按「檢查環境」。'
        return {'ready': all(checks.values()), 'checks': checks, 'message': error,
                'app_data': str(self.root)}

    def install(self, progress):
        report = self.check()
        for tool, package in [('ffmpeg', 'Gyan.FFmpeg'), ('node', 'OpenJS.NodeJS.LTS'), ('ollama', 'Ollama.Ollama')]:
            if report['checks'][tool]:
                continue
            progress(f'正在安裝 {tool}，若 Windows 顯示權限確認請允許；可能需要數分鐘。')
            self._execute(['winget', 'install', '--exact', '--id', package,
                '--accept-package-agreements', '--accept-source-agreements', '--silent'], 1200)
        refresh_tool_path()
        npm, ollama = self.which('npm'), self.which('ollama')
        if npm and not report['checks']['mcp-video-analyzer']:
            progress('正在準備影片擷取工具…')
            target = self.root / '.tools/mcp-video-analyzer'
            target.mkdir(parents=True, exist_ok=True)
            self._execute([npm, 'install', '--prefix', str(target), '--no-audit', '--no-fund', 'mcp-video-analyzer@0.8.0'], 900)
        if ollama and not report['checks'][MODEL]:
            progress('正在下載本機視覺模型（約 6 GB），請保持網路連線…')
            self._execute([ollama, 'pull', MODEL], 3600)
        result = self.check()
        if not result['ready'] and not result['message']:
            result['message'] = '安裝尚未完成。若權限確認被取消，請重新按「安裝缺少元件」；若剛安裝完成，請重開程式後檢查。'
        return result

    def _execute(self, args, timeout):
        try:
            result = self.runner(args, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError('下載或安裝逾時。請檢查網路，完成 Windows 權限確認後重新按「安裝缺少元件」。') from error
        except OSError as error:
            raise RuntimeError('無法執行安裝工具。請從 Microsoft Store 更新「應用程式安裝程式」（winget），再按「安裝缺少元件」。') from error
        if result.returncode:
            detail = ((result.stdout or '') + (result.stderr or '')).lower()
            if 'node' in detail and ('not recognized' in detail or '不是' in detail):
                hint = '安裝子程序找不到 Node.js。請重新開啟本程式以更新 PATH，再按「安裝缺少元件」。'
            elif 'enospc' in detail:
                hint = '磁碟空間不足。請釋出使用者磁碟空間後重試。'
            elif 'eperm' in detail or 'eacces' in detail:
                hint = '檔案被鎖定或權限不足。請關閉其他安裝程式，確認防毒未封鎖後重試。'
            else:
                hint = '請檢查網路與 Windows 權限確認，關閉其他安裝程式後重試。'
            if 'npm' in Path(args[0]).name.lower():
                hint += ' npm 詳細紀錄位於 %LOCALAPPDATA%/npm-cache/_logs。'
            raise RuntimeError(f'{Path(args[0]).name} 安裝未完成（代碼 {result.returncode}）。{hint}')
