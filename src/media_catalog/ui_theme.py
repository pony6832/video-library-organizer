"""Shared look and building blocks for the Tk user interfaces.

Tkinter is imported lazily: worker processes import the UI modules for
dispatch and must not pay for (or depend on) a Tcl/Tk runtime.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

FONT = "Microsoft JhengHei UI"

# Calm, light palette. Teal marks the normal path; amber marks anything that
# sends data to the cloud or may cost money; red is reserved for failures.
BG = "#F4F3EF"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#FAF9F6"
BORDER = "#E2DFD7"
DIVIDER = "#ECE9E2"
TEXT = "#1F2328"
TEXT_MUTED = "#5F646B"
TEXT_FAINT = "#9A9DA3"
ACCENT = "#0F766E"
ACCENT_HOVER = "#115E59"
ACCENT_SOFT = "#E3F1EE"
WARN = "#B45309"
WARN_HOVER = "#92400E"
WARN_SOFT = "#FCF1E1"
DANGER = "#B42318"
DANGER_SOFT = "#FBEAE8"
SUCCESS = "#15803D"
SUCCESS_SOFT = "#E5F4EA"
INFO = "#1D4ED8"
INFO_SOFT = "#E8EEFC"
DISABLED_BG = "#F1F0EC"
DISABLED_FG = "#B3B4AF"
BUTTON_FILL = "#EAE7E0"
BUTTON_FILL_HOVER = "#DEDAD1"
TRACK = "#E7E4DC"


@dataclass(frozen=True, slots=True)
class Tone:
    foreground: str
    background: str


TONES = {
    "idle": Tone(TEXT_MUTED, DISABLED_BG),
    "ready": Tone(INFO, INFO_SOFT),
    "running": Tone(SUCCESS, SUCCESS_SOFT),
    "waiting": Tone(WARN, WARN_SOFT),
    "error": Tone(DANGER, DANGER_SOFT),
    "done": Tone(ACCENT, ACCENT_SOFT),
}


def status_tone(status_text: str, light_color: str = "red") -> str:
    """Map a status sentence to a colour family.

    The worker light is binary (fresh heartbeat or not); a red dot for
    "completed" or "catalog ready" read as an error, so the UI shows intent.
    """
    text = status_text or ""
    if light_color == "green":
        return "running"
    if any(word in text for word in ("失敗", "異常", "逾時", "無法", "錯誤")):
        return "error"
    if text.startswith("已完成"):
        return "done"
    if any(word in text for word in ("就緒", "已安全停止")):
        return "ready"
    if any(
        word in text
        for word in ("建立", "更新", "啟動", "停止中", "重新", "等待", "未完成", "停止無回應")
    ):
        return "waiting"
    return "idle"


def enable_high_dpi() -> None:
    """Render crisply on scaled Windows displays instead of bitmap-stretched."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def apply_window_icon(root) -> None:
    """Use the app icon instead of Tk's default feather (window + taskbar)."""
    from pathlib import Path

    icon = Path(__file__).resolve().parent / "assets" / "app.ico"
    if not icon.is_file():
        return
    try:
        root.iconbitmap(default=str(icon))
    except Exception:  # a missing/unsupported icon must never block startup
        pass


def font(size: int = 10, weight: str = "normal") -> tuple[str, int, str]:
    return (FONT, size, weight)


_BUTTON_VARIANTS = {
    # background, foreground, hover background, border
    "primary": (ACCENT, "#FFFFFF", ACCENT_HOVER, ACCENT),
    "warn": (WARN, "#FFFFFF", WARN_HOVER, WARN),
    # Windows draws no highlight border on tk.Button, so every variant is a
    # filled shape; otherwise secondary actions read as plain text.
    "secondary": (BUTTON_FILL, TEXT, BUTTON_FILL_HOVER, BUTTON_FILL),
    "quiet": (BUTTON_FILL, TEXT_MUTED, BUTTON_FILL_HOVER, BUTTON_FILL),
    "danger": (DANGER_SOFT, DANGER, "#F5D5D1", DANGER_SOFT),
}

_button_class = None


def _themed_button_class(tk):
    global _button_class
    if _button_class is not None:
        return _button_class

    class ThemedButton(tk.Button):
        """Flat button whose disabled state is visibly different.

        Plain ``tk.Button`` keeps its background when disabled, which made
        unavailable actions look clickable.
        """

        def __init__(self, master, *, variant: str = "secondary", size: str = "normal", **kwargs):
            self._variant = _BUTTON_VARIANTS[variant]
            background, foreground, hover, border = self._variant
            large = size == "large"
            kwargs.setdefault("font", font(11 if large else 10, "bold"))
            super().__init__(
                master,
                bg=background,
                fg=foreground,
                activebackground=hover,
                activeforeground=foreground,
                disabledforeground=DISABLED_FG,
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground=border,
                highlightcolor=border,
                padx=22 if large else 14,
                pady=10 if large else 6,
                cursor="hand2",
                takefocus=True,
                **kwargs,
            )
            self.bind("<Enter>", lambda _event: self._hover(True), add="+")
            self.bind("<Leave>", lambda _event: self._hover(False), add="+")

        def configure(self, cnf=None, **kwargs):
            result = super().configure(cnf, **kwargs)
            if "state" in kwargs or (isinstance(cnf, dict) and "state" in cnf):
                self._restyle()
            return result

        config = configure

        def set_variant(self, variant: str) -> None:
            self._variant = _BUTTON_VARIANTS[variant]
            background, foreground, hover, _border = self._variant
            super().configure(fg=foreground, activebackground=hover, activeforeground=foreground)
            self._restyle()

        def _enabled(self) -> bool:
            return str(self.cget("state")) != "disabled"

        def _restyle(self) -> None:
            background, _foreground, _hover, border = self._variant
            enabled = self._enabled()
            super().configure(
                bg=background if enabled else DISABLED_BG,
                highlightbackground=border if enabled else DISABLED_BG,
                highlightcolor=border if enabled else DISABLED_BG,
                cursor="hand2" if enabled else "arrow",
            )

        def _hover(self, inside: bool) -> None:
            if not self._enabled():
                return
            background, _foreground, hover, _border = self._variant
            super().configure(bg=hover if inside else background)

    _button_class = ThemedButton
    return ThemedButton


def button(tk, parent, text: str, command, *, variant: str = "secondary", size: str = "normal"):
    return _themed_button_class(tk)(parent, text=text, command=command, variant=variant, size=size)


def configure_ttk(ttk, root) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")
    for name, color in (("Accent", ACCENT), ("Warn", WARN), ("Info", INFO)):
        style.configure(
            f"{name}.Horizontal.TProgressbar",
            troughcolor=TRACK,
            background=color,
            bordercolor=TRACK,
            lightcolor=color,
            darkcolor=color,
            thickness=10,
        )
    style.configure(
        "Thin.Horizontal.TProgressbar",
        troughcolor=TRACK,
        background=INFO,
        bordercolor=TRACK,
        lightcolor=INFO,
        darkcolor=INFO,
        thickness=6,
    )


def card(tk, parent, *, padding: int = 18, background: str = SURFACE):
    frame = tk.Frame(
        parent,
        bg=background,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=BORDER,
        padx=padding,
        pady=padding - 4,
    )
    return frame


def section_title(tk, parent, text: str, *, hint: str = "", background: str = SURFACE):
    row = tk.Frame(parent, bg=background)
    row.pack(fill="x")
    tk.Label(row, text=text, bg=background, fg=TEXT, font=font(12, "bold"), anchor="w").pack(side="left")
    if hint:
        tk.Label(row, text=hint, bg=background, fg=TEXT_FAINT, font=font(9), anchor="e").pack(side="right")
    return row


def divider(tk, parent, *, pady=(12, 10), background: str = DIVIDER):
    line = tk.Frame(parent, bg=background, height=1)
    line.pack(fill="x", pady=pady)
    return line


def auto_wrap(label, *, margin: int = 0) -> None:
    """Wrap a label at its current width instead of a fixed pixel guess."""
    label.bind(
        "<Configure>",
        lambda event: label.configure(wraplength=max(120, event.width - margin)),
        add="+",
    )


class StatTile:
    """Small labelled number, e.g. 影片 128."""

    def __init__(self, tk, parent, title: str, variable, *, background: str = SURFACE_ALT,
                 compact: bool = False) -> None:
        self.frame = tk.Frame(parent, bg=background, padx=14, pady=4 if compact else 8,
                              highlightthickness=1, highlightbackground=DIVIDER)
        tk.Label(self.frame, text=title, bg=background, fg=TEXT_MUTED, font=font(9), anchor="w").pack(fill="x")
        # Fixed width keeps the column from shifting as numbers change.
        tk.Label(self.frame, textvariable=variable, bg=background, fg=TEXT, width=9,
                 font=font(15, "bold"), anchor="w").pack(fill="x")


class StatusPill:
    """Coloured status badge. Keeps a canvas dot for the legacy light API."""

    def __init__(self, tk, parent, variable, *, background: str = SURFACE) -> None:
        self.frame = tk.Frame(parent, bg=TONES["idle"].background, padx=12, pady=5)
        self.light = tk.Canvas(self.frame, width=12, height=12, bg=TONES["idle"].background,
                               highlightthickness=0)
        self.light.pack(side="left")
        self.light_dot = self.light.create_oval(2, 2, 11, 11, fill=TEXT_FAINT, outline="")
        self.label = tk.Label(self.frame, textvariable=variable, bg=TONES["idle"].background,
                              fg=TEXT_MUTED, font=font(10, "bold"))
        self.label.pack(side="left", padx=(7, 0))

    def set_tone(self, tone: str) -> None:
        palette = TONES.get(tone, TONES["idle"])
        for widget in (self.frame, self.light, self.label):
            widget.configure(bg=palette.background)
        self.label.configure(fg=palette.foreground)
        self.light.itemconfigure(self.light_dot, fill=palette.foreground)


class Stepper:
    """Horizontal 1-2-3-4 progress guide for the overall workflow."""

    def __init__(self, tk, parent, steps: tuple[str, ...], *, background: str = BG) -> None:
        self.tk = tk
        self.frame = tk.Frame(parent, bg=background)
        self._items = []
        for index, title in enumerate(steps):
            if index:
                line = tk.Frame(self.frame, bg=BORDER, height=2, width=36)
                line.pack(side="left", padx=10, pady=(0, 0))
                self._items.append(("line", line))
            item = tk.Frame(self.frame, bg=background)
            item.pack(side="left")
            badge = tk.Label(item, text=str(index + 1), width=2, bg=DISABLED_BG, fg=TEXT_MUTED,
                             font=font(10, "bold"))
            badge.pack(side="left")
            label = tk.Label(item, text=title, bg=background, fg=TEXT_MUTED, font=font(10))
            label.pack(side="left", padx=(8, 0))
            self._items.append(("step", (badge, label, index)))
        self.active = -1

    def set_active(self, active: int) -> None:
        self.active = active
        for kind, payload in self._items:
            if kind == "line":
                continue
            badge, label, index = payload
            if index < active:
                badge.configure(text="✓", bg=ACCENT_SOFT, fg=ACCENT)
                label.configure(fg=TEXT_MUTED, font=font(10))
            elif index == active:
                badge.configure(text=str(index + 1), bg=ACCENT, fg="#FFFFFF")
                label.configure(fg=TEXT, font=font(10, "bold"))
            else:
                badge.configure(text=str(index + 1), bg=DISABLED_BG, fg=TEXT_FAINT)
                label.configure(fg=TEXT_FAINT, font=font(10))
        step_index = 0
        for kind, payload in self._items:
            if kind == "line":
                payload.configure(bg=ACCENT if step_index <= active - 1 else BORDER)
            else:
                step_index = payload[2]


class ChoiceCard:
    """A large, clickable radio option with a title and explanation."""

    def __init__(self, tk, parent, *, variable, value: str, title: str, description: str,
                 accent: str = ACCENT, accent_soft: str = ACCENT_SOFT, badge: str = "",
                 compact: bool = False) -> None:
        self.variable = variable
        self.value = value
        self.accent = accent
        self.accent_soft = accent_soft
        self.enabled = True
        self.frame = tk.Frame(parent, bg=SURFACE, padx=14, pady=6 if compact else 10, highlightthickness=1,
                              highlightbackground=BORDER, cursor="hand2")
        top = tk.Frame(self.frame, bg=SURFACE)
        top.pack(fill="x")
        self.dot = tk.Canvas(top, width=16, height=16, bg=SURFACE, highlightthickness=0)
        self.dot.pack(side="left")
        self.ring = self.dot.create_oval(2, 2, 14, 14, outline=TEXT_FAINT, width=2)
        self.center = self.dot.create_oval(5, 5, 11, 11, fill=SURFACE, outline="")
        self.title = tk.Label(top, text=title, bg=SURFACE, fg=TEXT, font=font(11, "bold"))
        self.title.pack(side="left", padx=(8, 0))
        self.badge = None
        if badge:
            self.badge = tk.Label(top, text=badge, bg=accent_soft, fg=accent, font=font(9, "bold"),
                                  padx=6)
            self.badge.pack(side="right")
        self.description = tk.Label(self.frame, text=description, bg=SURFACE, fg=TEXT_MUTED,
                                    font=font(9), justify="left", anchor="w", wraplength=330)
        self.description.pack(fill="x", padx=(24, 0), pady=(3, 0))
        self._surfaces = [self.frame, top, self.dot, self.title, self.description]
        for widget in self._surfaces:
            widget.bind("<Button-1>", self._choose, add="+")
        variable.trace_add("write", lambda *_args: self.refresh())
        self.refresh()

    def _choose(self, _event=None) -> None:
        if self.enabled:
            self.variable.set(self.value)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        cursor = "hand2" if enabled else "arrow"
        for widget in self._surfaces:
            widget.configure(cursor=cursor)
        self.refresh()

    @property
    def selected(self) -> bool:
        return self.variable.get() == self.value

    def refresh(self) -> None:
        selected = self.selected
        background = self.accent_soft if selected else SURFACE
        for widget in self._surfaces:
            widget.configure(bg=background)
        self.frame.configure(highlightbackground=self.accent if selected else BORDER,
                             highlightthickness=2 if selected else 1)
        muted = not self.enabled and not selected
        self.title.configure(fg=TEXT_FAINT if muted else TEXT)
        self.dot.itemconfigure(self.ring, outline=self.accent if selected else TEXT_FAINT)
        self.dot.itemconfigure(self.center, fill=self.accent if selected else background)
