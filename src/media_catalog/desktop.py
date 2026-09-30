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

from .analysis_mode import AnalysisMode
from .setup_environment import EnvironmentSetup, app_data_root
from .status_ui import StatusApplication, StatusViewModel, format_force_confirmation
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
        root.title('影片資料庫整理')
        root.geometry('1080x790')
        root.minsize(920, 740)
        root.after(150, self._drain_events)
        if media_root:
            self._select(str(media_root))

    def _build_layout(self):
        tk, ttk = self.tk, self.ttk
        self.root.option_add('*Font', ('Microsoft JhengHei UI', 11))
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('TCombobox', padding=5)
        panel = tk.Frame(self.root, bg='#0F172A', padx=28, pady=12)
        panel.pack(fill='both', expand=True)
        tk.Label(panel, text='影片資料庫整理', bg='#0F172A', fg='#F8FAFC',
                 font=('Microsoft JhengHei UI', 23, 'bold'), anchor='w').pack(fill='x')
        tk.Label(panel, text='建立清冊 → 分析影片 → 搜尋與檢閱成果｜原始檔案保持不變',
                 bg='#0F172A', fg='#CBD5E1', anchor='w').pack(fill='x', pady=(3, 8))
        status = tk.Frame(panel, bg='#0F172A')
        status.pack(fill='x', pady=(0, 8))
        self.light = tk.Canvas(status, width=22, height=22, bg='#0F172A', highlightthickness=0)
        self.light.pack(side='left')
        self.light_dot = self.light.create_oval(4, 4, 18, 18, fill='#94A3B8', outline='')
        tk.Label(status, textvariable=self.status_var, bg='#0F172A', fg='#F8FAFC', anchor='w').pack(side='left', padx=8)
        self._section(panel, '1  選擇影片資料夾')
        row = tk.Frame(panel, bg='#0F172A')
        row.pack(fill='x', pady=4)
        self.select_button = self._button(row, '選擇資料夾…', self._choose_folder)
        self.select_button.pack(side='left', padx=(0, 12))
        tk.Label(row, textvariable=self.path_var, bg='#0F172A', fg='#E2E8F0', anchor='w',
                 wraplength=710, justify='left').pack(side='left', fill='x', expand=True)
        self._label(panel, '影片統計', self.counts_var)
        self._section(panel, '2  選擇分析方式')
        modes = tk.Frame(panel, bg='#0F172A')
        modes.pack(fill='x', pady=4)
        self.mode_var = tk.StringVar(value='自動分析（本機優先）')
        self.mode_box = ttk.Combobox(modes, textvariable=self.mode_var, state='readonly', width=28,
            values=['自動分析（本機優先）', 'Gemini 強化（雲端付費）'])
        self.mode_box.pack(side='left')
        self.key_status_var = tk.StringVar(value='尚未設定 Key')
        tk.Label(modes, textvariable=self.key_status_var, bg='#0F172A', fg='#CBD5E1').pack(side='left', padx=(16, 8))
        self.key_button = self._button(modes, '設定／更換 Key', self._key_dialog)
        self.key_button.pack(side='left')
        self.check_key_button = self._button(modes, '檢查 Key', self._check_key)
        self.check_key_button.pack(side='left', padx=(8, 0))
        tk.Label(panel, text='本機：Qwen3.5 9B｜自動模式以本機為主；提供 Key 時，低信心縮圖可送至 Gemini。',
                 bg='#0F172A', fg='#CBD5E1', anchor='w').pack(fill='x')
        self._label(panel, '分析進度', self.progress_var)
        self._label(panel, '目前影片', self.current_var)
        self.cloud_var = tk.StringVar(value=cloud_status(None))
        self._label(panel, '雲端狀態', self.cloud_var, wraplength=740)
        self._label(panel, '處理結果', self.failure_var)
        self.progress = ttk.Progressbar(panel, maximum=100)
        self.progress.pack(fill='x', pady=5)
        self.segment_var = tk.StringVar(value='片段進度：尚未開始')
        self._label(panel, '本片進度', self.segment_var)
        self.segment_bar = ttk.Progressbar(panel, maximum=100)
        self.segment_bar.pack(fill='x', pady=(2, 8))
        actions = tk.Frame(panel, bg='#0F172A')
        actions.pack(fill='x', pady=(0, 5))
        self.start_button = self._button(actions, '開始／繼續分析', self._start,
            background='#1D4ED8', active_background='#2563EB')
        self.start_button.pack(side='left', padx=(0, 10))
        self.stop_button = self._button(actions, '安全停止', self._safe_stop)
        self.stop_button.pack(side='left')
        self._section(panel, '3  查看成果')
        footer = tk.Frame(panel, bg='#0F172A')
        footer.pack(fill='x', pady=5)
        self.excel_button = self._button(footer, '開啟 Excel 清冊', lambda: self._open_workspace_path('excel'))
        self.excel_button.pack(side='left', padx=(0, 10))
        self.result_button = self._button(footer, '開啟成果資料夾', lambda: self._open_workspace_path('result'))
        self.result_button.pack(side='left')
        self.setup_button = self._button(footer, '環境檢查／首次設定', self._setup_dialog)
        self.setup_button.pack(side='right')

    def _section(self, panel, text):
        self.tk.Label(panel, text=text, bg='#0F172A', fg='#93C5FD', anchor='w',
            font=('Microsoft JhengHei UI', 12, 'bold')).pack(fill='x', pady=(6, 1))

    def _button(self, *args, **kwargs):
        button = super()._button(*args, **kwargs)
        button.configure(font=('Microsoft JhengHei UI', 10, 'bold'))
        return button

    def _label(self, parent, title, variable, *, wraplength=0):
        row = self.tk.Frame(parent, bg='#1E293B', padx=14, pady=4)
        row.pack(fill='x', pady=2)
        self.tk.Label(row, text=title, width=10, anchor='w', bg='#1E293B', fg='#CBD5E1',
            font=('Microsoft JhengHei UI', 10)).pack(side='left')
        self.tk.Label(row, textvariable=variable, anchor='w', justify='left',
            wraplength=wraplength, bg='#1E293B', fg='#F8FAFC',
            font=('Microsoft JhengHei UI', 11)).pack(side='left', fill='x', expand=True)

    def _choose_folder(self):
        if not self.supervisor.is_busy and not self.setup_busy:
            self._select(self.folder_picker())

    def _key_dialog(self):
        window = self.tk.Toplevel(self.root)
        window.title('設定 Gemini Key')
        window.geometry('430x160')
        window.transient(self.root)
        window.grab_set()
        self.tk.Label(window, text='輸入新的 Gemini Key；儲存後下次啟動會自動使用。',
                      padx=16, pady=12).pack(anchor='w')
        value = self.tk.StringVar()
        entry = self.ttk.Entry(window, textvariable=value, show='•', width=50)
        entry.pack(fill='x', padx=16)
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

        self.ttk.Button(window, text='儲存 Key', command=save).pack(pady=12)

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
        if model.status_text == '正在建立影片清冊…' or self.supervisor.is_busy and self.supervisor.catalog_process is not None and self.supervisor.catalog_process.poll() is None:
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
            self.segment_var.set(f'第 {model.segment_number}／{model.segment_total} 段；已完成前 {model.segment_number - 1} 段')
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
            records = [r for r in CatalogDatabase(self.workspace.database_path).list_records() if r.media_type.startswith('video/')]
            model = StatusViewModel.without_run(status_text=model.status_text, root_text=model.root_text,
                video_count=len(records), total_bytes=sum(r.path.stat().st_size for r in records if r.path.is_file()))
            model = replace(model, progress_text=f'清冊已寫入 {len(records)} 部影片；正在掃描其餘檔案')
        if snapshot.run is None and snapshot.status == 'catalog_ready' and self.workspace:
            from .database import CatalogDatabase
            records = [r for r in CatalogDatabase(self.workspace.database_path).list_records() if r.media_type.startswith('video/')]
            model = StatusViewModel.without_run(status_text=model.status_text, root_text=model.root_text,
                video_count=len(records), total_bytes=sum(r.path.stat().st_size for r in records if r.path.is_file()))
            model = replace(model, progress_text=f'清冊已收錄 {len(records)} 部影片；尚未開始本次分析',
                remaining_text='啟動分析後計算')
        self.cloud_var.set(cloud_status(snapshot.run))
        return model

    def _apply_control_state(self):
        busy = self.supervisor.is_busy or self.setup_busy
        self.select_button.configure(state='disabled' if busy else 'normal')
        self.start_button.configure(state='normal' if self.workspace and not busy else 'disabled')
        self.stop_button.configure(state='normal' if self.supervisor.is_busy else 'disabled')
        self.mode_box.configure(state='disabled' if busy else 'readonly')
        self.key_button.configure(state='disabled' if busy else 'normal')
        self.check_key_button.configure(state='disabled' if busy else 'normal')
        self.setup_button.configure(state='disabled' if busy else 'normal')
        setup_window = getattr(self, 'setup_window', None)
        if setup_window is not None and setup_window.winfo_exists():
            for button in (self.check_button, self.install_button):
                button.configure(state='disabled' if busy else 'normal')
        has_outputs = bool(self.workspace and self.workspace.excel_path.is_file())
        for button in (self.excel_button, self.result_button):
            button.configure(state='normal' if has_outputs else 'disabled')

    def _setup_dialog(self):
        existing = getattr(self, 'setup_window', None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_set()
            return
        window = self.tk.Toplevel(self.root)
        self.setup_window = window
        window.title('首次設定與環境檢查')
        window.geometry('740x420')
        window.transient(self.root)
        self.setup_text = self.tk.StringVar(value='按「檢查環境」只檢查，不下載、不分析影片。\n安裝會下載 FFmpeg、Node.js、Ollama 及約 6.6 GB 的 Qwen3.5 9B 本機模型。\n需要網路、足夠磁碟空間；Windows 可能要求管理員確認。')
        self.tk.Label(window, textvariable=self.setup_text, justify='left', anchor='nw',
            wraplength=690, padx=20, pady=20).pack(fill='both', expand=True)
        buttons = self.tk.Frame(window, padx=20, pady=20)
        buttons.pack(fill='x')
        self.check_button = self.ttk.Button(buttons, text='檢查環境', command=lambda: self._setup_job(False))
        self.check_button.pack(side='left', padx=8)
        self.install_button = self.ttk.Button(buttons, text='安裝缺少元件', command=lambda: self._setup_job(True))
        self.install_button.pack(side='left', padx=8)
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
                lines = [f'{"就緒" if ready else "待設定"}  {name}' for name, ready in result['checks'].items()]
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
                    self.check_key_button.configure(state='normal')
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
