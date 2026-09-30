from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from . import ui_theme as theme
from .analysis_mode import AnalysisMode
from .database import CatalogDatabase
from .excel_catalog import ReviewedPathsError, read_reviewed_paths_strict
from .force_gemini import (
    ForceGeminiEstimate,
    plan_force_run,
    validate_force_environment,
)
from .run_state import AnalysisRun
from .supervisor import SupervisorSnapshot, WorkerSupervisor
from .workspace import MediaWorkspace, WorkspacePathError


def format_force_confirmation(estimate: ForceGeminiEstimate) -> str:
    return (
        "即將使用可用的 Gemini 模型強化未審核媒體：\n\n"
        f"影片：{estimate.video_count}\n"
        f"照片：{estimate.image_count}\n"
        f"已審核：{estimate.reviewed_count}（略過）\n\n"
        f"正常強化請求上限：{estimate.normal_request_limit}\n"
        f"含重試的最壞上限：{estimate.retry_attempt_limit}\n\n"
        "照片只傳送一張縮小預覽；影片每段只傳送 1～3 張縮圖，"
        "不會上傳完整影片或本機完整路徑。要繼續嗎？"
    )


@dataclass(frozen=True, slots=True)
class StatusViewModel:
    light_color: str
    status_text: str
    root_text: str
    video_count: int
    image_count: int
    total_size_text: str
    progress_text: str
    progress_percent: int
    remaining_text: str
    current_text: str
    gemini_text: str
    failure_text: str
    segment_number: int = 0
    segment_total: int = 0

    @classmethod
    def idle(cls) -> "StatusViewModel":
        return cls.without_run(
            status_text="尚未選擇資料夾",
            root_text="尚未選擇",
        )

    @classmethod
    def without_run(
        cls,
        *,
        status_text: str,
        root_text: str,
        video_count: int = 0,
        image_count: int = 0,
        total_bytes: int = 0,
    ) -> "StatusViewModel":
        return cls(
            light_color="red",
            status_text=status_text,
            root_text=root_text,
            video_count=video_count,
            image_count=image_count,
            total_size_text=cls._format_bytes(total_bytes),
            progress_text="0 / 0",
            progress_percent=0,
            remaining_text="0",
            current_text="尚未開始",
            gemini_text="0 / 12",
            failure_text="失敗／降級：0",
        )

    @classmethod
    def from_run(
        cls,
        run: AnalysisRun,
        *,
        worker_alive: bool,
        now: datetime | None = None,
        supervisor_status: str | None = None,
        current_media_name: str = "",
        segment_number: int = 0,
        segment_total: int = 0,
        gemini_used: int = 0,
    ) -> "StatusViewModel":
        now = now or datetime.now(timezone.utc)
        heartbeat_age = cls._heartbeat_age(run.last_heartbeat, now)
        light_color = "red"
        if run.excel_sync_pending:
            status_text = "等待 Excel 關閉"
        elif supervisor_status == "restarting":
            status_text = "正在重新啟動"
        elif supervisor_status == "stopping_stale_worker":
            status_text = "正在安全停止無回應 worker"
        elif supervisor_status == "error":
            status_text = "worker 異常結束"
        elif supervisor_status == "stopped" or run.stop_requested:
            status_text = "已安全停止"
        elif worker_alive and heartbeat_age is not None and heartbeat_age <= 15:
            light_color = "green"
            status_text = "執行中"
        elif worker_alive and heartbeat_age is None:
            status_text = "正在啟動"
        elif worker_alive:
            status_text = "心跳逾時"
        elif supervisor_status == "completed" or run.status == "completed":
            status_text = "已完成"
        elif supervisor_status == "incomplete":
            status_text = "已結束，仍有未完成項目（請看 Excel 錯誤原因）"
        else:
            status_text = "worker 未執行"
        if (
            run.analysis_mode is AnalysisMode.FORCE_GEMINI
            and status_text == "執行中"
        ):
            status_text = "Gemini 強制強化中"

        total = max(0, run.total_media)
        completed = min(max(0, run.completed_media), total)
        percent = round(completed * 100 / total) if total else 0
        current_text = current_media_name or "尚未開始"
        if current_media_name and segment_number and segment_total:
            current_text += f"｜第 {segment_number} / {segment_total} 段"
        return cls(
            light_color=light_color,
            status_text=status_text,
            root_text=str(run.root_path),
            video_count=run.video_count,
            image_count=run.image_count,
            total_size_text=cls._format_bytes(run.total_bytes),
            progress_text=f"{completed} / {total}",
            progress_percent=percent,
            remaining_text=str(max(0, total - completed)),
            current_text=current_text,
            gemini_text=f"{min(max(gemini_used, 0), 12)} / 12",
            failure_text=f"失敗／降級：{max(0, run.failed_media)}",
            segment_number=segment_number,
            segment_total=segment_total,
        )

    @staticmethod
    def _heartbeat_age(value: str | None, now: datetime) -> float | None:
        if not value:
            return None
        try:
            heartbeat = datetime.fromisoformat(value)
        except ValueError:
            return None
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        return max(0.0, (now - heartbeat).total_seconds())

    @staticmethod
    def _format_bytes(value: int) -> str:
        size = max(0, value)
        units = ("B", "KB", "MB", "GB", "TB")
        amount = float(size)
        unit = units[0]
        for unit in units:
            if amount < 1024 or unit == units[-1]:
                break
            amount /= 1024
        if unit == "B":
            return f"{int(amount)} {unit}"
        return f"{amount:.1f} {unit}"


@dataclass(frozen=True, slots=True)
class ControlState:
    select_enabled: bool
    start_enabled: bool
    force_start_enabled: bool
    stop_enabled: bool
    open_outputs_enabled: bool

    @classmethod
    def from_context(
        cls,
        *,
        has_workspace: bool,
        has_outputs: bool,
        busy: bool,
    ) -> "ControlState":
        return cls(
            select_enabled=not busy,
            start_enabled=has_workspace and not busy,
            force_start_enabled=has_workspace and has_outputs and not busy,
            stop_enabled=busy,
            open_outputs_enabled=has_outputs,
        )


MODE_LOCAL = "自動分析（本機優先）"
MODE_GEMINI = "Gemini 強化（雲端付費）"

_PLAIN_PROGRESS = re.compile(r"^\d+ / \d+$")


def progress_detail(progress_text: str, remaining_text: str) -> str:
    """One readable line under the big percentage."""
    if _PLAIN_PROGRESS.match(progress_text):
        return f"已完成 {progress_text}　·　未完成 {remaining_text}"
    return progress_text


def begin_selected_root(
    selected: str,
    supervisor: WorkerSupervisor,
    skill_root: Path,
) -> tuple[MediaWorkspace | None, str]:
    if not selected:
        return None, ""
    try:
        workspace = MediaWorkspace.from_root(Path(selected))
        supervisor.start_catalog(workspace.root, Path(skill_root).resolve())
    except (OSError, RuntimeError, WorkspacePathError) as error:
        return None, str(error)
    return workspace, ""


class StatusApplication:
    def __init__(
        self,
        root,
        *,
        skill_root: Path,
        media_root: Path | None = None,
        supervisor: WorkerSupervisor | None = None,
        folder_picker: Callable[[], str] | None = None,
    ) -> None:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        self.tk = tk
        self.messagebox = messagebox
        self.ttk = ttk
        self.root = root
        self.media_root = Path(media_root).resolve() if media_root else None
        self.skill_root = Path(skill_root).resolve()
        self.workspace = (
            MediaWorkspace.from_root(self.media_root)
            if self.media_root is not None
            else None
        )
        self.supervisor = supervisor or WorkerSupervisor()
        self.folder_picker = folder_picker or (
            lambda: filedialog.askdirectory(mustexist=True)
        )
        self.closing = False

        root.title(self.WINDOW_TITLE)
        theme.apply_window_icon(root)
        root.configure(bg=theme.BG)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        initial = (
            StatusViewModel.without_run(
                status_text="正在啟動",
                root_text=str(self.media_root),
            )
            if self.media_root is not None
            else StatusViewModel.idle()
        )
        self.status_var = tk.StringVar(value=initial.status_text)
        self.path_var = tk.StringVar(value=initial.root_text)
        self.counts_var = tk.StringVar(value="影片：0　影像：0　總容量：0 B")
        self.progress_var = tk.StringVar(value="進度：0 / 0　未完成：0")
        self.current_var = tk.StringVar(value="尚未開始")
        self.gemini_var = tk.StringVar(value="0 / 12")
        self.failure_var = tk.StringVar(value="失敗／降級：0")
        self.video_tile_var = tk.StringVar(value="0")
        self.image_tile_var = tk.StringVar(value="0")
        self.size_tile_var = tk.StringVar(value="0 B")
        self.percent_var = tk.StringVar(value="0%")
        self.detail_var = tk.StringVar(value="選擇資料夾後開始")
        self.mode_var = tk.StringVar(value=MODE_LOCAL)
        self.hint_var = tk.StringVar(value="")

        self._build_layout()
        self._render(initial)
        self._apply_control_state()
        self._fit_window()
        self.root.after(1000, self._refresh)
        if self.media_root is not None:
            self.root.after(0, self._start)

    # Texts and layout hooks; DesktopApplication overrides these.
    WINDOW_TITLE = "Media Catalog A+"
    APP_TITLE = "Media Catalog A+"
    APP_SUBTITLE = "為本機照片與影片建立清冊與內容摘要｜原始檔案不會被移動或修改"
    STEPS = ("選擇資料夾", "建立清冊", "分析媒體", "檢閱成果")
    SOURCE_TITLE = "媒體資料夾"
    DEFAULT_WIDTH = 1060

    def _fit_window(self) -> None:
        """Size the window from its content instead of fixed pixels, so the
        layout also fits on scaled (125%/150%) displays."""
        self.root.update_idletasks()
        # Stay on screen on small, heavily scaled laptops; the action bar is
        # packed first, so any shortfall trims card whitespace, not buttons.
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight() - 80
        required_width = min(self.root.winfo_reqwidth(), screen_width)
        height = min(self.root.winfo_reqheight(), screen_height)
        width = min(max(required_width, self.DEFAULT_WIDTH), screen_width)
        self.root.minsize(required_width, height)
        self.root.geometry(f"{width}x{height}")

    def _build_layout(self) -> None:
        tk = self.tk
        theme.configure_ttk(self.ttk, self.root)
        self.root.option_add("*Font", theme.font(10))

        header = tk.Frame(self.root, bg=theme.SURFACE, padx=28, pady=14)
        header.pack(fill="x")
        tk.Frame(self.root, bg=theme.BORDER, height=1).pack(fill="x")
        titles = tk.Frame(header, bg=theme.SURFACE)
        titles.pack(side="left")
        tk.Label(titles, text=self.APP_TITLE, bg=theme.SURFACE, fg=theme.TEXT,
                 font=theme.font(17, "bold"), anchor="w").pack(anchor="w")
        tk.Label(titles, text=self.APP_SUBTITLE, bg=theme.SURFACE, fg=theme.TEXT_MUTED,
                 font=theme.font(9), anchor="w").pack(anchor="w", pady=(2, 0))
        header_right = tk.Frame(header, bg=theme.SURFACE)
        header_right.pack(side="right")
        self._build_header_actions(header_right)
        self.status_pill = theme.StatusPill(tk, header_right, self.status_var)
        self.status_pill.frame.pack(side="right", padx=(0, 12))
        self.light = self.status_pill.light
        self.light_dot = self.status_pill.light_dot

        footer_wrap = tk.Frame(self.root, bg=theme.SURFACE)
        footer_wrap.pack(fill="x", side="bottom")
        tk.Frame(footer_wrap, bg=theme.BORDER, height=1).pack(fill="x")
        footer = tk.Frame(footer_wrap, bg=theme.SURFACE, padx=28, pady=12)
        footer.pack(fill="x")
        self._build_actions(footer)

        body = tk.Frame(self.root, bg=theme.BG, padx=28, pady=16)
        body.pack(fill="both", expand=True)
        self.stepper = theme.Stepper(tk, body, self.STEPS)
        self.stepper.frame.pack(anchor="w", pady=(0, 14))
        columns = tk.Frame(body, bg=theme.BG)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, minsize=420)
        columns.columnconfigure(1, weight=1)
        columns.rowconfigure(0, weight=1)
        left = tk.Frame(columns, bg=theme.BG)
        left.grid(row=0, column=0, sticky="nsew")
        right = tk.Frame(columns, bg=theme.BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(16, 0))
        self._build_source_card(left)
        self._build_mode_card(left)
        self._build_progress_card(right)

    def _build_header_actions(self, parent) -> None:
        pass

    def _source_tiles(self):
        return (("影片", self.video_tile_var), ("照片", self.image_tile_var),
                ("總容量", self.size_tile_var))

    def _build_source_card(self, parent) -> None:
        tk = self.tk
        card = theme.card(tk, parent)
        card.pack(fill="x")
        theme.section_title(tk, card, self.SOURCE_TITLE)
        path_box = tk.Frame(card, bg=theme.SURFACE_ALT, padx=12, pady=8,
                            highlightthickness=1, highlightbackground=theme.DIVIDER)
        path_box.pack(fill="x", pady=(10, 10))
        # Fixed two-line height: a long path must not push the layout around.
        tk.Label(path_box, textvariable=self.path_var, bg=theme.SURFACE_ALT, fg=theme.TEXT,
                 font=theme.font(10), anchor="nw", justify="left", wraplength=360,
                 height=2).pack(fill="x")
        self.select_button = self._button(card, "選擇資料夾…", self._choose_folder)
        self.select_button.pack(anchor="w")
        tiles = tk.Frame(card, bg=theme.SURFACE)
        tiles.pack(fill="x", pady=(12, 0))
        for index, (title, variable) in enumerate(self._source_tiles()):
            tile = theme.StatTile(tk, tiles, title, variable)
            tile.frame.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 8, 0))
            tiles.columnconfigure(index, weight=1, uniform="tiles")

    def _build_mode_card(self, parent) -> None:
        tk = self.tk
        card = theme.card(tk, parent)
        card.pack(fill="x", pady=(14, 0))
        theme.section_title(tk, card, "分析方式")
        self.local_choice = theme.ChoiceCard(
            tk, card, variable=self.mode_var, value=MODE_LOCAL, title="本機分析",
            description=self._local_mode_description(), badge="免費",
        )
        self.local_choice.frame.pack(fill="x", pady=(10, 8))
        self.gemini_choice = theme.ChoiceCard(
            tk, card, variable=self.mode_var, value=MODE_GEMINI, title="Gemini 雲端強化",
            description="重新分析未審核項目；只上傳縮小預覽圖，開始前會先顯示請求上限並請你確認。",
            accent=theme.WARN, accent_soft=theme.WARN_SOFT, badge="可能計費",
        )
        self.gemini_choice.frame.pack(fill="x")
        self._build_gemini_options(card)
        self.mode_var.trace_add("write", lambda *_args: self._apply_control_state())

    def _local_mode_description(self) -> str:
        return "在這台電腦上辨識；結果資訊不足時才自動請 Gemini 補強（需已設定 Key）。"

    def _build_gemini_options(self, parent) -> None:
        self.tk.Label(parent, text="Gemini 金鑰從環境變數 GEMINI_API_KEY 讀取。",
                      bg=theme.SURFACE, fg=theme.TEXT_FAINT, font=theme.font(9),
                      anchor="w").pack(fill="x", pady=(8, 0))

    def _build_progress_card(self, parent) -> None:
        tk = self.tk
        card = theme.card(tk, parent)
        card.pack(fill="both", expand=True)
        theme.section_title(tk, card, "分析進度")
        headline = tk.Frame(card, bg=theme.SURFACE)
        headline.pack(fill="x", pady=(8, 0))
        self.percent_label = tk.Label(headline, textvariable=self.percent_var, bg=theme.SURFACE,
                                      fg=theme.TEXT, font=theme.font(30, "bold"))
        self.percent_label.pack(side="left")
        tk.Label(headline, textvariable=self.detail_var, bg=theme.SURFACE, fg=theme.TEXT_MUTED,
                 font=theme.font(10), anchor="w", justify="left", wraplength=360
                 ).pack(side="left", padx=(16, 0), pady=(10, 0), fill="x", expand=True)
        self.progress = self.ttk.Progressbar(card, mode="determinate", maximum=100,
                                             style="Accent.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(10, 12))
        metrics = tk.Frame(card, bg=theme.SURFACE)
        metrics.pack(fill="x")
        self.failure_label = tk.Label(metrics, textvariable=self.failure_var, bg=theme.SURFACE,
                                      fg=theme.TEXT_MUTED, font=theme.font(10))
        self.failure_label.pack(side="left")
        tk.Label(metrics, textvariable=self.gemini_var, bg=theme.SURFACE, fg=theme.TEXT_MUTED,
                 font=theme.font(10)).pack(side="right")
        tk.Label(metrics, text="本片 Gemini 用量", bg=theme.SURFACE, fg=theme.TEXT_FAINT,
                 font=theme.font(9)).pack(side="right", padx=(0, 6))
        theme.divider(tk, card)
        tk.Label(card, text="目前項目", bg=theme.SURFACE, fg=theme.TEXT_MUTED, font=theme.font(9),
                 anchor="w").pack(fill="x")
        current_label = tk.Label(card, textvariable=self.current_var, bg=theme.SURFACE,
                                 fg=theme.TEXT, font=theme.font(11, "bold"), anchor="w",
                                 justify="left", wraplength=500)
        current_label.pack(fill="x", pady=(2, 0))
        theme.auto_wrap(current_label, margin=4)
        self._build_progress_extras(card)
        hint = tk.Frame(card, bg=theme.INFO_SOFT, padx=12, pady=9)
        hint.pack(fill="x", side="bottom", pady=(12, 0))
        tk.Label(hint, text="下一步", bg=theme.INFO_SOFT, fg=theme.INFO, font=theme.font(9, "bold")
                 ).pack(side="left", anchor="n")
        hint_label = tk.Label(hint, textvariable=self.hint_var, bg=theme.INFO_SOFT, fg=theme.TEXT,
                              font=theme.font(9), anchor="w", justify="left", wraplength=440)
        hint_label.pack(side="left", padx=(10, 0), fill="x", expand=True)
        theme.auto_wrap(hint_label, margin=4)

    HINTS = (
        "按「選擇資料夾…」挑選要整理的資料夾；程式只讀取原始檔案，不會移動或修改。",
        "正在掃描資料夾並建立清冊；完成後選擇分析方式，再按開始。",
        "選好分析方式後按開始；中途可按「安全停止」，下次會從保存的進度繼續。",
        "分析完成。開啟 Excel 清冊檢閱結果，確認無誤的列可把狀態改成「已審核」。",
    )
    BUSY_HINT = "分析進行中，可以關閉 Excel 但不要移動來源檔案；需要中斷時按「安全停止」。"

    def _build_progress_extras(self, card) -> None:
        pass

    def _build_actions(self, footer) -> None:
        self.start_button = self._button(footer, "開始／繼續分析", self._primary_action,
                                         variant="primary", size="large")
        self.start_button.pack(side="left")
        self.stop_button = self._button(footer, "安全停止", self._safe_stop, variant="danger",
                                        size="large")
        self.stop_button.pack(side="left", padx=(10, 0))
        self.result_button = self._button(footer, "開啟成果資料夾",
                                          lambda: self._open_workspace_path("result"))
        self.result_button.pack(side="right")
        self.excel_button = self._button(footer, "開啟 Excel 清冊",
                                         lambda: self._open_workspace_path("excel"))
        self.excel_button.pack(side="right", padx=(0, 10))

    def _button(self, parent, text: str, command, *, variant: str = "secondary",
                size: str = "normal"):
        return theme.button(self.tk, parent, text, command, variant=variant, size=size)

    @property
    def gemini_selected(self) -> bool:
        mode_var = getattr(self, "mode_var", None)
        return mode_var is not None and mode_var.get().startswith("Gemini")

    def _primary_action(self) -> None:
        if self.gemini_selected:
            self._start_force_gemini()
        else:
            self._start()

    def _stage(self, model: StatusViewModel) -> int:
        if self.workspace is None:
            return 0
        text = model.status_text
        if not self.workspace.excel_path.is_file():
            return 1
        if "清冊" in text and ("建立" in text or "更新" in text):
            return 1
        if text.startswith("已完成"):
            return 3
        return 2

    def _start(self) -> None:
        if self.workspace is None or self.media_root is None:
            return
        if self.supervisor.is_busy:
            return
        try:
            if (
                self.workspace.database_path.is_file()
                and self.workspace.excel_path.is_file()
            ):
                self.supervisor.start(
                    self.media_root,
                    self.skill_root,
                    mode=AnalysisMode.AUTO,
                )
            else:
                self.supervisor.start_catalog(
                    self.media_root, self.skill_root
                )
        except (OSError, RuntimeError, WorkspacePathError) as error:
            self.status_var.set(f"啟動失敗：{error}")
            self.light.itemconfigure(self.light_dot, fill="#EF4444")

    def _start_force_gemini(self) -> None:
        if self.workspace is None or self.media_root is None:
            return
        if self.supervisor.is_busy:
            return
        environment_error = validate_force_environment(os.environ)
        if environment_error:
            self.messagebox.showerror(
                "無法啟動 Gemini 強化", environment_error
            )
            return
        try:
            if not self.workspace.database_path.is_file():
                raise FileNotFoundError("找不到 SQLite 媒體清冊")
            records = CatalogDatabase(
                self.workspace.database_path
            ).list_records()
            reviewed_paths = read_reviewed_paths_strict(
                self.workspace.excel_path
            )
            estimate, eligible_ids = plan_force_run(records, reviewed_paths)
        except (
            OSError,
            RuntimeError,
            ReviewedPathsError,
            WorkspacePathError,
        ) as error:
            self.messagebox.showerror("無法讀取媒體清冊", str(error))
            return
        if not eligible_ids:
            self.messagebox.showinfo(
                "沒有需要強化的媒體",
                "目前沒有未審核的照片或影片。",
            )
            return
        confirmed = self.messagebox.askokcancel(
            "確認強制 Gemini 強化",
            format_force_confirmation(estimate),
        )
        if not confirmed:
            return
        try:
            self.supervisor.start(
                self.media_root,
                self.skill_root,
                mode=AnalysisMode.FORCE_GEMINI,
            )
        except (OSError, RuntimeError, WorkspacePathError) as error:
            self.messagebox.showerror("Gemini 強化啟動失敗", str(error))

    def _choose_folder(self) -> None:
        if self.supervisor.is_busy:
            return
        selected = self.folder_picker()
        workspace, error = begin_selected_root(
            selected, self.supervisor, self.skill_root
        )
        if error:
            self.messagebox.showerror("無法使用此資料夾", error)
            return
        if workspace is None:
            return
        self.workspace = workspace
        self.media_root = workspace.root
        self._render(
            StatusViewModel.without_run(
                status_text="正在建立／更新清冊",
                root_text=str(workspace.root),
            )
        )
        self._apply_control_state()

    def _refresh(self) -> None:
        try:
            snapshot = self.supervisor.poll()
            model = self._view_model(snapshot)
            self._render(model)
            self._apply_control_state()
            if self.closing and not snapshot.worker_alive:
                self.root.destroy()
                return
        except (OSError, RuntimeError, sqlite3.Error) as error:
            self.status_var.set(f"狀態讀取失敗：{error}")
            self.light.itemconfigure(self.light_dot, fill="#EF4444")
        except Exception as error:  # never let one bad poll stop the refresh loop
            self.status_var.set(f"狀態讀取失敗：{type(error).__name__}")
            self.light.itemconfigure(self.light_dot, fill="#EF4444")
        self.root.after(1000, self._refresh)

    def _view_model(self, snapshot: SupervisorSnapshot) -> StatusViewModel:
        run = snapshot.run
        if run is None:
            root_text = (
                str(self.media_root)
                if self.media_root is not None
                else "尚未選擇"
            )
            status_text = {
                "idle": "尚未選擇資料夾",
                "cataloging": "正在建立／更新清冊",
                "catalog_ready": "清冊就緒，請選擇分析模式",
                "stopped": "已安全停止",
                "error": snapshot.error_text or "建立媒體清冊失敗",
            }.get(snapshot.status, "worker 未執行")
            video_count = image_count = total_bytes = 0
            if (
                snapshot.status == "catalog_ready"
                and self.workspace is not None
                and self.workspace.database_path.is_file()
            ):
                video_count, image_count, total_bytes = CatalogDatabase(
                    self.workspace.database_path
                ).media_summary()
            return StatusViewModel.without_run(
                status_text=status_text,
                root_text=root_text,
                video_count=video_count,
                image_count=image_count,
                total_bytes=total_bytes,
            )
        media_name = ""
        segment_number = 0
        segment_total = 0
        gemini_used = 0
        if run.current_media_id:
            if self.workspace is None or self.supervisor.store is None:
                raise RuntimeError("Analysis run has no workspace state")
            record = CatalogDatabase(self.workspace.database_path).get_record(
                run.current_media_id
            )
            media_name = record.path.name if record is not None else run.current_media_id
            segment_number, segment_total = self.supervisor.store.segment_progress(
                run.current_media_id, run.current_segment_id
            )
            gemini_used, _ = self.supervisor.store.gemini_usage(run.current_media_id)
        return StatusViewModel.from_run(
            run,
            worker_alive=snapshot.worker_alive,
            supervisor_status=snapshot.status,
            current_media_name=media_name,
            segment_number=segment_number,
            segment_total=segment_total,
            gemini_used=gemini_used,
        )

    def _render(self, model: StatusViewModel) -> None:
        self.status_pill.set_tone(theme.status_tone(model.status_text, model.light_color))
        self.status_var.set(model.status_text)
        self.path_var.set(model.root_text)
        self.counts_var.set(
            f"影片：{model.video_count}　影像：{model.image_count}"
            f"　總容量：{model.total_size_text}"
        )
        self.video_tile_var.set(str(model.video_count))
        self.image_tile_var.set(str(model.image_count))
        self.size_tile_var.set(model.total_size_text)
        self.progress_var.set(
            f"進度：{model.progress_text}　未完成：{model.remaining_text}"
        )
        idle_total = model.progress_text == "0 / 0"
        self.percent_var.set(f"{model.progress_percent}%")
        self.percent_label.configure(fg=theme.TEXT_FAINT if idle_total else theme.TEXT)
        self.detail_var.set(
            "尚未開始分析" if idle_total
            else progress_detail(model.progress_text, model.remaining_text)
        )
        self.current_var.set(model.current_text)
        self.gemini_var.set(model.gemini_text)
        self.failure_var.set(model.failure_text)
        has_failures = not model.failure_text.rstrip().endswith("：0")
        self.failure_label.configure(fg=theme.DANGER if has_failures else theme.TEXT_MUTED)
        self.progress["value"] = model.progress_percent
        stage = self._stage(model)
        self._last_stage = stage
        self.stepper.set_active(stage)
        busy = bool(getattr(self.supervisor, "is_busy", False))
        self.hint_var.set(self.BUSY_HINT if busy and stage == 2 else self.HINTS[stage])

    def _safe_stop(self) -> None:
        self.supervisor.request_safe_stop()

    def _apply_control_state(self) -> None:
        has_workspace = self.workspace is not None
        has_outputs = bool(
            self.workspace is not None
            and self.workspace.database_path.is_file()
            and self.workspace.excel_path.is_file()
        )
        busy = self.supervisor.is_busy
        state = ControlState.from_context(
            has_workspace=has_workspace,
            has_outputs=has_outputs,
            busy=busy,
        )
        gemini = self.gemini_selected
        self.select_button.configure(
            state="normal" if state.select_enabled else "disabled"
        )
        start_enabled = state.force_start_enabled if gemini else state.start_enabled
        self.start_button.configure(state="normal" if start_enabled else "disabled")
        self._label_primary_action(busy=busy, gemini=gemini, has_outputs=has_outputs)
        self.local_choice.set_enabled(not busy)
        self.gemini_choice.set_enabled(not busy)
        self.stop_button.configure(
            state="normal" if state.stop_enabled else "disabled"
        )
        output_state = "normal" if state.open_outputs_enabled else "disabled"
        self.excel_button.configure(state=output_state)
        self.result_button.configure(state=output_state)

    def _label_primary_action(self, *, busy: bool, gemini: bool, has_outputs: bool) -> None:
        completed = getattr(self, "_last_stage", 0) == 3
        if busy:
            text = "處理中…"
        elif completed and not gemini:
            text = "重新檢查並繼續"
        elif gemini:
            text = "開始 Gemini 強化"
        elif self.workspace is not None and not has_outputs:
            text = "建立清冊"
        else:
            text = "開始／繼續分析"
        self.start_button.configure(text=text)
        if gemini:
            self.start_button.set_variant("warn")
        else:
            self.start_button.set_variant("secondary" if completed and not busy else "primary")
        # After a finished run, reviewing the workbook is the next step.
        self.excel_button.set_variant("primary" if completed and not busy else "secondary")
        # Exactly one highlighted next action: pick a folder first, then start.
        self.select_button.set_variant("primary" if self.workspace is None else "secondary")

    def _open_workspace_path(self, kind: str) -> None:
        if self.workspace is None:
            self.messagebox.showerror("無法開啟", "尚未選擇資料夾")
            return
        path = (
            self.workspace.excel_path
            if kind == "excel"
            else self.workspace.result_root
        )
        try:
            self._open(path)
        except OSError as error:
            self.messagebox.showerror("無法開啟", str(error))

    @staticmethod
    def _open(path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError(path)
        os.startfile(str(path))

    def _on_close(self) -> None:
        snapshot = self.supervisor.poll()
        if not snapshot.worker_alive:
            self.root.destroy()
            return
        confirmed = self.messagebox.askokcancel(
            "安全停止後關閉",
            "程式會完成目前片段並寫入進度後關閉。\n"
            "要安全停止後關閉嗎？",
        )
        if confirmed:
            self.closing = True
            self.supervisor.request_safe_stop()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="media-catalog-status")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--skill-root", type=Path, default=None)
    return parser


def _create_tk_root():
    import tkinter as tk

    theme.enable_high_dpi()
    try:
        return tk.Tk()
    except tk.TclError as error:
        raise RuntimeError(f"Tkinter 無法啟動：{error}") from error


def _show_startup_error(root, title: str, message: str) -> None:
    from tkinter import messagebox

    root.withdraw()
    messagebox.showerror(title, message, parent=root)
    root.destroy()


def _default_skill_root() -> Path:
    candidate = Path(sys.prefix).resolve().parent
    launcher = candidate / "scripts" / "run_media_analysis_ui.ps1"
    if not launcher.is_file():
        raise WorkspacePathError(
            "無法從私有 runtime 判斷 Skill 路徑，請重新執行安裝器"
        )
    return candidate


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        root = _create_tk_root()
    except (OSError, RuntimeError) as error:
        print(f"MEDIA_STATUS_UI_ERROR {error}", file=sys.stderr)
        return 2

    try:
        skill_root = (
            arguments.skill_root.resolve()
            if arguments.skill_root is not None
            else _default_skill_root()
        )
        media_root = None
        if arguments.root is not None:
            workspace = MediaWorkspace.from_root(arguments.root)
            if (
                not workspace.database_path.is_file()
                or not workspace.excel_path.is_file()
            ):
                raise WorkspacePathError("找不到媒體清冊，請先建立清冊")
            media_root = workspace.root
        StatusApplication(
            root,
            media_root=media_root,
            skill_root=skill_root,
        )
        root.mainloop()
        return 0
    except (OSError, RuntimeError, WorkspacePathError) as error:
        _show_startup_error(
            root,
            "Media Catalog A+ 啟動失敗",
            str(error),
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
