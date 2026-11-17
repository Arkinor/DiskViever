"""Общие UI-примитивы DiskViever.

Содержит кнопки с эффектом наведения, карточки статистики и единую
настройку стилей ttk, чтобы визуализатор и вкладка очистки выглядели
одинаково. Все цвета и шрифты берутся из :mod:`theme`.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import theme


# ---------- Работа с цветом ----------


def _clamp(value: float) -> int:
    return max(0, min(255, int(round(value))))


def _shift(hex_color: str, factor: float) -> str:
    """Осветляет (factor > 0) или затемняет (factor < 0) цвет на долю."""
    color = hex_color.lstrip("#")
    if len(color) != 6:
        return hex_color
    try:
        red = int(color[0:2], 16)
        green = int(color[2:4], 16)
        blue = int(color[4:6], 16)
    except ValueError:
        return hex_color

    if factor >= 0:
        red = _clamp(red + (255 - red) * factor)
        green = _clamp(green + (255 - green) * factor)
        blue = _clamp(blue + (255 - blue) * factor)
    else:
        scale = max(0.0, 1.0 + factor)
        red = _clamp(red * scale)
        green = _clamp(green * scale)
        blue = _clamp(blue * scale)

    return f"#{red:02x}{green:02x}{blue:02x}"


def lighten(hex_color: str, factor: float = 0.14) -> str:
    return _shift(hex_color, abs(factor))


def darken(hex_color: str, factor: float = 0.18) -> str:
    return _shift(hex_color, -abs(factor))


# ---------- Кнопки ----------

#: Вариант -> (фон, цвет текста)
BUTTON_VARIANTS = {
    "primary": (theme.ACCENT_COLOR, theme.TEXT_ON_ACCENT),
    "danger": (theme.ACCENT_COLOR_2, "#ffffff"),
    "secondary": (theme.BACKGROUND_PANEL_COLOR_3, theme.TEXT_COLOR_MAIN),
    "ghost": (theme.BACKGROUND_PANEL_COLOR, theme.TEXT_COLOR_DIM),
}


class FlatButton(tk.Button):
    """Плоская кнопка с подсветкой при наведении и нажатии."""

    def __init__(
        self,
        master,
        text: str = "",
        command=None,
        variant: str = "secondary",
        **kwargs,
    ):
        base_bg, foreground = BUTTON_VARIANTS.get(
            variant, BUTTON_VARIANTS["secondary"]
        )
        self._base_bg = base_bg
        self._hover_bg = lighten(base_bg, 0.14)
        self._press_bg = darken(base_bg, 0.20)
        self._foreground = foreground

        font = kwargs.pop("font", theme.FONT_UI_BOLD)
        padx = kwargs.pop("padx", 10)
        pady = kwargs.pop("pady", 5)

        super().__init__(
            master,
            text=text,
            command=command,
            bg=base_bg,
            fg=foreground,
            activebackground=self._hover_bg,
            activeforeground=foreground,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=padx,
            pady=pady,
            font=font,
            **kwargs,
        )

        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")
        self.bind("<ButtonPress-1>", self._on_press, add="+")
        self.bind("<ButtonRelease-1>", self._on_release, add="+")

    def _enabled(self) -> bool:
        return str(self.cget("state")) != tk.DISABLED

    def _on_enter(self, _event=None):
        if self._enabled():
            self.configure(bg=self._hover_bg)

    def _on_leave(self, _event=None):
        if self._enabled():
            self.configure(bg=self._base_bg)

    def _on_press(self, _event=None):
        if self._enabled():
            self.configure(bg=self._press_bg)

    def _on_release(self, _event=None):
        if self._enabled():
            self.configure(bg=self._hover_bg)


def make_button(parent, text, command, variant: str = "secondary", **kwargs) -> FlatButton:
    """Создаёт кнопку в едином стиле приложения."""
    return FlatButton(parent, text=text, command=command, variant=variant, **kwargs)


def make_divider(parent) -> tk.Frame:
    """Тонкая вертикальная линия-разделитель для панелей действий."""
    return tk.Frame(parent, width=1, bg=theme.BORDER_COLOR_SOFT)


# ---------- Карточки статистики ----------


class StatCard(tk.Frame):
    """Компактная карточка «заголовок — значение — пояснение»."""

    def __init__(self, master, title: str, accent: str = theme.TEXT_COLOR_MAIN, **kwargs):
        super().__init__(
            master,
            bg=theme.BACKGROUND_PANEL_COLOR_2,
            highlightthickness=1,
            highlightbackground=theme.BORDER_COLOR_SOFT,
            bd=0,
            **kwargs,
        )
        self._bg = theme.BACKGROUND_PANEL_COLOR_2
        self.value_var = tk.StringVar(value="—")
        self.sub_var = tk.StringVar(value="")

        body = tk.Frame(self, bg=self._bg)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)

        tk.Label(
            body,
            text=title.upper(),
            bg=self._bg,
            fg=theme.TEXT_COLOR_DIM_2,
            font=theme.FONT_SMALL_BOLD,
            anchor="w",
        ).pack(fill=tk.X)

        tk.Label(
            body,
            textvariable=self.value_var,
            bg=self._bg,
            fg=accent,
            font=theme.FONT_STAT,
            anchor="w",
        ).pack(fill=tk.X)

        tk.Label(
            body,
            textvariable=self.sub_var,
            bg=self._bg,
            fg=theme.TEXT_COLOR_DIM,
            font=theme.FONT_SMALL,
            anchor="w",
        ).pack(fill=tk.X)

    def set(self, value: str, sub: str = "") -> None:
        self.value_var.set(value)
        self.sub_var.set(sub)


# ---------- Стили ttk ----------


def apply_ttk_styles(root) -> ttk.Style:
    """Настраивает общие стили ttk (вкладки, таблицы, прокрутка, прогресс)."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    # --- Вкладки ---
    style.configure("TNotebook", background=theme.BACKGROUND_COLOR, borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=theme.BACKGROUND_PANEL_COLOR,
        foreground=theme.TEXT_COLOR_DIM,
        padding=(20, 9),
        font=("Segoe UI", 10, "bold"),
        borderwidth=0,
    )
    style.map(
        "TNotebook.Tab",
        background=[
            ("selected", theme.BACKGROUND_PANEL_COLOR_2),
            ("active", theme.BACKGROUND_PANEL_COLOR_3),
        ],
        foreground=[
            ("selected", theme.ACCENT_COLOR),
            ("active", theme.TEXT_COLOR_MAIN),
        ],
    )

    # --- Таблицы ---
    style.configure(
        "Treeview",
        background=theme.BACKGROUND_PANEL_COLOR_2,
        fieldbackground=theme.BACKGROUND_PANEL_COLOR_2,
        foreground=theme.TEXT_COLOR_MAIN,
        borderwidth=0,
        rowheight=26,
    )
    style.configure(
        "Treeview.Heading",
        background=theme.BACKGROUND_PANEL_COLOR_3,
        foreground=theme.TEXT_COLOR_DIM,
        relief=tk.FLAT,
        font=theme.FONT_SMALL_BOLD,
        padding=(8, 6),
    )
    style.map(
        "Treeview.Heading",
        background=[("active", theme.BACKGROUND_PANEL_COLOR_3)],
    )
    style.map(
        "Treeview",
        background=[("selected", theme.ACCENT_COLOR)],
        foreground=[("selected", theme.BACKGROUND_COLOR)],
    )

    # --- Прокрутка ---
    for orient in ("Vertical", "Horizontal"):
        style.configure(
            f"{orient}.TScrollbar",
            background=theme.SCROLLBAR_BG,
            troughcolor=theme.SCROLLBAR_TROUGH,
            bordercolor=theme.SCROLLBAR_TROUGH,
            arrowcolor=theme.TEXT_COLOR_DIM,
            relief=tk.FLAT,
            width=12,
        )
        style.map(
            f"{orient}.TScrollbar",
            background=[("active", theme.SCROLLBAR_ACTIVE)],
        )

    # --- Прогресс ---
    style.configure(
        "Accent.Horizontal.TProgressbar",
        troughcolor=theme.BACKGROUND_PANEL_COLOR_3,
        background=theme.ACCENT_COLOR,
        bordercolor=theme.BACKGROUND_PANEL_COLOR_3,
        lightcolor=theme.ACCENT_COLOR,
        darkcolor=theme.ACCENT_COLOR,
        thickness=8,
    )

    # --- Поля ввода и флажки ---
    style.configure(
        "TEntry",
        fieldbackground=theme.BACKGROUND_PANEL_COLOR_2,
        foreground=theme.TEXT_COLOR_MAIN,
        insertcolor=theme.TEXT_COLOR_MAIN,
        bordercolor=theme.BORDER_COLOR,
        padding=6,
    )
    style.configure(
        "TCheckbutton",
        background=theme.BACKGROUND_PANEL_COLOR,
        foreground=theme.TEXT_COLOR_DIM,
        font=theme.FONT_UI,
    )
    style.map(
        "TCheckbutton",
        background=[("active", theme.BACKGROUND_PANEL_COLOR)],
        foreground=[("active", theme.TEXT_COLOR_MAIN)],
    )

    # --- Разделители ---
    style.configure("TSeparator", background=theme.BORDER_COLOR_SOFT)
    style.configure("TPanedwindow", background=theme.BACKGROUND_COLOR)
    style.configure("Sash", sashthickness=8, background=theme.BACKGROUND_COLOR)

    return style
