"""Вкладка «Умная очистка»: поиск и безопасное удаление мусора."""

from __future__ import annotations

import csv
import os
import subprocess
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import theme
import ui_kit

from .actions import delete_items
from .models import CleanableItem, Risk, ScanResult
from .scanner import Scanner


def _human(size: int) -> str:
    units = ("Б", "КБ", "МБ", "ГБ", "ТБ", "ПБ")
    value = float(size)
    for unit in units:
        if abs(value) < 1024.0:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} ЭБ"


def _reveal(path: str) -> None:
    """Открывает каталог (или родителя файла) в проводнике."""
    if not path:
        return
    try:
        target = path if os.path.isdir(path) else os.path.dirname(path)
        if hasattr(os, "startfile"):
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            opener = "open" if os.uname().sysname == "Darwin" else "xdg-open"
            subprocess.Popen([opener, target])
    except Exception:
        pass


class SmartCleanerTab(tk.Frame):
    """Вкладка умной очистки. Не влияет на работу визуализатора."""

    def __init__(self, master):
        super().__init__(master, bg=theme.BACKGROUND_COLOR)

        self.items: list[CleanableItem] = []
        self.item_by_iid: dict[str, CleanableItem] = {}
        self.last_result: ScanResult | None = None
        self.scanning = False
        self.cancel_event = threading.Event()

        self._pending_status: str | None = None
        self._status_job = None
        self._details_item: CleanableItem | None = None
        self._filter_placeholder = "Фильтр: имя, путь или категория…"

        self._build_ui()

    # ==================== UI ====================

    def _build_ui(self) -> None:
        ui_kit.apply_ttk_styles(self)
        self._configure_styles()

        header = tk.Frame(self, bg=theme.BACKGROUND_PANEL_COLOR)
        header.pack(fill=tk.X)

        # ---------- Заголовок + карточки статистики ----------
        top_row = tk.Frame(header, bg=theme.BACKGROUND_PANEL_COLOR)
        top_row.pack(fill=tk.X, padx=16, pady=(12, 8))

        title_box = tk.Frame(top_row, bg=theme.BACKGROUND_PANEL_COLOR)
        title_box.pack(side=tk.LEFT)

        tk.Label(
            title_box, text="🧹 Умная очистка",
            bg=theme.BACKGROUND_PANEL_COLOR, fg=theme.ACCENT_COLOR,
            font=theme.FONT_TITLE,
        ).pack(anchor="w")
        tk.Label(
            title_box,
            text="Системный мусор и остатки удалённых программ",
            bg=theme.BACKGROUND_PANEL_COLOR, fg=theme.TEXT_COLOR_DIM,
            font=theme.FONT_SMALL,
        ).pack(anchor="w", pady=(2, 0))

        cards = tk.Frame(top_row, bg=theme.BACKGROUND_PANEL_COLOR)
        cards.pack(side=tk.RIGHT)

        self.card_total = ui_kit.StatCard(
            cards, "Найдено", theme.TEXT_COLOR_MAIN,
        )
        self.card_safe = ui_kit.StatCard(
            cards, "Безопасно", theme.SUCCESS_COLOR,
        )
        self.card_selected = ui_kit.StatCard(
            cards, "Выбрано", theme.ACCENT_COLOR,
        )
        self.card_orphans = ui_kit.StatCard(
            cards, "Остатки", theme.WARNING_COLOR,
        )
        for card in (
            self.card_total, self.card_safe, self.card_selected, self.card_orphans,
        ):
            card.pack(side=tk.LEFT, padx=(8, 0))

        # ---------- Кнопки действий ----------
        actions = tk.Frame(header, bg=theme.BACKGROUND_PANEL_COLOR)
        actions.pack(fill=tk.X, padx=16, pady=(0, 8))

        self.scan_btn = ui_kit.make_button(
            actions, "🔍 Анализ", self.start_scan, "primary",
        )
        self.scan_btn.pack(side=tk.LEFT)

        self.cancel_btn = ui_kit.make_button(
            actions, "Стоп", self.cancel_scan, "secondary",
        )
        self.cancel_btn.pack(side=tk.LEFT, padx=(8, 0))

        ui_kit.make_divider(actions).pack(
            side=tk.LEFT, fill=tk.Y, padx=10, pady=4,
        )

        ui_kit.make_button(
            actions, "Выбрать безопасное", self.select_safe, "ghost",
        ).pack(side=tk.LEFT)

        ui_kit.make_button(
            actions, "Снять выбор", self.clear_selection, "ghost",
        ).pack(side=tk.LEFT, padx=(4, 0))

        ui_kit.make_divider(actions).pack(
            side=tk.LEFT, fill=tk.Y, padx=10, pady=4,
        )

        self.delete_btn = ui_kit.make_button(
            actions, "🗑 Удалить", self.delete_selected, "danger",
        )
        self.delete_btn.pack(side=tk.LEFT)

        ui_kit.make_button(
            actions, "Открыть", self.open_selected, "ghost",
        ).pack(side=tk.LEFT, padx=(4, 0))

        ui_kit.make_button(
            actions, "Отчёт CSV", self.export_report, "ghost",
        ).pack(side=tk.LEFT, padx=(4, 0))

        self.recycle_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            actions, text="В корзину", variable=self.recycle_var,
            style="TCheckbutton",
        ).pack(side=tk.RIGHT, padx=(10, 0))

        filter_frame = tk.Frame(
            actions, bg=theme.BACKGROUND_PANEL_COLOR_2,
            highlightthickness=1, highlightbackground=theme.BORDER_COLOR_SOFT,
        )
        filter_frame.pack(side=tk.RIGHT, padx=(0, 6))

        tk.Label(
            filter_frame, text="🔎", bg=theme.BACKGROUND_PANEL_COLOR_2,
            fg=theme.TEXT_COLOR_DIM, font=theme.FONT_UI,
        ).pack(side=tk.LEFT, padx=(8, 2))

        self.filter_var = tk.StringVar()
        self.filter_entry = tk.Entry(
            filter_frame, textvariable=self.filter_var, width=24,
            bg=theme.BACKGROUND_PANEL_COLOR_2, fg=theme.TEXT_COLOR_DIM_2,
            insertbackground=theme.TEXT_COLOR_MAIN, relief=tk.FLAT,
            bd=0, highlightthickness=0,
        )
        self.filter_entry.pack(side=tk.LEFT, padx=(0, 6), pady=4)
        self.filter_entry.bind("<KeyRelease>", lambda event: self._populate())
        self.filter_entry.bind("<FocusIn>", self._on_filter_focus_in)
        self.filter_entry.bind("<FocusOut>", self._on_filter_focus_out)
        self.filter_entry.insert(0, self._filter_placeholder)

        # ---------- Прогресс, статус, легенда ----------
        status_row = tk.Frame(header, bg=theme.BACKGROUND_PANEL_COLOR)
        status_row.pack(fill=tk.X, padx=16, pady=(0, 12))

        self.progress = ttk.Progressbar(
            status_row, mode="indeterminate", length=220,
            style="Accent.Horizontal.TProgressbar",
        )

        self.status_var = tk.StringVar(
            value="Нажмите «Анализ», чтобы найти мусор и остатки удалённых программ."
        )
        tk.Label(
            status_row, textvariable=self.status_var,
            bg=theme.BACKGROUND_PANEL_COLOR, fg=theme.TEXT_COLOR_DIM,
            font=theme.FONT_UI,
        ).pack(side=tk.LEFT)

        legend = tk.Frame(status_row, bg=theme.BACKGROUND_PANEL_COLOR)
        legend.pack(side=tk.RIGHT)
        for risk in (Risk.SAFE, Risk.CAUTION, Risk.DANGER):
            tk.Label(
                legend, text=f"● {risk.label}", bg=theme.BACKGROUND_PANEL_COLOR,
                fg=risk.color, font=theme.FONT_SMALL_BOLD,
            ).pack(side=tk.LEFT, padx=(10, 0))

        # ---------- Тело: таблица + подробности ----------
        body = tk.Frame(self, bg=theme.BACKGROUND_COLOR)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        paned = tk.PanedWindow(
            body, orient=tk.HORIZONTAL, bg=theme.BACKGROUND_COLOR,
            sashwidth=8, bd=0, sashrelief=tk.FLAT,
        )
        paned.pack(fill=tk.BOTH, expand=True)

        tree_frame = tk.Frame(paned, bg=theme.BACKGROUND_PANEL_COLOR)
        details_frame = tk.Frame(paned, bg=theme.BACKGROUND_PANEL_COLOR)
        paned.add(tree_frame, stretch="always")
        paned.add(details_frame, stretch="never")

        self.tree = ttk.Treeview(
            tree_frame, columns=("size", "risk"), show="tree headings",
            style="Cleaner.Treeview", selectmode="browse",
        )
        self.tree.heading("#0", text="Элемент", anchor=tk.W)
        self.tree.heading("size", text="Размер", anchor=tk.E)
        self.tree.heading("risk", text="Риск", anchor=tk.CENTER)
        self.tree.column("#0", width=560, anchor=tk.W)
        self.tree.column("size", width=110, anchor=tk.E, stretch=False)
        self.tree.column("risk", width=120, anchor=tk.CENTER, stretch=False)

        self.tree.tag_configure(
            "category", foreground=theme.ACCENT_COLOR,
            font=("Segoe UI", 9, "bold"),
        )
        self.tree.tag_configure("safe", foreground=theme.SUCCESS_COLOR)
        self.tree.tag_configure("caution", foreground=theme.WARNING_COLOR)
        self.tree.tag_configure("danger", foreground=theme.DANGER_COLOR)
        self.tree.tag_configure("disabled", foreground=theme.TEXT_COLOR_DIM_2)
        self.tree.tag_configure(
            "empty", foreground=theme.TEXT_COLOR_DIM_2,
            font=("Segoe UI", 10, "italic"),
        )

        scrollbar = ttk.Scrollbar(
            tree_frame, orient=tk.VERTICAL, command=self.tree.yview,
        )
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", lambda event: self.open_selected())
        self.tree.bind("<space>", self._on_space)
        self.tree.bind("<Button-3>", self._on_tree_right_click)

        # ---------- Панель подробностей ----------
        tk.Label(
            details_frame, text="Подробности", bg=theme.BACKGROUND_PANEL_COLOR,
            fg=theme.TEXT_COLOR_DIM, font=theme.FONT_UI_BOLD,
        ).pack(anchor="w", padx=12, pady=(10, 4))

        details_actions = tk.Frame(details_frame, bg=theme.BACKGROUND_PANEL_COLOR)
        details_actions.pack(fill=tk.X, padx=12, pady=(0, 10), side=tk.BOTTOM)

        self._details_open_btn = ui_kit.make_button(
            details_actions, "📂 Открыть", self._details_open, "secondary",
        )
        self._details_open_btn.pack(side=tk.LEFT)

        self._details_copy_btn = ui_kit.make_button(
            details_actions, "📋 Путь", self._details_copy, "secondary",
        )
        self._details_copy_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.details = tk.Text(
            details_frame, width=42, wrap=tk.WORD,
            bg=theme.BACKGROUND_PANEL_COLOR_2, fg=theme.TEXT_COLOR_MAIN,
            relief=tk.FLAT, padx=12, pady=10, font=theme.FONT_UI,
            insertbackground=theme.TEXT_COLOR_MAIN, state=tk.DISABLED,
            spacing1=2, spacing3=2, bd=0, highlightthickness=0,
        )
        self.details.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))
        self.details.tag_configure(
            "title", font=("Segoe UI", 11, "bold"), foreground=theme.ACCENT_COLOR,
        )
        self.details.tag_configure("safe", foreground=theme.SUCCESS_COLOR)
        self.details.tag_configure("caution", foreground=theme.WARNING_COLOR)
        self.details.tag_configure("danger", foreground=theme.DANGER_COLOR)
        self.details.tag_configure("dim", foreground=theme.TEXT_COLOR_DIM)
        self.details.tag_configure(
            "label", foreground=theme.TEXT_COLOR_DIM, font=theme.FONT_SMALL_BOLD,
        )
        self.details.tag_configure(
            "hint", foreground=theme.TEXT_COLOR_DIM,
            font=("Segoe UI", 8, "italic"),
        )
        self.details.tag_configure(
            "mono", font=theme.FONT_MONO, foreground=theme.TEXT_COLOR_MAIN,
        )
        self.details.tag_configure(
            "admin", foreground=theme.WARNING_COLOR,
            font=theme.FONT_SMALL_BOLD,
        )

        self._reset_cards()
        self._set_scanning(False)
        self._show_placeholder_details()
        self._populate()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.configure(
            "Cleaner.Treeview",
            background=theme.BACKGROUND_PANEL_COLOR_2,
            fieldbackground=theme.BACKGROUND_PANEL_COLOR_2,
            foreground=theme.TEXT_COLOR_MAIN,
            borderwidth=0, rowheight=26,
        )
        style.configure(
            "Cleaner.Treeview.Heading",
            background=theme.BACKGROUND_PANEL_COLOR_3,
            foreground=theme.TEXT_COLOR_DIM,
            font=theme.FONT_SMALL_BOLD,
            padding=(8, 6),
        )
        style.map(
            "Cleaner.Treeview",
            background=[("selected", theme.ACCENT_COLOR)],
            foreground=[("selected", theme.BACKGROUND_COLOR)],
        )

    # ==================== Фильтр ====================

    def _on_filter_focus_in(self, _event=None):
        if self.filter_var.get() == self._filter_placeholder:
            self.filter_entry.delete(0, tk.END)
            self.filter_entry.configure(fg=theme.TEXT_COLOR_MAIN)

    def _on_filter_focus_out(self, _event=None):
        if not self.filter_var.get().strip():
            self.filter_entry.delete(0, tk.END)
            self.filter_entry.insert(0, self._filter_placeholder)
            self.filter_entry.configure(fg=theme.TEXT_COLOR_DIM_2)

    # ==================== Сканирование ====================

    def start_scan(self) -> None:
        if self.scanning:
            return
        self.cancel_event = threading.Event()
        self._set_scanning(True, "Анализ дисков…")
        self._clear_tree()
        self.item_by_iid.clear()
        self.items = []
        self._reset_cards()
        self._show_placeholder_details()

        scanner = Scanner()
        threading.Thread(
            target=self._scan_worker, args=(scanner,), daemon=True,
        ).start()

    def _scan_worker(self, scanner: Scanner) -> None:
        try:
            result = scanner.scan(
                progress_cb=self._on_progress,
                cancel_event=self.cancel_event,
            )
        except Exception as error:  # noqa: BLE001
            message = str(error)
            try:
                self.after(0, lambda: self._on_scan_failed(message))
            except tk.TclError:
                pass
            return

        try:
            self.after(0, lambda: self._on_scan_done(result))
        except tk.TclError:
            pass

    def _on_progress(self, text: str) -> None:
        self._pending_status = text
        if self._status_job is None:
            try:
                self._status_job = self.after(120, self._flush_status)
            except tk.TclError:
                self._status_job = None

    def _flush_status(self) -> None:
        self._status_job = None
        if self._pending_status:
            self.status_var.set(self._pending_status)
            self._pending_status = None

    def _on_scan_done(self, result: ScanResult) -> None:
        self.last_result = result
        self.items = result.items
        self._populate()
        self._update_summary()
        self._select_first_item()
        self._set_scanning(False)

        if self.cancel_event.is_set():
            self.status_var.set(
                f"Анализ остановлен. Уже найдено: {len(result.items)} элемент(ов)."
            )
            return

        self.status_var.set(
            f"Готово за {result.duration:.1f} с · проверено правил: {result.rules_checked} · "
            f"установленных программ: {result.installed_programs} · ошибок: {result.errors}"
        )
        if not result.items:
            self.status_var.set("Мусор не найден — диск в хорошем состоянии.")

    def _on_scan_failed(self, message: str) -> None:
        self._set_scanning(False)
        self.status_var.set(f"Ошибка анализа: {message}")

    def cancel_scan(self) -> None:
        if not self.scanning:
            return
        self.cancel_event.set()
        self.status_var.set("Останавливаю анализ…")

    def _set_scanning(self, flag: bool, text: str | None = None) -> None:
        self.scanning = flag
        if flag:
            try:
                self.progress.pack(side=tk.LEFT, padx=(12, 0))
                self.progress.start(12)
            except Exception:
                pass
            self.scan_btn.configure(state=tk.DISABLED)
            self.delete_btn.configure(state=tk.DISABLED)
            self.cancel_btn.configure(state=tk.NORMAL)
            if text:
                self.status_var.set(text)
        else:
            try:
                self.progress.stop()
                self.progress.pack_forget()
            except Exception:
                pass
            self.scan_btn.configure(state=tk.NORMAL)
            self.delete_btn.configure(state=tk.NORMAL)
            self.cancel_btn.configure(state=tk.DISABLED)

    # ==================== Таблица ====================

    def _clear_tree(self) -> None:
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)

    def _populate(self) -> None:
        self._clear_tree()
        self.item_by_iid.clear()

        query = self.filter_var.get().strip().lower()
        if query == self._filter_placeholder.lower():
            query = ""

        groups: dict[str, list[CleanableItem]] = {}
        for item in self.items:
            if query and not (
                query in item.name.lower()
                or query in item.path.lower()
                or query in item.category.lower()
            ):
                continue
            groups.setdefault(item.category, []).append(item)

        if not groups:
            self._show_empty_state(query)
            return

        for category in sorted(groups, key=lambda c: -sum(i.size for i in groups[c])):
            group = sorted(groups[category], key=lambda i: -i.size)
            total = sum(i.size for i in group)
            cat_iid = f"cat::{category}"
            self.tree.insert(
                "", "end", iid=cat_iid,
                text=f"📁 {category}  ({len(group)})",
                values=(_human(total), ""), open=True, tags=("category",),
            )
            for index, item in enumerate(group):
                iid = f"item::{category}::{index}"
                self.item_by_iid[iid] = item
                tags = (item.risk.value,)
                if not item.can_delete:
                    tags = (item.risk.value, "disabled")
                self.tree.insert(
                    cat_iid, "end", iid=iid,
                    text=self._item_text(item),
                    values=(_human(item.size), f"● {item.risk.label}"),
                    tags=tags,
                )

    def _show_empty_state(self, query: str) -> None:
        if self.last_result is None:
            message = "Нажмите «Анализ», чтобы начать поиск"
        elif query:
            message = "Ничего не найдено по фильтру"
        else:
            message = "✨ Мусор не найден — всё чисто"
        self.tree.insert("", "end", iid="empty", text=message, tags=("empty",))

    @staticmethod
    def _item_text(item: CleanableItem) -> str:
        prefix = "🔒 " if item.extra.get("requires_admin") else ""
        if not item.can_delete:
            return f"• {prefix}{item.name}"
        marker = "☑ " if item.selected else "☐ "
        return f"{marker}{prefix}{item.name}"

    def _on_tree_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return None
        item = self.item_by_iid.get(iid)
        if item is None:
            return None
        bbox = self.tree.bbox(iid, "#0")
        if not bbox:
            return None
        x = bbox[0]
        if event.x <= x + 24:
            self._toggle_item(iid)
            return "break"
        return None

    def _on_space(self, _event=None):
        selection = self.tree.selection()
        if selection and selection[0] in self.item_by_iid:
            self._toggle_item(selection[0])
        return "break"

    def _toggle_item(self, iid: str) -> None:
        item = self.item_by_iid.get(iid)
        if item is None:
            return
        if not item.can_delete:
            self.status_var.set(
                "Этот элемент показан только для информации — удалите его системными средствами."
            )
            return
        item.selected = not item.selected
        self.tree.item(iid, text=self._item_text(item))
        self._update_summary()
        if self._details_item is item:
            self._show_details(item)

    def _on_tree_select(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        item = self.item_by_iid.get(selection[0])
        if item is not None:
            self._show_details(item)

    def _on_tree_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        item = self.item_by_iid.get(iid)
        if item is None:
            return
        self.tree.selection_set(iid)
        menu = tk.Menu(
            self, tearoff=0, bg=theme.BACKGROUND_PANEL_COLOR_2,
            fg=theme.TEXT_COLOR_MAIN, activebackground=theme.ACCENT_COLOR,
            activeforeground=theme.BACKGROUND_COLOR, font=theme.FONT_UI,
        )
        menu.add_command(label="📂 Открыть в проводнике",
                         command=lambda: _reveal(item.path))
        menu.add_command(label="📋 Копировать путь",
                         command=lambda: self._copy_path(item.path))
        menu.add_separator()
        menu.add_command(
            label="☑ Выбрать" if not item.selected else "☐ Снять выбор",
            command=lambda: self._toggle_item(iid),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ==================== Подробности ====================

    def _show_placeholder_details(self) -> None:
        self._details_item = None
        self._details_open_btn.configure(state=tk.DISABLED)
        self._details_copy_btn.configure(state=tk.DISABLED)
        self.details.configure(state=tk.NORMAL)
        self.details.delete("1.0", tk.END)
        self.details.insert(
            tk.END,
            "Здесь появятся сведения о выбранном элементе:\n"
            "размер, уровень риска, описание и путь.\n\n"
            "Как это работает:\n"
            "• «Анализ» ищет системный мусор и остатки удалённых программ.\n"
            "• Ничего не выбирается автоматически — отметьте вручную\n"
            "  или нажмите «Выбрать безопасное».\n"
            "• Зелёные элементы безопасно удалять.\n"
            "• Жёлтые — проверьте содержимое перед удалением.\n"
            "• Красные — только для информации.\n"
            "• 🔒 — может потребоваться запуск от администратора.\n",
            "dim",
        )
        self.details.configure(state=tk.DISABLED)

    def _select_first_item(self) -> None:
        """Выделяет первый элемент после анализа, чтобы показать подробности."""
        for category_iid in self.tree.get_children():
            children = self.tree.get_children(category_iid)
            if not children:
                continue
            first = children[0]
            if first in self.item_by_iid:
                self.tree.selection_set(first)
                self.tree.focus(first)
                self.tree.see(first)
            return

    def _show_details(self, item: CleanableItem) -> None:
        self._details_item = item
        self._details_open_btn.configure(state=tk.NORMAL)
        self._details_copy_btn.configure(state=tk.NORMAL)

        self.details.configure(state=tk.NORMAL)
        self.details.delete("1.0", tk.END)

        self.details.insert(tk.END, item.name + "\n", "title")
        self.details.insert(
            tk.END,
            f"{item.risk.label.upper()}  ·  {_human(item.size)}\n",
            item.risk.value,
        )
        self.details.insert(tk.END, "\n")

        self.details.insert(tk.END, "Категория: ", "label")
        self.details.insert(tk.END, f"{item.category}\n")

        rule_name = item.extra.get("rule_name")
        if rule_name:
            self.details.insert(tk.END, "Правило: ", "label")
            self.details.insert(tk.END, f"{rule_name}\n")

        self.details.insert(tk.END, "Что удаляется: ", "label")
        self.details.insert(
            tk.END,
            "содержимое папки\n" if item.contents_only else "папка или файл\n",
        )
        if item.is_orphan:
            self.details.insert(
                tk.END, "Тип: остаток удалённой программы\n", "caution",
            )

        self.details.insert(tk.END, "\n" + item.description + "\n")

        if item.note:
            self.details.insert(tk.END, f"\nПримечание: {item.note}\n", "dim")
        if item.extra.get("requires_admin"):
            self.details.insert(
                tk.END, "\n🔒 Нужны права администратора.\n", "admin",
            )
        if not item.can_delete:
            self.details.insert(
                tk.END, "\nУдаление из программы недоступно.\n", "danger",
            )

        self.details.insert(tk.END, f"\n{item.risk.hint}\n", "hint")
        self.details.insert(tk.END, "\nПуть:\n", "label")
        self.details.insert(tk.END, f"{item.path}\n", "mono")

        self.details.configure(state=tk.DISABLED)

    def _details_open(self) -> None:
        if self._details_item is not None:
            _reveal(self._details_item.path)

    def _details_copy(self) -> None:
        if self._details_item is not None:
            self._copy_path(self._details_item.path)

    # ==================== Действия ====================

    def select_safe(self) -> None:
        for item in self.items:
            item.selected = item.can_delete and item.risk is Risk.SAFE
        self._populate()
        self._update_summary()

    def clear_selection(self) -> None:
        for item in self.items:
            item.selected = False
        self._populate()
        self._update_summary()

    def open_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        item = self.item_by_iid.get(selection[0])
        if item is not None:
            _reveal(item.path)

    def _copy_path(self, path: str) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(path)
            self.status_var.set(f"Скопировано: {path}")
        except tk.TclError:
            pass

    def delete_selected(self) -> None:
        if self.scanning:
            return
        selected = [item for item in self.items if item.selected and item.can_delete]
        if not selected:
            messagebox.showinfo(
                "Умная очистка",
                "Ничего не выбрано. Отметьте элементы галочками или нажмите "
                "«Безопасное».",
            )
            return

        total = sum(item.size for item in selected)
        safe_count = sum(1 for item in selected if item.risk is Risk.SAFE)
        caution_count = sum(1 for item in selected if item.risk is Risk.CAUTION)
        recycle = self.recycle_var.get()

        lines = [
            f"Элементов: {len(selected)} · всего {_human(total)}",
            f"Безопасных: {safe_count} · осторожных: {caution_count}",
            "",
        ]
        if caution_count:
            lines.append(
                "Среди выбранного есть элементы «Осторожно» — "
                "проверьте их перед удалением."
            )
        if recycle:
            lines.append("Удаление можно отменить из корзины.")
        else:
            lines.append(
                "ВНИМАНИЕ: удаление безвозвратное, отменить его нельзя."
            )

        if not messagebox.askyesno("Подтверждение удаления", "\n".join(lines)):
            return

        self._set_scanning(True, "Удаление…")

        def worker():
            outcome = delete_items(
                selected, use_recycle_bin=self.recycle_var.get(),
            )
            try:
                self.after(0, lambda: self._on_delete_done(outcome))
            except tk.TclError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _on_delete_done(self, outcome) -> None:
        self._set_scanning(False)
        lines = [
            f"Удалено элементов: {outcome.deleted}",
            f"Освобождено: {_human(outcome.freed)}",
        ]
        if outcome.skipped:
            lines.append(f"Пропущено: {outcome.skipped}")
        if outcome.failed:
            lines.append(f"Ошибок: {len(outcome.failed)}")
            for path, error in outcome.failed[:5]:
                lines.append(f"• {path}: {error}")
        messagebox.showinfo("Умная очистка", "\n".join(lines))
        self.start_scan()

    def export_report(self) -> None:
        if not self.items:
            messagebox.showinfo("Умная очистка", "Нет данных — сначала выполните анализ.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV файлы", "*.csv")],
            initialfile=f"cleanup_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as file:
                writer = csv.writer(file, delimiter=";")
                writer.writerow([
                    "Категория", "Имя", "Размер (байт)", "Размер",
                    "Риск", "Можно удалить", "Путь", "Описание",
                ])
                for item in self.items:
                    writer.writerow([
                        item.category, item.name, item.size, _human(item.size),
                        item.risk.label, "да" if item.can_delete else "нет",
                        item.path, item.description,
                    ])
            self.status_var.set(f"Отчёт сохранён: {path}")
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("Умная очистка", f"Не удалось сохранить отчёт: {error}")

    # ==================== Сводка ====================

    def _reset_cards(self) -> None:
        for card in (
            self.card_total, self.card_safe, self.card_selected, self.card_orphans,
        ):
            card.set("—", "")

    def _update_summary(self) -> None:
        if not self.items:
            if self.last_result is None:
                self._reset_cards()
            else:
                self.card_total.set("0 Б", "элементов нет")
                self.card_safe.set("0 Б", "можно удалить")
                self.card_selected.set("0 Б", "0 выбрано")
                self.card_orphans.set("0", "остатков программ")
            return

        total = sum(item.size for item in self.items)
        safe = sum(
            item.size for item in self.items
            if item.risk is Risk.SAFE and item.can_delete
        )
        selected = sum(item.size for item in self.items if item.selected)
        selected_count = sum(1 for item in self.items if item.selected)
        orphans = sum(1 for item in self.items if item.is_orphan)

        self.card_total.set(_human(total), f"{len(self.items)} элементов")
        self.card_safe.set(_human(safe), "можно удалить")
        self.card_selected.set(_human(selected), f"{selected_count} выбрано")
        self.card_orphans.set(str(orphans), "остатков программ")
