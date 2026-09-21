"""
Визуализатор места на дисках.

Управление:
    ЛКМ  — войти в папку/сектор
    ПКМ  — вернуться назад
    СКМ  — переключить вид (диаграмма <-> проводник)
    Esc  — выйти на уровень дисков

Вид "диаграмма":
    - жёсткий минимальный угловой размер сектора (MIN_ANGLE_DEG);
    - размер рисуется на каждом секторе:
        * крупные сектора — вдоль дуги;
        * узкие — вдоль радиуса;
        * совсем мелкие — снаружи у края;
    - подписи снаружи — единый блок: [D/F] имя · размер;
    - иконка D/F стоит вплотную к тексту;
    - проценты не отображаются;
    - подписи расталкиваются по вертикали (spider);
    - при наведении активируется вся группа, остальные тускнеют.

Вид "проводник":
    - компактный список: иконка D/F, имя, дорожка прогресса,
      размер справа (без процентов);
    - имя обрезается через clip_path по границам своей колонки —
      оно физически не может залезть на прогресс-бар;
    - строка подсвечивается при наведении, при клике — переход.

Окно открывается развёрнутым, корректно масштабируется при
изменении размера.
"""

import math
import os
import threading
import tkinter as tk

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.patheffects as pe
import matplotlib.patches as mpatches
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import psutil


# ============================================================
# Константы оформления
# ============================================================

BG_MAIN     = "#0f1420"
BG_PANEL    = "#1a2233"
BG_PANEL_2  = "#232d44"
BG_PANEL_3  = "#2d3854"
FG_TEXT     = "#e8f0ff"
FG_DIM      = "#8fa3c4"
FG_DIM_2    = "#5d6b85"
ACCENT      = "#4cc9f0"
ACCENT_2    = "#f72585"
ACCENT_3    = "#ffd60a"

PALETTES = [
    ["#ff6b6b", "#ffa94d", "#ffd43b", "#a9e34b", "#69db7c",
     "#38d9a9", "#4dabf7", "#748ffc", "#da77f2", "#f783ac"],
    ["#4dabf7", "#4cc9f0", "#3bc9db", "#38d9a9", "#69db7c",
     "#a9e34b", "#e9ecef", "#ffd43b", "#ffa94d", "#ff8787"],
    ["#748ffc", "#9775fa", "#da77f2", "#f783ac", "#ff8787",
     "#ffa94d", "#ffd43b", "#a9e34b", "#38d9a9", "#3bc9db"],
    ["#845ef7", "#b197fc", "#d0bfff", "#e599f7", "#f783ac",
     "#ffa8a8", "#ffc078", "#ffe066", "#c0eb75", "#8ce99a"],
    ["#5f3dc4", "#7048e8", "#9775fa", "#c0a0f0", "#e0b8f0",
     "#f0b8d0", "#f0c8b0", "#f0e0a0", "#c8e0a0", "#a0e0c0"],
]


# ============================================================
# Вспомогательные функции
# ============================================================

def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} EB"


def color_for(depth: int, index: int) -> str:
    palette = PALETTES[min(depth, len(PALETTES) - 1)]
    return palette[index % len(palette)]


def lighten(hex_color: str, amount: float = 0.35) -> str:
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    r = int(r + (255 - r) * amount)
    g = int(g + (255 - g) * amount)
    b = int(b + (255 - b) * amount)
    return f"#{r:02x}{g:02x}{b:02x}"


def get_dir_size(path: str, cache: dict) -> int:
    if path in cache:
        return cache[path]
    total = 0
    stack = [path]
    seen = set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    cache[path] = total
    return total


# ============================================================
# Основное окно
# ============================================================

class DiskVisualizer(tk.Tk):

    # Жёсткий минимальный угол сектора (в градусах).
    MIN_ANGLE_DEG = 2.2

    def __init__(self):
        super().__init__()
        self.title("Диск-Визуализатор")

        # --- Полноэкранный запуск с fallback ---
        try:
            self.state("zoomed")            # Windows
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)     # Linux
            except tk.TclError:
                self.attributes("-fullscreen", True) # macOS

        self.minsize(900, 640)
        self.configure(bg=BG_MAIN)

        # Состояние
        self.current_path = None
        self.current_items = []
        self.history = []
        self.view_mode = "pie"
        self.cache = {}
        self.hover_index = None
        self.anim_state = 0.0
        self._anim_job = None
        self._resize_job = None

        # Графические объекты
        self._wedges = []
        self._labels = []
        self._lines = []
        self._dots = []
        self._legend_items = {}
        self._explorer_rows = []
        self._hover_zones = []

        self._pie_radius = 1.0
        self._display_angles = []

        self._build_ui()
        self._load_disks_async()

        # Реакция на изменение размера окна — пере-рендер
        self.bind("<Configure>", self._on_configure)

    # ---------- Реакция на resize ----------
    def _on_configure(self, event):
        if event.widget is not self:
            return
        if self._resize_job is not None:
            try:
                self.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.after(150, self._on_resize_finish)

    def _on_resize_finish(self):
        self._resize_job = None
        w = max(self.winfo_width(), 400)
        h = max(self.winfo_height() - 52 - 28, 300)
        self.fig.set_size_inches(w / self.fig.dpi,
                                 h / self.fig.dpi,
                                 forward=False)
        self._render_view(animate=False)

    # ---------- Построение UI ----------
    def _build_ui(self):
        top = tk.Frame(self, bg=BG_PANEL, height=52)
        top.pack(fill=tk.X, side=tk.TOP)
        top.pack_propagate(False)

        hints = tk.Frame(top, bg=BG_PANEL)
        hints.pack(side=tk.LEFT, padx=16, pady=8)
        self._make_hint(hints, "ЛКМ", "войти", ACCENT).pack(side=tk.LEFT, padx=(0, 14))
        self._make_hint(hints, "ПКМ", "назад", ACCENT_2).pack(side=tk.LEFT, padx=(0, 14))
        self._make_hint(hints, "СКМ", "вид", ACCENT_3).pack(side=tk.LEFT, padx=(0, 14))
        self._make_hint(hints, "Esc", "к дискам", FG_DIM).pack(side=tk.LEFT)

        self.path_var = tk.StringVar(value="Загрузка дисков…")
        tk.Label(
            top, textvariable=self.path_var,
            bg=BG_PANEL, fg=ACCENT,
            font=("Consolas", 11, "bold"),
        ).pack(side=tk.RIGHT, padx=16, pady=8)

        self.fig = Figure(figsize=(10, 7), dpi=100, facecolor=BG_MAIN)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor(BG_MAIN)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.canvas.mpl_connect("button_press_event", self._on_click)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)

        self.bind("<Escape>", lambda e: self._go_home())
        self.canvas.get_tk_widget().bind("<Escape>", lambda e: self._go_home())

        status = tk.Frame(self, bg=BG_PANEL, height=28)
        status.pack(fill=tk.X, side=tk.BOTTOM)
        status.pack_propagate(False)

        self.status_var = tk.StringVar(value="Готово")
        tk.Label(
            status, textvariable=self.status_var,
            bg=BG_PANEL, fg=FG_DIM, font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=16)

        self.mode_var = tk.StringVar(value="● Диаграмма")
        tk.Label(
            status, textvariable=self.mode_var,
            bg=BG_PANEL, fg=ACCENT,
            font=("Segoe UI", 9, "bold"),
        ).pack(side=tk.RIGHT, padx=16)

    def _make_hint(self, parent, key, action, color):
        f = tk.Frame(parent, bg=BG_PANEL)
        tk.Label(
            f, text=key, bg=color, fg=BG_MAIN,
            font=("Segoe UI", 9, "bold"), padx=8, pady=2,
        ).pack(side=tk.LEFT)
        tk.Label(
            f, text=action, bg=BG_PANEL, fg=FG_TEXT, font=("Segoe UI", 10),
        ).pack(side=tk.LEFT, padx=(6, 0))
        return f

    # ---------- Загрузка дисков ----------
    def _load_disks_async(self):
        self.status_var.set("Сканирование дисков…")

        def worker():
            disks = []
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append((part.mountpoint, usage.used))
                except OSError:
                    continue
            self.after(0, lambda: self._show_disks(disks))

        threading.Thread(target=worker, daemon=True).start()

    def _show_disks(self, disks):
        if not disks:
            self.status_var.set("Диски не найдены.")
            return
        self.current_path = None
        self.history.clear()
        self.cache.clear()
        self.current_items = [(mount, size) for mount, size in disks]
        self.path_var.set("🖥  Мои диски")
        self.status_var.set(
            f"Найдено дисков: {len(disks)}   |   "
            f"Всего занято: {human_size(sum(s for _, s in disks))}"
        )
        self._render_view(animate=True)

    # ---------- Отрисовка ----------
    def _render_view(self, animate=False):
        self.ax.clear()
        self.ax.set_facecolor(BG_MAIN)
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        for spine in self.ax.spines.values():
            spine.set_visible(False)

        self._wedges = []
        self._labels = []
        self._lines = []
        self._dots = []
        self._legend_items = {}
        self._explorer_rows = []
        self._hover_zones = []
        self.hover_index = None
        self._pie_radius = 1.0
        self._display_angles = []

        if self.view_mode == "pie":
            self._render_pie()
        else:
            self._render_explorer()

        if animate:
            self._start_animation()
        else:
            self.canvas.draw_idle()

    def _start_animation(self, steps=14, delay=16):
        if self._anim_job is not None:
            try:
                self.after_cancel(self._anim_job)
            except Exception:
                pass
        self.anim_state = 0.0

        def tick():
            self.anim_state += 1.0 / steps
            if self.anim_state >= 1.0:
                self.anim_state = 1.0
                self._apply_animation()
                self._anim_job = None
                return
            self._apply_animation()
            self._anim_job = self.after(delay, tick)

        self._apply_animation()
        self._anim_job = self.after(delay, tick)

    def _apply_animation(self):
        t = self.anim_state
        eased = 1 - (1 - t) ** 3

        for i, wedge in enumerate(self._wedges):
            local = max(0.0, min(1.0, (eased - i * 0.03) / 0.7))
            theta1 = wedge._orig_theta1
            theta2 = wedge._orig_theta2
            mid = (theta1 + theta2) / 2
            half = (theta2 - theta1) / 2 * local
            wedge.set_theta1(mid - half)
            wedge.set_theta2(mid + half)
            wedge.set_alpha(local)

        for txt in self._labels:
            txt.set_alpha(eased)
        for ln in self._lines:
            ln.set_alpha(eased)
        for dot in self._dots:
            dot.set_alpha(eased)

        self.canvas.draw_idle()

    # ==========================================================
    # Пересчёт углов с жёстким минимумом
    # ==========================================================
    def _compute_display_angles(self, sizes):
        n = len(sizes)
        if n == 0:
            return []
        total = sum(sizes)
        if total <= 0:
            return [360.0 / n] * n

        min_angle = self.MIN_ANGLE_DEG
        if min_angle * n >= 360.0:
            return [360.0 / n] * n

        angles = [s / total * 360.0 for s in sizes]
        fixed = [False] * n

        for _ in range(12):
            used = sum(angles[i] for i in range(n) if fixed[i])
            free_sum = sum(sizes[i] for i in range(n) if not fixed[i])
            free_deg = 360.0 - used
            if free_sum <= 0 or free_deg <= 0:
                break
            changed = False
            for i in range(n):
                if fixed[i]:
                    continue
                share = sizes[i] / free_sum * free_deg
                if share < min_angle:
                    angles[i] = min_angle
                    fixed[i] = True
                    changed = True
                else:
                    angles[i] = share
            if not changed:
                break

        for _ in range(4):
            s_ang = sum(angles)
            if s_ang <= 0:
                break
            k = 360.0 / s_ang
            angles = [a * k for a in angles]
            deficit = 0.0
            for i in range(n):
                if angles[i] < min_angle - 1e-9:
                    deficit += min_angle - angles[i]
                    angles[i] = min_angle
            if deficit < 1e-9:
                break
            excess_idx = [i for i in range(n) if angles[i] > min_angle + 1e-9]
            excess_sum = sum(angles[i] - min_angle for i in excess_idx)
            if excess_sum <= 0:
                break
            for i in excess_idx:
                take = (angles[i] - min_angle) / excess_sum * deficit
                angles[i] -= take

        s_ang = sum(angles)
        if s_ang > 0 and abs(s_ang - 360.0) > 1e-6:
            k = 360.0 / s_ang
            angles = [a * k for a in angles]

        return angles

    # ==========================================================
    # Круговая диаграмма
    # ==========================================================
    def _render_pie(self):
        data = [(n, s) for n, s in self.current_items if s > 0]
        total = sum(s for _, s in data)

        if not data:
            self.ax.text(0.5, 0.5, "Пусто", ha="center", va="center",
                         color=FG_DIM, fontsize=16, transform=self.ax.transAxes)
            self.ax.axis("off")
            self.canvas.draw_idle()
            return

        depth = len(self.history)
        n = len(data)
        sizes = [s for _, s in data]
        colors = [color_for(depth, i) for i in range(n)]

        disp_angles = self._compute_display_angles(sizes)
        self._display_angles = disp_angles

        angles = []
        acc = 90.0
        for deg in disp_angles:
            theta1 = acc
            theta2 = acc - deg
            mid = math.radians((theta1 + theta2) / 2.0)
            angles.append((theta1, theta2, mid))
            acc -= deg

        # ---------- Радиусы ----------
        radius = 1.0
        self._pie_radius = radius

        radial_knee_r = radius + 0.06
        trunk_x = radius + 0.22
        text_x = radius + 0.32

        # ---------- Динамический шрифт легенды ----------
        if n <= 8:
            outside_fontsize = 9.0
            LABEL_H = 0.16
        elif n <= 14:
            outside_fontsize = 8.3
            LABEL_H = 0.14
        elif n <= 22:
            outside_fontsize = 7.6
            LABEL_H = 0.12
        elif n <= 32:
            outside_fontsize = 7.0
            LABEL_H = 0.10
        elif n <= 45:
            outside_fontsize = 6.4
            LABEL_H = 0.09
        else:
            outside_fontsize = 5.8
            LABEL_H = 0.08

        ICON_SIZE = 0.09
        ICON_GAP = 0.035

        # ---------- Записи ----------
        entries = []
        for i, (name, size) in enumerate(data):
            _t1, _t2, mid_rad = angles[i]
            cx, cy = math.cos(mid_rad), math.sin(mid_rad)
            name_str = name if len(name) <= 30 else name[:28] + "…"

            if cx > 0.05:
                side = "right"
                ha = "left"
            elif cx < -0.05:
                side = "left"
                ha = "right"
            else:
                side = "right" if cy >= 0 else "left"
                ha = "left" if side == "right" else "right"

            entries.append({
                "index": i,
                "color": colors[i],
                "mid_rad": mid_rad,
                "cx": cx, "cy": cy,
                "side": side,
                "ha": ha,
                "name": name,
                "size": size,
                "text": f"{name_str}  ·  {human_size(size)}",
                "box_h": LABEL_H,
                "y_ideal": cy * (radius + 0.02),
                "y_text": cy * (radius + 0.02),
                "span_deg": disp_angles[i],
            })

        # ---------- Расталкивание по вертикали ----------
        entries_sorted = sorted(entries, key=lambda e: -e["y_ideal"])
        available_h = 3.2
        if n > 1:
            min_gap = min(LABEL_H * 1.22, available_h / (n - 1))
        else:
            min_gap = LABEL_H

        for i in range(1, len(entries_sorted)):
            prev = entries_sorted[i - 1]
            cur = entries_sorted[i]
            min_y = prev["y_text"] - min_gap
            if cur["y_text"] > min_y:
                cur["y_text"] = min_y

        for i in range(len(entries_sorted) - 2, -1, -1):
            nxt = entries_sorted[i + 1]
            cur = entries_sorted[i]
            max_y = nxt["y_text"] + min_gap
            if cur["y_text"] < max_y:
                cur["y_text"] = max_y

        if entries_sorted:
            ideal_center = sum(e["y_ideal"] for e in entries_sorted) / len(entries_sorted)
            real_center = sum(e["y_text"] for e in entries_sorted) / len(entries_sorted)
            dy = ideal_center - real_center
            for e in entries_sorted:
                e["y_text"] += dy

        # ---------- Круг ----------
        wedges, _ = self.ax.pie(
            disp_angles,
            colors=colors,
            startangle=90,
            counterclock=False,
            radius=radius,
            wedgeprops=dict(edgecolor=BG_MAIN, linewidth=1.5),
        )
        for i, w in enumerate(wedges):
            w._orig_theta1 = w.theta1
            w._orig_theta2 = w.theta2
            self._wedges.append(w)
            if disp_angles[i] < 3.5:
                w.set_edgecolor("#ffffff")
                w.set_linewidth(1.0)

        # ---------- Размер внутри сектора ----------
        for i, wedge in enumerate(wedges):
            span = disp_angles[i]
            name, size = data[i]
            mid = math.radians((wedge.theta1 + wedge.theta2) / 2.0)
            cx, cy = math.cos(mid), math.sin(mid)

            size_str = human_size(size)

            text_angle = math.degrees(mid)
            while text_angle > 180:
                text_angle -= 360
            while text_angle <= -180:
                text_angle += 360
            if text_angle > 90:
                text_angle -= 180
            elif text_angle < -90:
                text_angle += 180

            drawn = False

            # --- Вариант A: вдоль дуги ---
            if span >= 6.0:
                for fontsize, r_pos in ((9.0, 0.72),
                                        (8.0, 0.72),
                                        (7.0, 0.70),
                                        (6.5, 0.68),
                                        (6.0, 0.66),
                                        (5.5, 0.64),
                                        (5.0, 0.62),
                                        (4.5, 0.60),
                                        (4.0, 0.58)):
                    text_len_axis = len(size_str) * (fontsize / 16.0)
                    r_center = radius * r_pos
                    half_arc_rad = (text_len_axis / 2) / max(r_center, 1e-6)
                    arc_deg = math.degrees(half_arc_rad) * 2.0
                    if arc_deg * 1.05 <= span:
                        txt = self.ax.text(
                            cx * r_center, cy * r_center,
                            size_str,
                            ha="center", va="center",
                            rotation=text_angle,
                            rotation_mode="anchor",
                            color="white",
                            fontsize=fontsize, fontweight="bold",
                            path_effects=[pe.withStroke(linewidth=2.4,
                                                        foreground="#000000")],
                            zorder=9,
                        )
                        self._labels.append(txt)
                        drawn = True
                        break

            # --- Вариант B: вдоль радиуса ---
            if not drawn:
                radial_angle = math.degrees(mid)
                while radial_angle > 90:
                    radial_angle -= 180
                while radial_angle <= -90:
                    radial_angle += 180

                for fontsize, r_pos in ((6.5, 0.78),
                                        (6.0, 0.78),
                                        (5.5, 0.76),
                                        (5.0, 0.74),
                                        (4.5, 0.72),
                                        (4.0, 0.70)):
                    text_len_r = len(size_str) * (fontsize / 110.0)
                    avail_r = radius * (1.0 - 0.30)
                    if text_len_r <= avail_r:
                        r_center = radius * r_pos
                        txt = self.ax.text(
                            cx * r_center, cy * r_center,
                            size_str,
                            ha="center", va="center",
                            rotation=radial_angle,
                            rotation_mode="anchor",
                            color="white",
                            fontsize=fontsize, fontweight="bold",
                            path_effects=[pe.withStroke(linewidth=2.0,
                                                        foreground="#000000")],
                            zorder=9,
                        )
                        self._labels.append(txt)
                        drawn = True
                        break

            # --- Вариант C: снаружи ---
            if not drawn:
                r_out = radius * 1.06
                txt = self.ax.text(
                    cx * r_out, cy * r_out,
                    size_str,
                    ha="center", va="center",
                    color="white",
                    fontsize=4.5, fontweight="bold",
                    path_effects=[pe.withStroke(linewidth=2.0,
                                                foreground="#000000")],
                    zorder=9,
                )
                self._labels.append(txt)

        # ---------- Внешняя легенда ----------
        for e in entries_sorted:
            cx, cy = e["cx"], e["cy"]
            color = e["color"]
            idx = e["index"]
            sign = 1.0 if e["side"] == "right" else -1.0
            is_dir = e["name"].endswith(os.sep)

            x_edge = cx * radius * 1.005
            y_edge = cy * radius * 1.005

            x_radial = cx * radial_knee_r
            y_radial = cy * radial_knee_r

            x_trunk = sign * trunk_x
            y_trunk = e["y_text"]

            anchor_x = sign * (text_x - 0.06)
            y_text = e["y_text"]

            line = self.ax.plot(
                [x_edge, x_radial, x_trunk, anchor_x],
                [y_edge, y_radial, y_trunk, y_text],
                color=color, linewidth=1.4, alpha=1.0,
                solid_capstyle="round", solid_joinstyle="round",
                zorder=4,
            )[0]
            self._lines.append(line)

            dot = mpatches.Circle((anchor_x, y_text), 0.010,
                                  color=color, zorder=6)
            self.ax.add_patch(dot)
            self._dots.append(dot)

            # Иконка D/F вплотную к тексту
            if e["side"] == "right":
                icon_x = text_x
                text_xx = text_x + ICON_SIZE + ICON_GAP
                text_ha = "left"
            else:
                icon_x = -text_x
                text_xx = -text_x - ICON_SIZE - ICON_GAP
                text_ha = "right"

            icon_color = ACCENT if is_dir else ACCENT_3
            icon_letter = "D" if is_dir else "F"

            icon_rect = mpatches.Rectangle(
                (icon_x - ICON_SIZE / 2, y_text - ICON_SIZE / 2),
                ICON_SIZE, ICON_SIZE,
                facecolor=icon_color, edgecolor="none",
                alpha=0.9, zorder=7,
            )
            self.ax.add_patch(icon_rect)
            icon_txt = self.ax.text(
                icon_x, y_text, icon_letter,
                ha="center", va="center",
                color=BG_MAIN, fontsize=6.5, fontweight="bold",
                zorder=8,
            )
            self._labels.append(icon_txt)

            txt = self.ax.text(
                text_xx, y_text, e["text"],
                ha=text_ha, va="center",
                color=color, fontsize=outside_fontsize, fontweight="bold",
                path_effects=[pe.withStroke(linewidth=3,
                                            foreground=BG_MAIN)],
                zorder=7,
            )
            self._labels.append(txt)

            if e["side"] == "right":
                zone_x0 = icon_x - ICON_SIZE / 2 - 0.02
                zone_x1 = text_xx + 3.0
            else:
                zone_x0 = text_xx - 3.0
                zone_x1 = icon_x + ICON_SIZE / 2 + 0.02

            zone_y0 = y_text - LABEL_H / 2
            zone_y1 = zone_y0 + LABEL_H

            highlight_rect = mpatches.Rectangle(
                (zone_x0, zone_y0),
                zone_x1 - zone_x0, LABEL_H,
                facecolor="none", edgecolor="none",
                zorder=3,
            )
            self.ax.add_patch(highlight_rect)

            self._hover_zones.append({
                "x0": zone_x0, "x1": zone_x1,
                "y0": zone_y0, "y1": zone_y1,
                "index": idx,
            })

            self._legend_items[idx] = {
                "text": txt,
                "line": line,
                "dot": dot,
                "icon_rect": icon_rect,
                "icon_text": icon_txt,
                "base_color": color,
                "zone": highlight_rect,
            }

        # ---------- Центр ----------
        centre_circle = mpatches.Circle((0, 0), radius * 0.30,
                                        color=BG_MAIN, zorder=10)
        self.ax.add_patch(centre_circle)
        self.ax.text(0, radius * 0.05, human_size(total),
                     ha="center", va="center",
                     color=FG_TEXT, fontsize=12, fontweight="bold",
                     zorder=11)
        self.ax.text(0, radius * -0.07, "всего",
                     ha="center", va="center",
                     color=FG_DIM, fontsize=9, zorder=11)

        # ---------- Границы осей ----------
        if entries_sorted:
            y_upper = max(e["y_text"] for e in entries_sorted)
            y_lower = min(e["y_text"] for e in entries_sorted)
        else:
            y_upper, y_lower = 0.0, 0.0

        y_span = max(y_upper - y_lower, 0.1)
        needed_half = max(y_span / 0.86 / 2.0, radius + 0.45)
        y_center = (y_upper + y_lower) / 2.0

        y_max = max(y_center + needed_half, radius + 0.55)
        y_min = min(y_center - needed_half, -(radius + 0.55))

        max_x = text_x + ICON_SIZE + ICON_GAP + 3.0
        x_bound = max(max_x, radius + 0.6)

        self.ax.set_xlim(-x_bound, x_bound)
        self.ax.set_ylim(y_min, y_max)
        self.ax.set_aspect("equal")
        self.ax.axis("off")

    # ==========================================================
    # Проводник
    # ==========================================================
    def _render_explorer(self):
        data = [(n, s) for n, s in self.current_items if s > 0]
        total = sum(s for _, s in data)
        if not data:
            self.ax.text(0.5, 0.5, "Пусто", ha="center", va="center",
                         color=FG_DIM, fontsize=16, transform=self.ax.transAxes)
            self.ax.axis("off")
            self.canvas.draw_idle()
            return

        data_sorted = sorted(data, key=lambda x: x[1], reverse=True)
        depth = len(self.history)
        n = len(data_sorted)

        # --- Ширины колонок в долях оси ---
        # x_name — начало колонки имени,
        # x_bar0 — начало прогресс-бара.
        # Между ними оставлен зазор 0.02 для запаса.
        x_icon      = 0.030
        x_name      = 0.065
        name_col_x0 = x_name
        name_col_x1 = 0.52          # правая граница колонки имени
        x_bar0      = 0.54          # прогресс-бар начинается правее
        x_bar1      = 0.92
        x_size      = 0.985

        top_y       = 0.965
        bottom_y    = 0.035

        max_rows = 60
        shown = min(n, max_rows)
        row_h = (top_y - bottom_y) / shown
        bar_h = min(row_h * 0.50, 0.024)

        # --- Прямоугольник-отсекатель для колонки имени ---
        # Всё, что выходит за него, будет физически обрезано.
        clip_rect = mpatches.Rectangle(
            (name_col_x0, 0.0),
            name_col_x1 - name_col_x0, 1.0,
            transform=self.ax.transAxes,
            facecolor="none", edgecolor="none",
        )
        self.ax.add_patch(clip_rect)

        for i, (name, size) in enumerate(data_sorted[:max_rows]):
            y = top_y - i * row_h
            frac = size / total if total > 0 else 0.0
            col = color_for(depth, i)
            is_dir = name.endswith(os.sep)

            if i % 2 == 0:
                self.ax.add_patch(mpatches.Rectangle(
                    (0.0, y - row_h / 2),
                    1.0, row_h,
                    facecolor=BG_PANEL_2, alpha=0.20,
                    edgecolor="none", zorder=1,
                    transform=self.ax.transAxes,
                ))

            hit_rect = mpatches.Rectangle(
                (0.0, y - row_h / 2),
                1.0, row_h,
                facecolor="none", edgecolor="none",
                zorder=2, transform=self.ax.transAxes,
            )
            self.ax.add_patch(hit_rect)
            self._explorer_rows.append({
                "rect": hit_rect,
                "y": y,
                "row_h": row_h,
                "index": i,
                "_active": False,
            })

            icon_size = min(row_h * 0.65, 0.022)
            icon_color = ACCENT if is_dir else ACCENT_3
            icon_letter = "D" if is_dir else "F"

            self.ax.add_patch(mpatches.FancyBboxPatch(
                (x_icon - icon_size / 2, y - icon_size / 2),
                icon_size, icon_size,
                boxstyle="round,pad=0,rounding_size=0.003",
                facecolor=icon_color, edgecolor="none",
                alpha=0.9, zorder=3,
                transform=self.ax.transAxes,
            ))
            self.ax.text(
                x_icon, y, icon_letter,
                ha="center", va="center",
                color=BG_MAIN, fontsize=6.5, fontweight="bold",
                transform=self.ax.transAxes, zorder=4,
            )

            # --- Имя: рисуем полностью, но обрезаем по колонке ---
            # Никаких ручных оценок ширины — Matplotlib сам обрежет
            # всё, что выйдет за правую границу clip_rect.
            txt_name = self.ax.text(
                x_name, y, name,
                ha="left", va="center",
                color=FG_TEXT, fontsize=9,
                transform=self.ax.transAxes,
                fontfamily="Consolas",
                zorder=4,
                clip_on=True,
            )
            # Назначаем clip_path — именно он физически отрежет
            # «хвост» имени, который вылез бы на прогресс-бар.
            txt_name.set_clip_path(clip_rect)

            self.ax.add_patch(mpatches.FancyBboxPatch(
                (x_bar0, y - bar_h / 2),
                x_bar1 - x_bar0, bar_h,
                boxstyle="round,pad=0,rounding_size=0.003",
                facecolor=BG_PANEL_3, edgecolor="none",
                alpha=0.45, zorder=2,
                transform=self.ax.transAxes,
            ))

            fill_w = (x_bar1 - x_bar0) * frac
            if fill_w > 0.0005:
                light_col = lighten(col, 0.30)
                self.ax.add_patch(mpatches.FancyBboxPatch(
                    (x_bar0, y - bar_h / 2),
                    fill_w, bar_h,
                    boxstyle="round,pad=0,rounding_size=0.003",
                    facecolor=col, edgecolor="none",
                    alpha=0.95, zorder=3,
                    transform=self.ax.transAxes,
                ))
                self.ax.add_patch(mpatches.Rectangle(
                    (x_bar0, y + bar_h * 0.05),
                    fill_w, bar_h * 0.30,
                    facecolor=light_col, edgecolor="none",
                    alpha=0.25, zorder=4,
                    transform=self.ax.transAxes,
                ))

            self.ax.text(
                x_size, y, human_size(size),
                ha="right", va="center",
                color=FG_TEXT, fontsize=9, fontweight="bold",
                transform=self.ax.transAxes,
                fontfamily="Consolas",
            )

        if n > max_rows:
            self.ax.text(
                0.5, bottom_y - row_h * 0.4,
                f"… и ещё {n - max_rows} элементов (не показаны)",
                ha="center", va="center",
                color=FG_DIM, fontsize=9, style="italic",
                transform=self.ax.transAxes,
            )

        self.ax.set_xlim(0, 1)
        self.ax.set_ylim(0, 1)
        self.ax.axis("off")

    # ---------- Клики ----------
    def _on_click(self, event):
        if event.button == 2:
            self.view_mode = "explorer" if self.view_mode == "pie" else "pie"
            self.mode_var.set(
                "● Проводник" if self.view_mode == "explorer" else "● Диаграмма"
            )
            self._render_view(animate=True)
            return

        if event.button == 3:
            self._go_back()
            return

        if event.button != 1:
            return
        if event.inaxes != self.ax:
            return

        if self.view_mode == "pie":
            idx = self._find_hover_zone(event.xdata, event.ydata)
            if idx is None:
                idx = self._find_pie_sector(event.xdata, event.ydata)
            if idx is None:
                return
            name, _ = self.current_items[idx]
        else:
            idx = self._find_explorer_row(event.ydata)
            if idx is None:
                return
            data_sorted = sorted(
                [(n, s) for n, s in self.current_items if s > 0],
                key=lambda x: x[1], reverse=True,
            )
            name, _ = data_sorted[idx]

        self._enter_item(name)

    def _find_pie_sector(self, x, y):
        if x is None or y is None:
            return None
        r = math.hypot(x, y)
        radius = self._pie_radius
        if r > radius * 1.005 or r < radius * 0.30:
            return None
        angle_deg = math.degrees(math.atan2(y, x))
        travelled = (90.0 - angle_deg) % 360.0

        disp = self._display_angles
        if not disp:
            return None
        acc = 0.0
        for i, deg in enumerate(disp):
            if travelled < acc + deg:
                return i
            acc += deg
        return len(disp) - 1

    def _find_explorer_row(self, y):
        if y is None or not self._explorer_rows:
            return None
        rows = self._explorer_rows
        lo, hi = 0, len(rows) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            row = rows[mid]
            dy = row["y"] - y
            if abs(dy) <= row["row_h"] / 2:
                return row["index"]
            if dy < 0:
                hi = mid - 1
            else:
                lo = mid + 1
        return None

    def _find_hover_zone(self, x, y):
        if x is None or y is None:
            return None
        for zone in self._hover_zones:
            if (zone["x0"] <= x <= zone["x1"] and
                    zone["y0"] <= y <= zone["y1"]):
                return zone["index"]
        return None

    # ---------- Hover ----------
    def _on_motion(self, event):
        if self._anim_job is not None:
            return

        if event.inaxes != self.ax:
            if self.hover_index is not None:
                self._apply_hover(None)
            self._set_cursor("")
            return

        if self.view_mode == "pie":
            idx = self._find_hover_zone(event.xdata, event.ydata)
            if idx is None:
                idx = self._find_pie_sector(event.xdata, event.ydata)
        else:
            idx = self._find_explorer_row(event.ydata)

        if idx == self.hover_index:
            return

        self._apply_hover(idx)
        self._set_cursor("hand2" if idx is not None else "")

    def _set_cursor(self, name):
        try:
            self.canvas.get_tk_widget().configure(cursor=name)
        except tk.TclError:
            pass

    def _apply_hover(self, idx):
        if idx == self.hover_index:
            return
        self.hover_index = idx

        if self.view_mode == "pie":
            for i, wedge in enumerate(self._wedges):
                if idx is None:
                    wedge.set_alpha(1.0)
                elif i == idx:
                    wedge.set_alpha(1.0)
                else:
                    wedge.set_alpha(0.25)

            for i, item in self._legend_items.items():
                if idx is None:
                    item["line"].set_linewidth(1.4)
                    item["line"].set_alpha(1.0)
                    item["dot"].set_alpha(1.0)
                    item["icon_rect"].set_alpha(0.9)
                    item["icon_text"].set_alpha(1.0)
                    item["text"].set_alpha(1.0)
                    item["text"].set_color(item["base_color"])
                    item["zone"].set_facecolor("none")
                    item["zone"].set_alpha(0.0)
                    item["zone"].set_edgecolor("none")
                    item["zone"].set_linewidth(0.0)
                elif i == idx:
                    item["line"].set_linewidth(3.2)
                    item["line"].set_alpha(1.0)
                    item["dot"].set_alpha(1.0)
                    item["icon_rect"].set_alpha(1.0)
                    item["icon_text"].set_alpha(1.0)
                    item["text"].set_alpha(1.0)
                    item["text"].set_color(FG_TEXT)
                    item["zone"].set_facecolor(item["base_color"])
                    item["zone"].set_alpha(0.35)
                    item["zone"].set_edgecolor(item["base_color"])
                    item["zone"].set_linewidth(1.4)
                else:
                    item["line"].set_linewidth(1.0)
                    item["line"].set_alpha(0.10)
                    item["dot"].set_alpha(0.10)
                    item["icon_rect"].set_alpha(0.15)
                    item["icon_text"].set_alpha(0.15)
                    item["text"].set_alpha(0.15)
                    item["text"].set_color(item["base_color"])
                    item["zone"].set_facecolor("none")
                    item["zone"].set_alpha(0.0)
                    item["zone"].set_edgecolor("none")
                    item["zone"].set_linewidth(0.0)

        elif self.view_mode == "explorer":
            for row in self._explorer_rows:
                new_state = (idx is not None and row["index"] == idx)
                old_state = row.get("_active", False)
                if new_state == old_state:
                    continue
                row["_active"] = new_state
                if new_state:
                    row["rect"].set_facecolor(ACCENT)
                    row["rect"].set_alpha(0.12)
                else:
                    row["rect"].set_facecolor("none")
                    row["rect"].set_alpha(0.0)

        self.canvas.draw_idle()

    # ---------- Навигация ----------
    def _enter_item(self, name):
        if self.current_path is None:
            target = name
        else:
            target = os.path.join(self.current_path, name.rstrip(os.sep))

        if not os.path.isdir(target):
            self.status_var.set(f"Не папка: {target}")
            return

        self.status_var.set(f"Сканирование {target}…")

        def worker():
            items = self._scan_directory(target)
            self.after(0, lambda: self._show_directory(target, items))

        threading.Thread(target=worker, daemon=True).start()

    def _scan_directory(self, path):
        results = []
        try:
            entries = list(os.scandir(path))
        except OSError:
            return results
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    size = get_dir_size(entry.path, self.cache)
                    results.append((entry.name + os.sep, size))
                else:
                    size = entry.stat(follow_symlinks=False).st_size
                    results.append((entry.name, size))
            except OSError:
                continue
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def _show_directory(self, path, items):
        self.history.append(self.current_path)
        self.current_path = path
        self.current_items = items
        self.path_var.set(f"📁  {path}")
        total = sum(s for _, s in items)
        self.status_var.set(
            f"Элементов: {len(items)}   |   Всего: {human_size(total)}"
        )
        self._render_view(animate=True)

    def _go_back(self):
        if not self.history:
            self.status_var.set("Это верхний уровень.")
            return
        prev = self.history.pop()
        if prev is None:
            self._load_disks_async()
            return

        self.status_var.set(f"Возврат в {prev}…")

        def worker():
            items = self._scan_directory(prev)
            self.after(0, lambda: self._show_directory_back(prev, items))

        threading.Thread(target=worker, daemon=True).start()

    def _show_directory_back(self, path, items):
        self.current_path = path
        self.current_items = items
        self.path_var.set(f"📁  {path}")
        total = sum(s for _, s in items)
        self.status_var.set(
            f"Элементов: {len(items)}   |   Всего: {human_size(total)}"
        )
        self._render_view(animate=True)

    def _go_home(self):
        if self.current_path is None:
            self.status_var.set("Это верхний уровень.")
            return
        self.history.clear()
        self._load_disks_async()


# ============================================================
# Точка входа
# ============================================================

def main():
    app = DiskVisualizer()
    app.mainloop()


if __name__ == "__main__":
    main()