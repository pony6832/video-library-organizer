"""Standalone desktop entry. Worker dispatch deliberately precedes Tk imports."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import sys
import threading
from dataclasses import replace

from . import ui_theme as theme
from .analysis_mode import AnalysisMode
from .setup_environment import EnvironmentSetup, app_data_root
from .status_ui import (
    StatusApplication,
    StatusViewModel,
    format_force_confirmation,
)
from .workspace import MediaWorkspace
from .credential_store import CredentialError, read_key, write_key


def set_session_key(value: str) -> None:
    if value.strip():
        os.environ['GEMINI_API_KEY'] = value.strip()


def analysis_progress_text(percent: int, progress: str, remaining: str) -> str:
    if progress.startswith(('清冊已收錄', '清冊已寫入')):
        return progress
    return f'{percent}%　已完成 {progress}　未完成 {remaining}'


def segment_percent(number: int, total: int) -> int:
    """Completed segments before the active one; never imply it has finished."""
    return max(0, min(total - 1, number - 1) * 100 // total) if total > 0 else 0


def select_video_root(selected, supervisor, app_root):
    if not selected:
        return None
    workspace = MediaWorkspace.from_root(Path(selected))
    supervisor.start_catalog(workspace.root, app_root, video_only=True)
    return workspace


def cloud_status(run):
    if run is None:
        return '尚未使用雲端；模型將於連線後顯示'
    model = run.gemini_model or '尚未選定'
    return f'實際模型：{model}' + (f'｜{run.gemini_error}' if run.gemini_error else '')


class DesktopApplication(StatusApplication):
    def __init__(self, root, *, media_root=None, skill_root=None, **kwargs):
        self.setup_busy = False
        self.events = queue.Queue()
        self.environment = EnvironmentSetup(skill_root)
        super().__init__(root, skill_root=skill_root or app_data_root(), **kwargs)
        try:
            saved_key = read_key()
        except CredentialError as error:
            saved_key = None
            self.messagebox.showwarning('Gemini Key 無法讀取', str(error))
        if saved_key:
            set_session_key(saved_key)
        self.key_status_var.set('Key 已儲存' if saved_key else '尚未設定 Key')
        root.after(150, self._drain_events)
        if media_root:
            self._select(str(media_root))

    WINDOW_TITLE = '影片資料庫整理'
    APP_TITLE = '影片資料庫整理'
    APP_SUBTITLE = '為本機影片建立可搜尋的清冊與內容摘要｜原始影片不會被移動或修改，也不處理照片'
    STEPS = ('選擇資料夾', '建立清冊', '分析影片', '檢閱成果')
    SOURCE_TITLE = '影片資料夾'

    def _build_header_actions(self, parent):
        self.setup_button = self._button(parent, '⚙  環境設定', self._setup_dialog, variant='quiet')
        self.setup_button.pack(side='right')

    def _source_tiles(self):
        return (('影片', self.video_tile_var), ('總容量', self.size_tile_var))

    def _local_mode_description(self):
        return '以本機 Qwen3.5 9B 辨識，不需網路；設定 Key 後，低信心片段的縮圖才會送至 Gemini 補強。'

    def _build_gemini_options(self, parent):
        tk = self.tk
        row = tk.Frame(parent, bg=theme.SURFACE)
        row.pack(fill='x', pady=(10, 0))
        tk.Label(row, text='Gemini Key', bg=theme.SURFACE, fg=theme.TEXT_MUTED,
                 font=theme.font(9)).pack(side='left')
        self.key_status_var = tk.StringVar(value='尚未設定 Key')
        tk.Label(row, textvariable=self.key_status_var, bg=theme.SURFACE, fg=theme.TEXT,
                 font=theme.font(9, 'bold'), anchor='w', justify='left', wraplength=170
                 ).pack(side='left', padx=(8, 0), fill='x', expand=True)
        self.check_key_button = self._button(row, '檢查', self._check_key, variant='quiet')
        self.check_key_button.pack(side='right')
        self.key_button = self._button(row, '設定 Key', self._key_dialog, variant='quiet')
        self.key_button.pack(side='right', padx=(0, 6))

    def _build_progress_extras(self, card):
        tk = self.tk
        segment = tk.Frame(card, bg=theme.SURFACE)
        segment.pack(fill='x', pady=(10, 0))
        self.segment_var = tk.StringVar(value='片段進度：尚未開始')
        tk.Label(segment, textvariable=self.segment_var, bg=theme.SURFACE, fg=theme.TEXT_MUTED,
                 font=theme.font(9), anchor='w').pack(fill='x')
        self.segment_bar = self.ttk.Progressbar(card, maximum=100, style='Thin.Horizontal.TProgressbar')
        self.segment_bar.pack(fill='x', pady=(4, 0))
        theme.divider(tk, card)
        cloud = tk.Frame(card, bg=theme.SURFACE)
        cloud.pack(fill='x')
        tk.Label(cloud, text='雲端', bg=theme.WARN_SOFT, fg=theme.WARN, font=theme.font(9, 'bold'),
                 padx=6).pack(side='left', anchor='n')
        self.cloud_var = tk.StringVar(value=cloud_status(None))
        cloud_label = tk.Label(cloud, textvariable=self.cloud_var, bg=theme.SURFACE, fg=theme.TEXT_MUTED,
                               font=theme.font(9), anchor='w', justify='left', wraplength=460)
        cloud_label.pack(side='left', padx=(8, 0), fill='x', expand=True)
        theme.auto_wrap(cloud_label, margin=4)

    def _choose_folder(self):
        if not self.supervisor.is_busy and not self.setup_busy:
            self._select(self.folder_picker())

    def _key_dialog(self):
        tk = self.tk
        window = tk.Toplevel(self.root)
        window.title('設定 Gemini Key')
        window.configure(bg=theme.SURFACE)
        window.resizable(False, False)
        window.transient(self.root)
        window.grab_set()
        body = tk.Frame(window, bg=theme.SURFACE, padx=24, pady=20)
        body.pack(fill='both', expand=True)
        tk.Label(body, text='設定 Gemini Key', bg=theme.SURFACE, fg=theme.TEXT,
                 font=theme.font(13, 'bold'), anchor='w').pack(fill='x')
        tk.Label(body, text='Key 只存放在 Windows 認證管理員，不會寫入清冊、Excel 或設定檔。',
                 bg=theme.SURFACE, fg=theme.TEXT_MUTED, font=theme.font(9), anchor='w',
                 justify='left', wraplength=380).pack(fill='x', pady=(4, 12))
        value = tk.StringVar()
        entry = tk.Entry(body, textvariable=value, show='•', width=44, relief='flat',
                         bg=theme.SURFACE_ALT, fg=theme.TEXT, insertbackground=theme.TEXT,
                         highlightthickness=1, highlightbackground=theme.BORDER,
                         highlightcolor=theme.ACCENT, font=theme.font(11))
        entry.pack(fill='x', ipady=6)
        entry.focus_set()

        def save():
            try:
                write_key(value.get())
            except (CredentialError, ValueError) as error:
                self.messagebox.showerror('無法儲存 Key', str(error), parent=window)
                return
            set_session_key(value.get())
            value.set('')
            self.key_status_var.set('Key 已儲存')
            window.destroy()

        actions = tk.Frame(body, bg=theme.SURFACE)
        actions.pack(fill='x', pady=(16, 0))
        self._button(actions, '儲存', save, variant='primary').pack(side='right')
        self._button(actions, '取消', window.destroy).pack(side='right', padx=(0, 8))
        window.bind('<Return>', lambda _event: save())
        window.bind('<Escape>', lambda _event: window.destroy())

    def _check_key(self):
        if self.supervisor.is_busy or self.setup_busy:
            return
        key = os.environ.get('GEMINI_API_KEY', '').strip()
        if not key:
            self.key_status_var.set('尚未設定 Key；請先儲存')
            return
        self.check_key_button.configure(state='disabled')
        self.key_status_var.set('正在檢查 Key…')

        def work():
            from .gemini_client import GeminiClient, GeminiError
            try:
                model = GeminiClient(timeout_seconds=15).discover_model(key=key)
                message = f'Key 可列出模型｜最新正式 Flash：{model}'
            except GeminiError as error:
                message = f'Key 檢查未通過：{error}'
            except Exception:
                message = 'Key 檢查未完成：網路或服務暫時無法使用'
            self.events.put(('key_check', message))

        threading.Thread(target=work, daemon=True).start()

    def _select(self, selected):
        try:
            workspace = select_video_root(selected, self.supervisor, self.skill_root)
            if workspace:
                self.workspace, self.media_root = workspace, workspace.root
                self._render(StatusViewModel.without_run(status_text='正在建立影片清冊…', root_text=str(workspace.root)))
                self._apply_control_state()
        except (OSError, RuntimeError, ValueError) as error:
            self.messagebox.showerror('無法使用資料夾', f'{error}\n請選擇可讀寫的本機影片資料夾。')

    def _start(self):
        if self.workspace is None or self.supervisor.is_busy or self.setup_busy:
            return
        force = self.mode_var.get().startswith('Gemini')
        try:
            if not self.workspace.database_path.is_file() or not self.workspace.excel_path.is_file():
                self.supervisor.start_catalog(self.media_root, self.skill_root, video_only=True)
                return
            if force:
                from .force_gemini import validate_force_environment, plan_force_run
                from .database import CatalogDatabase
                from .excel_catalog import read_reviewed_paths_strict
                error = validate_force_environment(os.environ)
                if error:
                    self.messagebox.showerror('請輸入 Gemini Key', error)
                    return
                records = [r for r in CatalogDatabase(self.workspace.database_path).list_records() if r.media_type.startswith('video/')]
                estimate, ids = plan_force_run(records, read_reviewed_paths_strict(self.workspace.excel_path))
                if not ids:
                    self.messagebox.showinfo('無須強化', '沒有未審核的影片。')
                    return
                if not self.messagebox.askokcancel('確認雲端強化與可能費用', format_force_confirmation(estimate)):
                    return
            self.supervisor.start(self.media_root, self.skill_root,
                mode=AnalysisMode.FORCE_GEMINI if force else AnalysisMode.AUTO, video_only=True)
            self._apply_control_state()
        except (OSError, RuntimeError, ValueError) as error:
            self.messagebox.showerror('尚未開始分析', f'{error}\n請先完成「環境檢查／首次設定」，再重試。')

    def _render(self, model):
        super()._render(model)
        self.progress_var.set(analysis_progress_text(model.progress_percent, model.progress_text, model.remaining_text))
        cataloging = (model.status_text == '正在建立影片清冊…' or self.supervisor.is_busy
                      and self.supervisor.catalog_process is not None
                      and self.supervisor.catalog_process.poll() is None)
        if cataloging:
            self.percent_var.set('…')
            if str(self.progress['mode']) != 'indeterminate':
                self.progress.configure(mode='indeterminate')
                self.progress.start(12)
        elif str(self.progress['mode']) == 'indeterminate':
            self.progress.stop()
            self.progress.configure(mode='determinate')
            self.progress['value'] = model.progress_percent
        self.counts_var.set(f'影片：{model.video_count}　容量：{model.total_size_text}　（不新增或分析照片）')
        self.status_var.set(model.status_text.replace('worker', '分析程序'))
        if model.segment_total and model.segment_number:
            self.segment_var.set(f'本片第 {model.segment_number}／{model.segment_total} 段（已完成前 {model.segment_number - 1} 段）')
            self.segment_bar['value'] = segment_percent(model.segment_number, model.segment_total)
        else:
            self.segment_var.set('片段進度：尚未開始或目前影片已完成')
            self.segment_bar['value'] = 0

    def _view_model(self, snapshot):
        model = super()._view_model(snapshot)
        if snapshot.run and snapshot.run.stop_requested and snapshot.worker_alive:
            model = replace(model, status_text='安全停止中，正在保存目前進度…')
        if snapshot.run is None and snapshot.status == 'cataloging' and self.workspace and self.workspace.database_path.is_file():
            from .database import CatalogDatabase
            videos, _, total_bytes = CatalogDatabase(self.workspace.database_path).media_summary(video_only=True)
            model = StatusViewModel.without_run(status_text=model.status_text, root_text=model.root_text,
                video_count=videos, total_bytes=total_bytes)
            model = replace(model, progress_text=f'清冊已寫入 {videos} 部影片；正在掃描其餘檔案')
        if snapshot.run is None and snapshot.status == 'catalog_ready' and self.workspace:
            from .database import CatalogDatabase
            videos, _, total_bytes = CatalogDatabase(self.workspace.database_path).media_summary(video_only=True)
            model = StatusViewModel.without_run(status_text=model.status_text, root_text=model.root_text,
                video_count=videos, total_bytes=total_bytes)
            model = replace(model, progress_text=f'清冊已收錄 {videos} 部影片；尚未開始本次分析',
                remaining_text='啟動分析後計算')
        self.cloud_var.set(cloud_status(snapshot.run))
        return model

    def _apply_control_state(self):
        busy = self.supervisor.is_busy or self.setup_busy
        has_outputs = bool(self.workspace and self.workspace.excel_path.is_file())
        gemini = self.gemini_selected
        self.select_button.configure(state='disabled' if busy else 'normal')
        self.start_button.configure(state='normal' if self.workspace and not busy else 'disabled')
        self._label_primary_action(busy=busy, gemini=gemini,
                                   has_outputs=bool(self.workspace and self.workspace.database_path.is_file() and has_outputs))
        self.stop_button.configure(state='normal' if self.supervisor.is_busy else 'disabled')
        self.local_choice.set_enabled(not busy)
        self.gemini_choice.set_enabled(not busy)
        self.key_button.configure(state='disabled' if busy else 'normal')
        self.check_key_button.configure(state='disabled' if busy else 'normal')
        self.setup_button.configure(state='disabled' if busy else 'normal')
        setup_window = getattr(self, 'setup_window', None)
        if setup_window is not None and setup_window.winfo_exists():
            for button in (self.check_button, self.install_button):
                button.configure(state='disabled' if busy else 'normal')
        for button in (self.excel_button, self.result_button, self.viewer_button):
            button.configure(state='normal' if has_outputs else 'disabled')

    def _primary_action(self):
        # The desktop start handler reads the selected mode itself.
        self._start()

    def _setup_dialog(self):
        existing = getattr(self, 'setup_window', None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_set()
            return
        tk = self.tk
        window = tk.Toplevel(self.root)
        self.setup_window = window
        window.title('環境設定')
        window.configure(bg=theme.SURFACE)
        window.geometry('640x440')
        window.minsize(560, 400)
        window.transient(self.root)
        body = tk.Frame(window, bg=theme.SURFACE, padx=26, pady=22)
        body.pack(fill='both', expand=True)
        tk.Label(body, text='環境檢查與首次設定', bg=theme.SURFACE, fg=theme.TEXT,
                 font=theme.font(14, 'bold'), anchor='w').pack(fill='x')
        tk.Label(body, text='「檢查環境」只檢查，不下載也不分析影片。「安裝缺少元件」會下載 FFmpeg、Node.js、'
                            'Ollama 及約 6.6 GB 的本機模型；需要網路與磁碟空間，Windows 可能要求確認權限。',
                 bg=theme.SURFACE, fg=theme.TEXT_MUTED, font=theme.font(9), anchor='w', justify='left',
                 wraplength=580).pack(fill='x', pady=(4, 14))
        report = tk.Frame(body, bg=theme.SURFACE_ALT, padx=16, pady=14,
                          highlightthickness=1, highlightbackground=theme.DIVIDER)
        report.pack(fill='both', expand=True)
        self.setup_text = tk.StringVar(value='尚未檢查。按「檢查環境」查看每個元件是否就緒。')
        tk.Label(report, textvariable=self.setup_text, bg=theme.SURFACE_ALT, fg=theme.TEXT,
                 font=theme.font(10), justify='left', anchor='nw', wraplength=560
                 ).pack(fill='both', expand=True)
        buttons = tk.Frame(body, bg=theme.SURFACE)
        buttons.pack(fill='x', pady=(16, 0))
        self.install_button = self._button(buttons, '安裝缺少元件', lambda: self._setup_job(True), variant='primary')
        self.install_button.pack(side='right')
        self.check_button = self._button(buttons, '檢查環境', lambda: self._setup_job(False))
        self.check_button.pack(side='right', padx=(0, 8))
        window.protocol('WM_DELETE_WINDOW', lambda: None if self.setup_busy else window.destroy())
        self._apply_control_state()

    def _setup_job(self, install):
        if self.setup_busy or self.supervisor.is_busy:
            return
        self.setup_busy = True
        self.check_button.configure(state='disabled')
        self.install_button.configure(state='disabled')
        self._apply_control_state()
        self.setup_text.set('正在檢查環境…')
        def work():
            try:
                result = self.environment.install(lambda msg: self.events.put(('progress', msg))) if install else self.environment.check()
                lines = [f'{"✓ 就緒　" if ready else "✗ 待設定"}  {name}' for name, ready in result['checks'].items()]
                lines.append(result['message'] or ('環境已就緒，可以開始分析。' if result['ready'] else '請按「安裝缺少元件」完成設定。'))
                self.events.put(('done', '\n'.join(lines)))
            except Exception as error:
                self.events.put(('done', f'設定未完成：{error}\n請檢查網路及權限後重試；不會影響原始影片。'))
        threading.Thread(target=work, daemon=True).start()

    def _drain_events(self):
        try:
            while True:
                kind, message = self.events.get_nowait()
                if kind == 'key_check':
                    self.key_status_var.set(message)
                    # Respect busy state instead of unconditionally re-enabling.
                    self._apply_control_state()
                    continue
                self.setup_text.set(message)
                if kind == 'done':
                    self.setup_busy = False
                    self.check_button.configure(state='normal')
                    self.install_button.configure(state='normal')
                    self._apply_control_state()
        except queue.Empty:
            pass
        self.root.after(150, self._drain_events)

    def _on_close(self):
        if self.setup_busy:
            self.messagebox.showinfo('環境設定中', '請等待目前安裝步驟完成；若有 Windows 權限提示，請先回應。')
            return
        super()._on_close()


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ('--worker', '--catalog'):
        if sys.platform == 'win32' and getattr(sys, 'frozen', False):
            import ctypes
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        # PyInstaller windowed builds have no standard streams. Reattach worker
        # stdout to the inherited pipe so catalog failures remain inspectable.
        if sys.stdout is None:
            try:
                sys.stdout = open(1, 'w', encoding='utf-8', closefd=False)
            except OSError:
                sys.stdout = open(os.devnull, 'w')
        if sys.stderr is None:
            sys.stderr = sys.stdout
        from .cli import main as cli_main
        return cli_main(args[1:])
    parser = argparse.ArgumentParser(description='影片資料庫整理桌面版')
    parser.add_argument('--root', type=Path)
    parser.add_argument('--diagnostics', nargs='?', const='-', metavar='JSON_PATH')
    arguments = parser.parse_args(args)
    if arguments.diagnostics:
        report = EnvironmentSetup().check()
        encoded = json.dumps(report, ensure_ascii=False, indent=2)
        if arguments.diagnostics != '-':
            Path(arguments.diagnostics).write_text(encoded, encoding='utf-8')
        elif sys.stdout:
            print(encoded)
        return 0 if report['ready'] else 1
    from .status_ui import _create_tk_root, _show_startup_error
    root = _create_tk_root()
    try:
        DesktopApplication(root, media_root=arguments.root)
        root.mainloop()
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        _show_startup_error(root, '影片資料庫整理無法啟動', f'{error}\n請重新開啟程式並檢查資料夾權限。')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
