import csv
import heapq
import math
import os
import platform
import subprocess
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, ttk

import matplotlib
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
import psutil
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

matplotlib.use("TkAgg")

# ---------- Цвета ----------

BACKGROUND_COLOR = "#0f1420"
BACKGROUND_PANEL_COLOR = "#1a2233"
BACKGROUND_PANEL_COLOR_2 = "#232d44"
BACKGROUND_PANEL_COLOR_3 = "#2d3854"
TEXT_COLOR_MAIN = "#e8f0ff"
TEXT_COLOR_DIM = "#8fa3c4"
TEXT_COLOR_DIM_2 = "#5d6b85"
ACCENT_COLOR = "#4cc9f0"
ACCENT_COLOR_2 = "#f72585"
ACCENT_COLOR_3 = "#ffd60a"

HOVER_BG_EXPLORER = "#2f3d5e"

# ---------- Константы ----------

MIN_ANGLE_DEGREES = 2.2
MAX_CHART_SECTORS = 60
EXPLORER_MAX_ROWS = 50
MOTION_DEBOUNCE_MS = 15
TOP_FILES_COUNT = 100

COLOR_PALETTES = [
    ["#ff6b6b", "#ffa94d", "#ffd43b", "#a9e34b", "#69db7c", "#38d9a9", "#4dabf7", "#748ffc", "#da77f2", "#f783ac"],
    ["#4dabf7", "#4cc9f0", "#3bc9db", "#38d9a9", "#69db7c", "#a9e34b", "#e9ecef", "#ffd43b", "#ffa94d", "#ff8787"],
    ["#748ffc", "#9775fa", "#da77f2", "#f783ac", "#ff8787", "#ffa94d", "#ffd43b", "#a9e34b", "#38d9a9", "#3bc9db"],
    ["#845ef7", "#b197fc", "#d0bfff", "#e599f7", "#f783ac", "#ffa8a8", "#ffc078", "#ffe066", "#c0eb75", "#8ce99a"],
    ["#5f3dc4", "#7048e8", "#9775fa", "#c0a0f0", "#e0b8f0", "#f0b8d0", "#f0c8b0", "#f0e0a0", "#c8e0a0", "#a0e0c0"],
]


# ---------- Утилиты ----------

def get_readable_size(num_bytes):
    units = ("Б", "КБ", "МБ", "ГБ", "ТБ", "ПБ")
    value = float(num_bytes)
    for unit in units:
        if abs(value) < 1024.0:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} ЭБ"


def get_color_for_level(depth, index):
    palette = COLOR_PALETTES[min(depth, len(COLOR_PALETTES) - 1)]
    return palette[index % len(palette)]


def lighten_color(hex_color, factor=0.35):
    color_no_hash = hex_color.lstrip("#")
    red = int(color_no_hash[0:2], 16)
    green = int(color_no_hash[2:4], 16)
    blue = int(color_no_hash[4:6], 16)
    red = int(red + (255 - red) * factor)
    green = int(green + (255 - green) * factor)
    blue = int(blue + (255 - blue) * factor)
    return f"#{red:02x}{green:02x}{blue:02x}"


def get_directory_size(path, cache):
    """Рекурсивно считает размер каталога с защитой от symlink-петель."""
    if path in cache:
        return cache[path]

    total_size = 0
    stack = [path]
    visited = {os.path.realpath(path)}

    while stack:
        current_item = stack.pop()
        try:
            with os.scandir(current_item) as iterator:
                for entry in iterator:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            real_path = os.path.realpath(entry.path)
                            if real_path not in visited:
                                visited.add(real_path)
                                stack.append(entry.path)
                        else:
                            total_size += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue

    cache[path] = total_size
    return total_size


def get_all_mount_points():
    """
    Возвращает список точек монтирования всех физических дисков,
    которые видны через psutil.disk_partitions.
    """
    mounts = []
    seen = set()
    for partition in psutil.disk_partitions(all=False):
        mount = partition.mountpoint
        # Пропускаем дубликаты и псевдо-ФС
        if mount in seen:
            continue
        if platform.system() == "Windows":
            # На Windows оставляем только реальные диски
            if "cdrom" in partition.opts or partition.fstype == "":
                continue
        else:
            # На Linux/macOS пропускаем системные псевдо-ФС
            if partition.fstype in ("", "tmpfs", "devtmpfs", "squashfs", "overlay", "proc", "sysfs"):
                continue
        seen.add(mount)
        mounts.append(mount)
    return mounts


def reveal_in_os(filepath):
    """Открывает файловый менеджер ОС и выделяет указанный файл или папку."""
    try:
        filepath = os.path.normpath(os.path.abspath(filepath))
    except Exception:
        return
    system = platform.system()
    try:
        if system == "Windows":
            if os.path.isdir(filepath):
                subprocess.Popen(f'explorer "{filepath}"', shell=True)
            else:
                subprocess.Popen(f'explorer /select,"{filepath}"', shell=True)
        elif system == "Darwin":
            if os.path.exists(filepath):
                subprocess.Popen(['open', '-R', filepath])
            else:
                parent = os.path.dirname(filepath)
                while parent and not os.path.exists(parent):
                    parent = os.path.dirname(parent)
                if parent:
                    subprocess.Popen(['open', parent])
        else:
            # Linux / BSD
            target_dir = filepath if os.path.isdir(filepath) else os.path.dirname(filepath)
            if not target_dir:
                target_dir = filepath
            if os.path.isfile(filepath):
                # Пробуем выделить файл через DBus (Nautilus, Dolphin, Nemo)
                try:
                    subprocess.Popen([
                        'dbus-send', '--session',
                        '--dest=org.freedesktop.FileManager1',
                        '--type=method_call',
                        '/org/freedesktop/FileManager1',
                        'org.freedesktop.FileManager1.ShowItems',
                        f'array:string:file://{filepath}', 'string:',
                    ])
                    return
                except (FileNotFoundError, OSError):
                    pass
            subprocess.Popen(['xdg-open', target_dir])
    except Exception as error:
        print(f"reveal_in_os error: {error}")


class DiskVisualizer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Disk Space Visualizer")

        try:
            self.state("zoomed")
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)
            except tk.TclError:
                self.attributes("-fullscreen", True)

        self.minsize(1000, 700)
        self.configure(bg=BACKGROUND_COLOR)

        # --- Состояние ---
        self.current_path = None
        self.current_items = []
        self.filtered_items = []
        self.history = []
        self.display_mode = "chart"
        self.sort_by_size = True
        self.size_cache = {}
        self.hover_index = None
        self.animation_state = 0.0
        self.animation_job = None
        self.resize_job = None
        self.motion_job = None
        self.scan_token = 0

        self.explorer_offset = 0
        self.explorer_max_rows = EXPLORER_MAX_ROWS

        # --- Объекты на холсте ---
        self.segments = []
        self.labels = []
        self.lines = []
        self.dots = []
        self.legend_items = {}
        self.explorer_rows = []
        self.hover_zones = []

        self.chart_radius = 1.0
        self.display_angles = []
        self.chart_sector_to_item = []

        # --- Blitting для быстрого hover ---
        self._blit_background = None
        self._hover_artist = None
        self._blit_ready = False
        self._explorer_top_y = 0.965
        self._explorer_row_height = 0.0
        self._explorer_start_idx = 0

        # --- Контекстное меню ---
        self.context_menu = tk.Menu(
            self, tearoff=0, bg=BACKGROUND_PANEL_COLOR_2, fg=TEXT_COLOR_MAIN,
            activebackground=ACCENT_COLOR, activeforeground=BACKGROUND_COLOR,
            relief=tk.FLAT, font=("Segoe UI", 9),
        )

        self.create_ui()
        self.load_disks_async()

        self.bind("<Configure>", self.on_resize)
        self.bind("<Escape>", lambda event: self.go_home())

    # ==================== Ресайз ====================

    def on_resize(self, event):
        if event.widget is not self:
            return
        if self.resize_job is not None:
            try:
                self.after_cancel(self.resize_job)
            except Exception:
                pass
        self.resize_job = self.after(150, self.finish_resize)

    def finish_resize(self):
        self.resize_job = None
        width = max(self.winfo_width(), 400)
        height = max(self.winfo_height() - 80, 300)
        self.figure.set_size_inches(width / self.figure.dpi, height / self.figure.dpi, forward=False)
        self.render_view(animation=False)

    # ==================== UI ====================

    def create_ui(self):
        top_panel = tk.Frame(self, bg=BACKGROUND_PANEL_COLOR, height=56)
        top_panel.pack(fill=tk.X, side=tk.TOP)
        top_panel.pack_propagate(False)

        tooltip_panel = tk.Frame(top_panel, bg=BACKGROUND_PANEL_COLOR)
        tooltip_panel.pack(side=tk.LEFT, padx=16, pady=8)

        self.create_tooltip(tooltip_panel, "ЛКМ", "войти", ACCENT_COLOR).pack(side=tk.LEFT, padx=(0, 12))
        self.create_tooltip(tooltip_panel, "ПКМ", "меню", ACCENT_COLOR_2).pack(side=tk.LEFT, padx=(0, 12))
        self.create_tooltip(tooltip_panel, "СКМ", "вид", ACCENT_COLOR_3).pack(side=tk.LEFT, padx=(0, 12))
        self.create_tooltip(tooltip_panel, "Esc", "домой", TEXT_COLOR_DIM).pack(side=tk.LEFT)

        self.path_var = tk.StringVar(value="Загрузка дисков…")
        tk.Label(
            top_panel, textvariable=self.path_var,
            bg=BACKGROUND_PANEL_COLOR, fg=ACCENT_COLOR,
            font=("Consolas", 11, "bold"),
        ).pack(side=tk.RIGHT, padx=16, pady=8)

        toolbar = tk.Frame(top_panel, bg=BACKGROUND_PANEL_COLOR)
        toolbar.pack(side=tk.RIGHT, padx=16, pady=8)

        self.search_entry = tk.Entry(
            toolbar, bg=BACKGROUND_PANEL_COLOR_2, fg=TEXT_COLOR_MAIN,
            insertbackground=TEXT_COLOR_MAIN, relief=tk.FLAT, width=20,
        )
        self.search_entry.pack(side=tk.LEFT, padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", self.on_search_change)

        tk.Button(
            toolbar, text="↕ Сортировка", bg=BACKGROUND_PANEL_COLOR_3, fg=TEXT_COLOR_MAIN,
            relief=tk.FLAT, cursor="hand2", command=self.toggle_sort,
        ).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(
            toolbar, text="🏆 Топ-100 по ПК", bg=BACKGROUND_PANEL_COLOR_3, fg=TEXT_COLOR_MAIN,
            relief=tk.FLAT, cursor="hand2", command=self.show_top_files_window,
        ).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(
            toolbar, text="📂 Проводник", bg=ACCENT_COLOR_2, fg=TEXT_COLOR_MAIN,
            font=("Segoe UI", 9, "bold"), relief=tk.FLAT, cursor="hand2",
            command=self.reveal_current_in_os,
        ).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(
            toolbar, text="💾 Экспорт CSV", bg=ACCENT_COLOR, fg=BACKGROUND_COLOR,
            font=("Segoe UI", 9, "bold"), relief=tk.FLAT, cursor="hand2",
            command=self.export_to_csv,
        ).pack(side=tk.LEFT)

        # --- Figure ---
        self.figure = Figure(figsize=(10, 7), dpi=100, facecolor=BACKGROUND_COLOR)
        self.axis = self.figure.add_subplot(111)
        self.axis.set_facecolor(BACKGROUND_COLOR)

        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.canvas.mpl_connect("button_press_event", self.on_click)
        self.canvas.mpl_connect("motion_notify_event", self.on_mouse_move)

        widget = self.canvas.get_tk_widget()
        widget.bind("<MouseWheel>", self.on_mouse_wheel)
        widget.bind("<Button-4>", self.on_mouse_wheel)
        widget.bind("<Button-5>", self.on_mouse_wheel)
        widget.bind("<Escape>", lambda event: self.go_home())

        # --- Нижняя панель ---
        bottom_panel = tk.Frame(self, bg=BACKGROUND_PANEL_COLOR, height=32)
        bottom_panel.pack(fill=tk.X, side=tk.BOTTOM)
        bottom_panel.pack_propagate(False)

        self.status_var = tk.StringVar(value="Готово")
        tk.Label(
            bottom_panel, textvariable=self.status_var,
            bg=BACKGROUND_PANEL_COLOR, fg=TEXT_COLOR_DIM, font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=16)

        self.mode_var = tk.StringVar(value="● Диаграмма")
        tk.Label(
            bottom_panel, textvariable=self.mode_var,
            bg=BACKGROUND_PANEL_COLOR, fg=ACCENT_COLOR, font=("Segoe UI", 9, "bold"),
        ).pack(side=tk.RIGHT, padx=16)

    def create_tooltip(self, parent, key, action, color):
        frame = tk.Frame(parent, bg=BACKGROUND_PANEL_COLOR)
        tk.Label(
            frame, text=key, bg=color, fg=BACKGROUND_COLOR,
            font=("Segoe UI", 9, "bold"), padx=8, pady=2,
        ).pack(side=tk.LEFT)
        tk.Label(
            frame, text=action, bg=BACKGROUND_PANEL_COLOR, fg=TEXT_COLOR_MAIN,
            font=("Segoe UI", 10),
        ).pack(side=tk.LEFT, padx=(6, 0))
        return frame

    # ==================== Загрузка дисков ====================

    def load_disks_async(self):
        self.status_var.set("Сканирование дисков…")
        self.scan_token += 1
        token = self.scan_token

        def worker():
            disks = []
            for partition in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    disks.append((partition.mountpoint, usage.used))
                except OSError:
                    continue
            self.after(0, lambda: self._on_disks_loaded(token, disks))

        threading.Thread(target=worker, daemon=True).start()

    def _on_disks_loaded(self, token, disks):
        if token != self.scan_token:
            return
        if not disks:
            self.status_var.set("Диски не найдены.")
            return

        self.current_path = None
        self.history.clear()
        self.size_cache.clear()
        self.current_items = list(disks)
        self.apply_filter()
        self.path_var.set("🖥  Мои диски")
        total_size = sum(size for _, size in disks)
        self.status_var.set(
            f"Найдено дисков: {len(disks)} | Всего занято: {get_readable_size(total_size)}"
        )
        self.render_view(animation=True)

    # ==================== Рендер ====================

    def render_view(self, animation=False):
        self.axis.clear()
        self.axis.set_facecolor(BACKGROUND_COLOR)
        self.axis.set_xticks([])
        self.axis.set_yticks([])
        for line in self.axis.spines.values():
            line.set_visible(False)

        # Сброс всех визуальных объектов
        self.segments = []
        self.labels = []
        self.lines = []
        self.dots = []
        self.legend_items = {}
        self.explorer_rows = []
        self.hover_zones = []
        self.hover_index = None
        self.chart_radius = 1.0
        self.display_angles = []
        self.chart_sector_to_item = []

        # Сброс blit-состояния
        self._blit_background = None
        self._hover_artist = None
        self._blit_ready = False

        if self.display_mode == "chart":
            self.render_chart()
        else:
            self.render_explorer()

        if animation:
            self.start_animation()
        else:
            self.canvas.draw_idle()
            if self.display_mode == "explorer":
                self.after(30, self._prepare_blit_background)

    def start_animation(self, steps=14, delay=16):
        if self.animation_job is not None:
            try:
                self.after_cancel(self.animation_job)
            except Exception:
                pass
        self.animation_state = 0.0

        def tick():
            self.animation_state += 1.0 / steps
            if self.animation_state >= 1.0:
                self.animation_state = 1.0
                self.apply_animation()
                self.animation_job = None
                if self.display_mode == "explorer":
                    self.after(30, self._prepare_blit_background)
                return
            self.apply_animation()
            self.animation_job = self.after(delay, tick)

        self.apply_animation()
        self.animation_job = self.after(delay, tick)

    def apply_animation(self):
        time_val = self.animation_state
        smoothing = 1 - (1 - time_val) ** 3

        for index, segment in enumerate(self.segments):
            local_val = max(0.0, min(1.0, (smoothing - index * 0.03) / 0.7))
            angle1 = segment._orig_theta1
            angle2 = segment._orig_theta2
            mid = (angle1 + angle2) / 2
            half = (angle2 - angle1) / 2 * local_val
            segment.set_theta1(mid - half)
            segment.set_theta2(mid + half)
            segment.set_alpha(local_val)

        for text in self.labels:
            text.set_alpha(smoothing)
        for line in self.lines:
            line.set_alpha(smoothing)
        for dot in self.dots:
            dot.set_alpha(smoothing)

        self.canvas.draw_idle()

    def calculate_display_angles(self, sizes):
        count = len(sizes)
        if count == 0:
            return []
        total_size = sum(sizes)
        if total_size <= 0:
            return [360.0 / count] * count

        min_angle = MIN_ANGLE_DEGREES
        if min_angle * count >= 360.0:
            return [360.0 / count] * count

        angles = [size / total_size * 360.0 for size in sizes]
        fixed = [False] * count

        for _ in range(12):
            used = sum(angles[i] for i in range(count) if fixed[i])
            free_sum = sum(sizes[i] for i in range(count) if not fixed[i])
            free_degrees = 360.0 - used
            if free_sum <= 0 or free_degrees <= 0:
                break
            changed = False
            for i in range(count):
                if fixed[i]:
                    continue
                share = sizes[i] / free_sum * free_degrees
                if share < min_angle:
                    angles[i] = min_angle
                    fixed[i] = True
                    changed = True
                else:
                    angles[i] = share
            if not changed:
                break

        for _ in range(4):
            angle_sum = sum(angles)
            if angle_sum <= 0:
                break
            coeff = 360.0 / angle_sum
            angles = [angle * coeff for angle in angles]
            deficit = 0.0
            for i in range(count):
                if angles[i] < min_angle - 1e-9:
                    deficit += min_angle - angles[i]
                    angles[i] = min_angle
            if deficit < 1e-9:
                break
            excess_indices = [i for i in range(count) if angles[i] > min_angle + 1e-9]
            excess_sum = sum(angles[i] - min_angle for i in excess_indices)
            if excess_sum <= 0:
                break
            for i in excess_indices:
                take = (angles[i] - min_angle) / excess_sum * deficit
                angles[i] -= take

        angle_sum = sum(angles)
        if angle_sum > 0 and abs(angle_sum - 360.0) > 1e-6:
            coeff = 360.0 / angle_sum
            angles = [angle * coeff for angle in angles]

        return angles

    def _build_chart_data(self):
        data_with_idx = [
            (name, size, i)
            for i, (name, size) in enumerate(self.filtered_items)
            if size > 0
        ]
        if not data_with_idx:
            return []

        if len(data_with_idx) <= MAX_CHART_SECTORS:
            return data_with_idx

        data_with_idx.sort(key=lambda x: x[1], reverse=True)
        head = data_with_idx[: MAX_CHART_SECTORS - 1]
        tail = data_with_idx[MAX_CHART_SECTORS - 1:]
        others_size = sum(item[1] for item in tail)
        if others_size > 0:
            head.append((f"… ещё {len(tail)} элементов", others_size, -1))
        return head

    def render_chart(self):
        chart_data = self._build_chart_data()
        if not chart_data:
            self.axis.text(
                0.5, 0.5, "Нет данных для отображения",
                ha="center", va="center", color=TEXT_COLOR_DIM,
                fontsize=16, transform=self.axis.transAxes,
            )
            self.axis.axis("off")
            self.canvas.draw_idle()
            return

        data = [(name, size) for name, size, _ in chart_data]
        self.chart_sector_to_item = [idx for _, _, idx in chart_data]

        total_size = sum(size for _, size in data)
        depth = len(self.history)
        count = len(data)
        sizes = [size for _, size in data]
        colors = [get_color_for_level(depth, i) for i in range(count)]

        display_angles = self.calculate_display_angles(sizes)
        self.display_angles = display_angles

        angles = []
        accumulator = 90.0
        for degree in display_angles:
            angle1 = accumulator
            angle2 = accumulator - degree
            mid_rad = math.radians((angle1 + angle2) / 2.0)
            angles.append((angle1, angle2, mid_rad))
            accumulator -= degree

        radius = 1.0
        self.chart_radius = radius

        bend_radius = radius + 0.06
        stem_coord = radius + 0.22
        text_coord = radius + 0.32

        if count <= 8:
            font_size_out, label_height = 9.0, 0.16
        elif count <= 14:
            font_size_out, label_height = 8.3, 0.14
        elif count <= 22:
            font_size_out, label_height = 7.6, 0.12
        elif count <= 32:
            font_size_out, label_height = 7.0, 0.10
        elif count <= 45:
            font_size_out, label_height = 6.4, 0.09
        else:
            font_size_out, label_height = 5.8, 0.08

        icon_size = 0.09
        icon_padding = 0.035

        records = []
        for i, (name, size) in enumerate(data):
            _angle1, _angle2, mid_rad = angles[i]
            center_x, center_y = math.cos(mid_rad), math.sin(mid_rad)
            name_str = name if len(name) <= 30 else name[:28] + "…"

            if center_x > 0.05:
                side, align = "right", "left"
            elif center_x < -0.05:
                side, align = "left", "right"
            else:
                side = "right" if center_y >= 0 else "left"
                align = "left" if side == "right" else "right"

            records.append({
                "index": i,
                "color": colors[i],
                "mid_rad": mid_rad,
                "center_x": center_x, "center_y": center_y,
                "side": side, "align": align,
                "name": name, "size": size,
                "text": f"{name_str}  ·  {get_readable_size(size)}",
                "height": label_height,
                "ideal_y": center_y * (radius + 0.02),
                "text_y": center_y * (radius + 0.02),
                "angle_span": display_angles[i],
            })

        sorted_records = sorted(records, key=lambda e: -e["ideal_y"])
        available_height = 3.2
        if count > 1:
            min_gap = min(label_height * 1.22, available_height / (count - 1))
        else:
            min_gap = label_height

        for i in range(1, len(sorted_records)):
            prev = sorted_records[i - 1]
            curr = sorted_records[i]
            min_y = prev["text_y"] - min_gap
            if curr["text_y"] > min_y:
                curr["text_y"] = min_y

        for i in range(len(sorted_records) - 2, -1, -1):
            next_rec = sorted_records[i + 1]
            curr = sorted_records[i]
            max_y = next_rec["text_y"] + min_gap
            if curr["text_y"] < max_y:
                curr["text_y"] = max_y

        if sorted_records:
            ideal_center = sum(e["ideal_y"] for e in sorted_records) / len(sorted_records)
            real_center = sum(e["text_y"] for e in sorted_records) / len(sorted_records)
            offset_y = ideal_center - real_center
            for e in sorted_records:
                e["text_y"] += offset_y

        # --- Рисуем сектора ---
        fig_segments, _ = self.axis.pie(
            display_angles,
            colors=colors,
            startangle=90,
            counterclock=False,
            radius=radius,
            wedgeprops=dict(edgecolor=BACKGROUND_COLOR, linewidth=1.5),
        )
        for i, segment in enumerate(fig_segments):
            segment._orig_theta1 = segment.theta1
            segment._orig_theta2 = segment.theta2
            self.segments.append(segment)
            if display_angles[i] < 3.5:
                segment.set_edgecolor("#ffffff")
                segment.set_linewidth(1.0)

        # --- Подписи размеров внутри секторов ---
        for i, segment in enumerate(fig_segments):
            span = display_angles[i]
            name, size = data[i]
            mid_rad = math.radians((segment.theta1 + segment.theta2) / 2.0)
            center_x, center_y = math.cos(mid_rad), math.sin(mid_rad)
            size_str = get_readable_size(size)

            text_angle = math.degrees(mid_rad)
            while text_angle > 180:
                text_angle -= 360
            while text_angle <= -180:
                text_angle += 360
            if text_angle > 90:
                text_angle -= 180
            elif text_angle < -90:
                text_angle += 180

            drawn = False

            if span >= 6.0:
                for font_size, pos_radius in (
                    (9.0, 0.72), (8.0, 0.72), (7.0, 0.70), (6.5, 0.68),
                    (6.0, 0.66), (5.5, 0.64), (5.0, 0.62), (4.5, 0.60), (4.0, 0.58),
                ):
                    text_len = len(size_str) * (font_size / 16.0)
                    center_radius = radius * pos_radius
                    half_arc = (text_len / 2) / max(center_radius, 1e-6)
                    arc_angle = math.degrees(half_arc) * 2.0
                    if arc_angle * 1.05 <= span:
                        text = self.axis.text(
                            center_x * center_radius, center_y * center_radius,
                            size_str, ha="center", va="center",
                            rotation=text_angle, rotation_mode="anchor",
                            color="white", fontsize=font_size, fontweight="bold",
                            path_effects=[pe.withStroke(linewidth=2.4, foreground="#000000")],
                            zorder=9,
                        )
                        self.labels.append(text)
                        drawn = True
                        break

            if not drawn:
                radial_angle = math.degrees(mid_rad)
                while radial_angle > 90:
                    radial_angle -= 180
                while radial_angle <= -90:
                    radial_angle += 180

                for font_size, pos_radius in (
                    (6.5, 0.78), (6.0, 0.78), (5.5, 0.76),
                    (5.0, 0.74), (4.5, 0.72), (4.0, 0.70),
                ):
                    radius_len = len(size_str) * (font_size / 110.0)
                    available_radius = radius * (1.0 - 0.30)
                    if radius_len <= available_radius:
                        center_radius = radius * pos_radius
                        text = self.axis.text(
                            center_x * center_radius, center_y * center_radius,
                            size_str, ha="center", va="center",
                            rotation=radial_angle, rotation_mode="anchor",
                            color="white", fontsize=font_size, fontweight="bold",
                            path_effects=[pe.withStroke(linewidth=2.0, foreground="#000000")],
                            zorder=9,
                        )
                        self.labels.append(text)
                        drawn = True
                        break

            if not drawn:
                outer_radius = radius * 1.06
                text = self.axis.text(
                    center_x * outer_radius, center_y * outer_radius,
                    size_str, ha="center", va="center",
                    color="white", fontsize=4.5, fontweight="bold",
                    path_effects=[pe.withStroke(linewidth=2.0, foreground="#000000")],
                    zorder=9,
                )
                self.labels.append(text)

        # --- Выноски ---
        for e in sorted_records:
            center_x, center_y = e["center_x"], e["center_y"]
            color = e["color"]
            index = e["index"]
            sign = 1.0 if e["side"] == "right" else -1.0
            is_dir = e["name"].endswith(os.sep)

            x_edge = center_x * radius * 1.005
            y_edge = center_y * radius * 1.005
            x_radial = center_x * bend_radius
            y_radial = center_y * bend_radius
            x_stem = sign * stem_coord
            y_stem = e["text_y"]
            anchor_x = sign * (text_coord - 0.06)
            y_text = e["text_y"]

            line = self.axis.plot(
                [x_edge, x_radial, x_stem, anchor_x],
                [y_edge, y_radial, y_stem, y_text],
                color=color, linewidth=1.4, alpha=1.0,
                solid_capstyle="round", solid_joinstyle="round", zorder=4,
            )[0]
            self.lines.append(line)

            dot = mpatches.Circle((anchor_x, y_text), 0.010, color=color, zorder=6)
            self.axis.add_patch(dot)
            self.dots.append(dot)

            if e["side"] == "right":
                icon_x = text_coord
                text_x = text_coord + icon_size + icon_padding
                text_align = "left"
            else:
                icon_x = -text_coord
                text_x = -text_coord - icon_size - icon_padding
                text_align = "right"

            icon_color = ACCENT_COLOR if is_dir else ACCENT_COLOR_3
            icon_letter = "D" if is_dir else "F"

            icon_rect = mpatches.Rectangle(
                (icon_x - icon_size / 2, y_text - icon_size / 2),
                icon_size, icon_size,
                facecolor=icon_color, edgecolor="none", alpha=0.9, zorder=7,
            )
            self.axis.add_patch(icon_rect)
            icon_text = self.axis.text(
                icon_x, y_text, icon_letter, ha="center", va="center",
                color=BACKGROUND_COLOR, fontsize=6.5, fontweight="bold", zorder=8,
            )
            self.labels.append(icon_text)

            label_text = self.axis.text(
                text_x, y_text, e["text"], ha=text_align, va="center",
                color=color, fontsize=font_size_out, fontweight="bold",
                path_effects=[pe.withStroke(linewidth=3, foreground=BACKGROUND_COLOR)],
                zorder=7,
            )
            self.labels.append(label_text)

            if e["side"] == "right":
                zone_x0 = icon_x - icon_size / 2 - 0.02
                zone_x1 = text_x + 3.0
            else:
                zone_x0 = text_x - 3.0
                zone_x1 = icon_x + icon_size / 2 + 0.02

            zone_y0 = y_text - e["height"] / 2
            zone_y1 = zone_y0 + e["height"]

            highlight_rect = mpatches.Rectangle(
                (zone_x0, zone_y0), zone_x1 - zone_x0, e["height"],
                facecolor="none", edgecolor="none", zorder=3,
            )
            self.axis.add_patch(highlight_rect)

            original_item_index = self.chart_sector_to_item[index]

            self.hover_zones.append({
                "x0": zone_x0, "x1": zone_x1, "y0": zone_y0, "y1": zone_y1,
                "index": original_item_index,
            })

            self.legend_items[original_item_index] = {
                "text": label_text, "line": line, "dot": dot,
                "icon_rect": icon_rect, "icon_text": icon_text,
                "base_color": color, "zone": highlight_rect,
                "segment_index": index,
            }

        # --- Центр ---
        center_circle = mpatches.Circle((0, 0), radius * 0.30, color=BACKGROUND_COLOR, zorder=10)
        self.axis.add_patch(center_circle)
        self.axis.text(
            0, radius * 0.05, get_readable_size(total_size),
            ha="center", va="center", color=TEXT_COLOR_MAIN,
            fontsize=12, fontweight="bold", zorder=11,
        )
        self.axis.text(
            0, radius * -0.07, "всего", ha="center", va="center",
            color=TEXT_COLOR_DIM, fontsize=9, zorder=11,
        )

        # --- Границы ---
        if sorted_records:
            y_top = max(e["text_y"] for e in sorted_records)
            y_bottom = min(e["text_y"] for e in sorted_records)
        else:
            y_top, y_bottom = 0.0, 0.0

        y_span = max(y_top - y_bottom, 0.1)
        required_half = max(y_span / 0.86 / 2.0, radius + 0.45)
        y_center = (y_top + y_bottom) / 2.0

        y_max = max(y_center + required_half, radius + 0.55)
        y_min = min(y_center - required_half, -(radius + 0.55))

        max_x = text_coord + icon_size + icon_padding + 3.0
        x_bound = max(max_x, radius + 0.6)

        self.axis.set_xlim(-x_bound, x_bound)
        self.axis.set_ylim(y_min, y_max)
        self.axis.set_aspect("equal")
        self.axis.axis("off")

    def render_explorer(self):
        data = self._sorted_explorer_data()
        total_size = sum(size for _, size in data)

        if not data:
            self.axis.text(
                0.5, 0.5, "Нет данных для отображения",
                ha="center", va="center", color=TEXT_COLOR_DIM,
                fontsize=16, transform=self.axis.transAxes,
            )
            self.axis.axis("off")
            self.canvas.draw_idle()
            return

        depth = len(self.history)
        count = len(data)

        x_icon = 0.030
        x_name = 0.065
        name_col_x0 = x_name
        name_col_x1 = 0.45
        x_bar0 = 0.47
        x_bar1 = 0.85
        x_size = 0.985

        top_y = 0.965
        bottom_y = 0.035

        row_height = (top_y - bottom_y) / self.explorer_max_rows
        bar_height = max(0.006, min(row_height * 0.50, 0.024))

        self._explorer_top_y = top_y
        self._explorer_row_height = row_height
        self._explorer_start_idx = self.explorer_offset

        clip_rect = mpatches.Rectangle(
            (name_col_x0, 0.0), name_col_x1 - name_col_x0, 1.0,
            transform=self.axis.transAxes, facecolor="none", edgecolor="none",
        )
        self.axis.add_patch(clip_rect)

        start_idx = self.explorer_offset
        end_idx = min(start_idx + self.explorer_max_rows, count)
        visible_data = data[start_idx:end_idx]

        name_to_filtered = {name: i for i, (name, _) in enumerate(self.filtered_items)}

        for i, (name, size) in enumerate(visible_data):
            item_index = name_to_filtered.get(name, None)

            y = top_y - i * row_height
            share = size / total_size if total_size > 0 else 0.0
            color = get_color_for_level(depth, i)
            is_dir = name.endswith(os.sep)

            if i % 2 == 0:
                self.axis.add_patch(mpatches.Rectangle(
                    (0.0, y - row_height / 2), 1.0, row_height,
                    facecolor=BACKGROUND_PANEL_COLOR_2, alpha=0.20,
                    edgecolor="none", zorder=1, transform=self.axis.transAxes,
                ))

            highlight_rect = mpatches.Rectangle(
                (0.0, y - row_height / 2), 1.0, row_height,
                facecolor=HOVER_BG_EXPLORER, alpha=0.0,
                edgecolor="none", zorder=2, transform=self.axis.transAxes,
            )
            self.axis.add_patch(highlight_rect)

            hit_rect = mpatches.Rectangle(
                (0.0, y - row_height / 2), 1.0, row_height,
                facecolor="none", edgecolor="none", zorder=3,
                transform=self.axis.transAxes,
            )
            self.axis.add_patch(hit_rect)

            self.explorer_rows.append({
                "rect": hit_rect,
                "highlight": highlight_rect,
                "y": y,
                "row_h": row_height,
                "item_index": item_index,
                "_active": False,
            })

            icon_size = min(row_height * 0.65, 0.022)
            icon_color = ACCENT_COLOR if is_dir else ACCENT_COLOR_3
            icon_letter = "D" if is_dir else "F"

            self.axis.add_patch(mpatches.FancyBboxPatch(
                (x_icon - icon_size / 2, y - icon_size / 2), icon_size, icon_size,
                boxstyle="round,pad=0,rounding_size=0.003",
                facecolor=icon_color, edgecolor="none",
                alpha=0.9, zorder=4, transform=self.axis.transAxes,
            ))
            self.axis.text(
                x_icon, y, icon_letter, ha="center", va="center",
                color=BACKGROUND_COLOR, fontsize=6.5, fontweight="bold",
                transform=self.axis.transAxes, zorder=5,
            )

            name_text = self.axis.text(
                x_name, y, name, ha="left", va="center",
                color=TEXT_COLOR_MAIN, fontsize=9, transform=self.axis.transAxes,
                fontfamily="Consolas", zorder=5, clip_on=True,
            )
            name_text.set_clip_path(clip_rect)

            self.axis.add_patch(mpatches.FancyBboxPatch(
                (x_bar0, y - bar_height / 2), x_bar1 - x_bar0, bar_height,
                boxstyle="round,pad=0,rounding_size=0.003",
                facecolor=BACKGROUND_PANEL_COLOR_3, edgecolor="none",
                alpha=0.45, zorder=2, transform=self.axis.transAxes,
            ))

            fill_width = (x_bar1 - x_bar0) * share
            if fill_width > 0.0005:
                light_color = lighten_color(color, 0.30)
                self.axis.add_patch(mpatches.FancyBboxPatch(
                    (x_bar0, y - bar_height / 2), fill_width, bar_height,
                    boxstyle="round,pad=0,rounding_size=0.003",
                    facecolor=color, edgecolor="none",
                    alpha=0.95, zorder=3, transform=self.axis.transAxes,
                ))
                self.axis.add_patch(mpatches.Rectangle(
                    (x_bar0, y + bar_height * 0.05), fill_width, bar_height * 0.30,
                    facecolor=light_color, edgecolor="none", alpha=0.25,
                    zorder=4, transform=self.axis.transAxes,
                ))

            self.axis.text(
                x_size, y, get_readable_size(size),
                ha="right", va="center", color=TEXT_COLOR_MAIN,
                fontsize=9, fontweight="bold",
                transform=self.axis.transAxes, fontfamily="Consolas",
            )

        if count > self.explorer_max_rows:
            self.axis.text(
                0.5, bottom_y - row_height * 0.4,
                f"… и ещё {count - self.explorer_max_rows} элементов (колесо мыши для прокрутки)",
                ha="center", va="center", color=TEXT_COLOR_DIM,
                fontsize=9, style="italic", transform=self.axis.transAxes,
            )

        self.axis.set_xlim(0, 1)
        self.axis.set_ylim(0, 1)
        self.axis.axis("off")

    # ==================== Вспомогательные ====================

    def _sorted_explorer_data(self):
        data = [(n, s) for n, s in self.filtered_items if s > 0]
        if self.sort_by_size:
            return sorted(data, key=lambda x: x[1], reverse=True)
        return sorted(data, key=lambda x: x[0].lower())

    # ==================== Blitting ====================

    def _prepare_blit_background(self):
        if self.display_mode != "explorer":
            self._blit_ready = False
            return
        try:
            self.canvas.draw()
            self._blit_background = self.canvas.copy_from_bbox(self.figure.bbox)
            self._blit_ready = True
        except Exception:
            self._blit_ready = False

    def _blit_hover_rect(self, row):
        if not self._blit_ready or self._blit_background is None:
            return False
        try:
            self.canvas.restore_region(self._blit_background)

            if self._hover_artist is not None:
                try:
                    self._hover_artist.set_alpha(0.0)
                except Exception:
                    pass
                self._hover_artist = None

            if row is not None:
                highlight = row["highlight"]
                highlight.set_alpha(0.85)
                self.axis.draw_artist(highlight)
                self._hover_artist = highlight

            self.canvas.blit(self.figure.bbox)
            return True
        except Exception:
            self._blit_ready = False
            return False

    # ==================== Обработка событий ====================

    def on_click(self, event):
        if event.button == 2:
            self.display_mode = "explorer" if self.display_mode == "chart" else "chart"
            self.mode_var.set("● Проводник" if self.display_mode == "explorer" else "● Диаграмма")
            self.explorer_offset = 0
            self.hover_index = None
            self.render_view(animation=True)
            return

        if event.button == 3:
            self.show_context_menu(event)
            return

        if event.button != 1:
            return
        if event.inaxes != self.axis:
            return

        if self.display_mode == "chart":
            index = self.find_hover_zone(event.xdata, event.ydata)
            if index is None:
                index = self.find_chart_sector(event.xdata, event.ydata)
            if index is None:
                return
            name, _ = self.filtered_items[index]
        else:
            index = self.find_explorer_row(event.ydata)
            if index is None:
                return
            name, _ = self.filtered_items[index]

        self.navigate_to_item(name)

    def show_context_menu(self, event):
        self.context_menu.delete(0, tk.END)

        index = None
        if self.display_mode == "chart":
            index = self.find_hover_zone(event.xdata, event.ydata)
            if index is None:
                index = self.find_chart_sector(event.xdata, event.ydata)
        else:
            index = self.find_explorer_row(event.ydata)

        if index is not None and 0 <= index < len(self.filtered_items):
            item_name, _ = self.filtered_items[index]
            is_dir = item_name.endswith(os.sep)
            display_name = item_name.rstrip(os.sep)

            self.context_menu.add_command(
                label=f"📄 {display_name[:40]}", state=tk.DISABLED,
            )
            self.context_menu.add_separator()

            if is_dir:
                self.context_menu.add_command(
                    label="📂 Открыть каталог",
                    command=lambda n=item_name: self.navigate_to_item(n),
                )

            if self.current_path is None:
                full_path = item_name.rstrip(os.sep)
            else:
                full_path = os.path.join(self.current_path, item_name.rstrip(os.sep))

            self.context_menu.add_command(
                label="📂 Показать в проводнике",
                command=lambda p=full_path: reveal_in_os(p),
            )
            self.context_menu.add_command(
                label="📋 Копировать путь",
                command=lambda p=full_path: self.clipboard_set(p),
            )
            self.context_menu.add_separator()

        self.context_menu.add_command(label="⬅ Назад", command=self.go_back)
        self.context_menu.add_command(label="🏠 Домой", command=self.go_home)

        x_root = self.winfo_pointerx()
        y_root = self.winfo_pointery()

        try:
            self.context_menu.tk_popup(x_root, y_root)
        finally:
            self.context_menu.grab_release()

    def clipboard_set(self, text):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()
            self.status_var.set(f"Скопировано: {text}")
        except tk.TclError as error:
            self.status_var.set(f"Не удалось скопировать: {error}")

    def find_chart_sector(self, x, y):
        if x is None or y is None:
            return None
        radius = math.hypot(x, y)
        if radius > self.chart_radius * 1.005 or radius < self.chart_radius * 0.30:
            return None
        angle_deg = math.degrees(math.atan2(y, x))
        passed = (90.0 - angle_deg) % 360.0

        if not self.display_angles:
            return None
        accumulator = 0.0
        for i, degree in enumerate(self.display_angles):
            if passed < accumulator + degree:
                if 0 <= i < len(self.chart_sector_to_item):
                    return self.chart_sector_to_item[i]
                return None
            accumulator += degree
        if self.chart_sector_to_item:
            return self.chart_sector_to_item[-1]
        return None

    def find_explorer_row(self, y):
        if y is None or not self.explorer_rows:
            return None
        if self._explorer_row_height <= 0:
            return None

        i_float = (self._explorer_top_y - y) / self._explorer_row_height
        i = int(round(i_float))

        if i < 0 or i >= len(self.explorer_rows):
            return None

        row = self.explorer_rows[i]
        if abs(row["y"] - y) > row["row_h"] / 2 + 1e-9:
            return None
        return row["item_index"]

    def find_hover_zone(self, x, y):
        if x is None or y is None:
            return None
        for zone in self.hover_zones:
            if zone["x0"] <= x <= zone["x1"] and zone["y0"] <= y <= zone["y1"]:
                return zone["index"]
        return None

    def on_mouse_move(self, event):
        if self.motion_job is not None:
            return
        self.motion_job = self.after(MOTION_DEBOUNCE_MS, lambda: self._process_motion(event))

    def _process_motion(self, event):
        self.motion_job = None

        if self.animation_job is not None:
            return

        if event.inaxes != self.axis:
            if self.hover_index is not None:
                self.hover_index = None
                if self.display_mode == "explorer":
                    self._apply_hover_explorer(None)
                else:
                    self._apply_hover_chart(None)
            self.set_cursor("")
            return

        if self.display_mode == "explorer":
            index = self.find_explorer_row(event.ydata)
            if index != self.hover_index:
                self.hover_index = index
                self._apply_hover_explorer(index)
            self.set_cursor("hand2" if index is not None else "")
            return

        index = self.find_hover_zone(event.xdata, event.ydata)
        if index is None:
            index = self.find_chart_sector(event.xdata, event.ydata)

        if index == self.hover_index:
            return

        self.hover_index = index
        self._apply_hover_chart(index)
        self.set_cursor("hand2" if index is not None else "")

    def on_mouse_wheel(self, event):
        if self.display_mode != "explorer":
            return

        data = self._sorted_explorer_data()
        max_possible_offset = max(0, len(data) - self.explorer_max_rows)

        if max_possible_offset <= 0:
            return

        if hasattr(event, "delta") and event.delta != 0:
            direction = -1 if event.delta > 0 else 1
        elif getattr(event, "num", None) == 4:
            direction = -1
        elif getattr(event, "num", None) == 5:
            direction = 1
        else:
            return

        new_offset = self.explorer_offset + direction
        new_offset = max(0, min(new_offset, max_possible_offset))

        if new_offset == self.explorer_offset:
            return

        self.explorer_offset = new_offset
        self.hover_index = None
        self.render_view(animation=False)

    def set_cursor(self, name):
        try:
            self.canvas.get_tk_widget().configure(cursor=name)
        except tk.TclError:
            pass

    def _apply_hover_explorer(self, index):
        if self._blit_ready:
            target_row = None
            if index is not None:
                for row in self.explorer_rows:
                    if row["item_index"] == index:
                        target_row = row
                        break

            if self._hover_artist is not None:
                for row in self.explorer_rows:
                    if row["highlight"] is self._hover_artist:
                        row["_active"] = False
                        break

            if self._blit_hover_rect(target_row):
                if target_row is not None:
                    target_row["_active"] = True
                return

        # Fallback
        changed = False
        for row in self.explorer_rows:
            if index is None:
                if row["_active"]:
                    row["highlight"].set_alpha(0.0)
                    row["_active"] = False
                    changed = True
            elif row["item_index"] == index:
                if not row["_active"]:
                    row["highlight"].set_alpha(0.85)
                    row["_active"] = True
                    changed = True
            else:
                if row["_active"]:
                    row["highlight"].set_alpha(0.0)
                    row["_active"] = False
                    changed = True
        if changed:
            self.canvas.draw_idle()

    def _apply_hover_chart(self, index):
        changed = False

        for i, segment in enumerate(self.segments):
            original_index = (
                self.chart_sector_to_item[i]
                if i < len(self.chart_sector_to_item) else None
            )
            target_alpha = 1.0 if (index is None or original_index == index) else 0.25
            if abs((segment.get_alpha() or 1.0) - target_alpha) > 1e-6:
                segment.set_alpha(target_alpha)
                changed = True

        for original_index, item in self.legend_items.items():
            if index is None:
                if item["line"].get_linewidth() != 1.4:
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
                    changed = True
            elif original_index == index:
                if item["line"].get_linewidth() != 3.2:
                    item["line"].set_linewidth(3.2)
                    item["line"].set_alpha(1.0)
                    item["dot"].set_alpha(1.0)
                    item["icon_rect"].set_alpha(1.0)
                    item["icon_text"].set_alpha(1.0)
                    item["text"].set_alpha(1.0)
                    item["text"].set_color(TEXT_COLOR_MAIN)
                    item["zone"].set_facecolor(item["base_color"])
                    item["zone"].set_alpha(0.35)
                    item["zone"].set_edgecolor(item["base_color"])
                    item["zone"].set_linewidth(1.4)
                    changed = True
            else:
                if item["line"].get_linewidth() != 1.0:
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
                    changed = True

        if changed:
            self.canvas.draw_idle()

    # ==================== Навигация ====================

    def navigate_to_item(self, name):
        if self.current_path is None:
            target = name
        else:
            target = os.path.join(self.current_path, name.rstrip(os.sep))

        if not os.path.isdir(target):
            self.status_var.set(f"Не является каталогом: {target}")
            return

        self.status_var.set(f"Сканирование {target}…")
        self.scan_token += 1
        token = self.scan_token

        def worker():
            items = self.scan_directory(target)
            self.after(0, lambda: self._on_directory_scanned(token, target, items, push_history=True))

        threading.Thread(target=worker, daemon=True).start()

    def scan_directory(self, path):
        results = []
        try:
            entries = list(os.scandir(path))
        except OSError:
            return results

        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    size = get_directory_size(entry.path, self.size_cache)
                    results.append((entry.name + os.sep, size))
                else:
                    size = entry.stat(follow_symlinks=False).st_size
                    results.append((entry.name, size))
            except OSError:
                continue

        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def _on_directory_scanned(self, token, path, items, push_history):
        if token != self.scan_token:
            return

        if push_history:
            self.history.append(self.current_path)
        self.current_path = path
        self.current_items = items
        self.explorer_offset = 0
        self.hover_index = None
        self.apply_filter()
        self.path_var.set(f"📁  {path}")
        total_size = sum(s for _, s in items)
        self.status_var.set(
            f"Элементов: {len(items)} | Всего: {get_readable_size(total_size)}"
        )
        self.render_view(animation=True)

    def go_back(self):
        if not self.history:
            self.status_var.set("Это верхний уровень.")
            return
        prev = self.history.pop()
        if prev is None:
            self.load_disks_async()
            return

        self.status_var.set(f"Возврат в {prev}…")
        self.scan_token += 1
        token = self.scan_token

        def worker():
            items = self.scan_directory(prev)
            self.after(0, lambda: self._on_directory_scanned(token, prev, items, push_history=False))

        threading.Thread(target=worker, daemon=True).start()

    def go_home(self):
        if self.current_path is None:
            self.status_var.set("Это верхний уровень.")
            return
        self.history.clear()
        self.search_entry.delete(0, tk.END)
        self.explorer_offset = 0
        self.hover_index = None
        self.load_disks_async()

    def on_search_change(self, event):
        self.apply_filter()
        self.explorer_offset = 0
        self.hover_index = None
        self.render_view(animation=False)

    def apply_filter(self):
        search_text = self.search_entry.get().strip().lower()
        if not search_text:
            self.filtered_items = list(self.current_items)
        else:
            self.filtered_items = [
                (name, size)
                for name, size in self.current_items
                if search_text in name.lower()
            ]

    def toggle_sort(self):
        self.sort_by_size = not self.sort_by_size
        self.explorer_offset = 0
        self.hover_index = None
        self.render_view(animation=False)

    def reveal_current_in_os(self):
        if self.current_path:
            reveal_in_os(self.current_path)
            self.status_var.set(f"Открыто в проводнике: {self.current_path}")
        else:
            self.status_var.set("Выберите каталог для открытия.")

    # ==================== Топ-100 файлов по всему ПК ====================

    def show_top_files_window(self):
        """Сканирует ВСЕ диски ПК и показывает топ-100 самых больших файлов."""
        mount_points = get_all_mount_points()
        if not mount_points:
            self.status_var.set("Не найдено ни одного диска для сканирования.")
            return

        top_n = TOP_FILES_COUNT
        self.status_var.set(f"Поиск топ-{top_n} файлов по всему ПК…")

        # --- Окно прогресса ---
        progress_win = tk.Toplevel(self)
        progress_win.title("Сканирование всего ПК…")
        progress_win.geometry("520x180")
        progress_win.configure(bg=BACKGROUND_PANEL_COLOR)
        progress_win.transient(self)
        progress_win.resizable(False, False)
        progress_win.protocol("WM_DELETE_WINDOW", lambda: on_cancel())

        progress_win.update_idletasks()
        px = self.winfo_rootx() + (self.winfo_width() - 520) // 2
        py = self.winfo_rooty() + (self.winfo_height() - 180) // 2
        progress_win.geometry(f"+{max(px, 0)}+{max(py, 0)}")

        tk.Label(
            progress_win,
            text=f"🏆 Поиск топ-{top_n} самых больших файлов на всём ПК",
            bg=BACKGROUND_PANEL_COLOR, fg=ACCENT_COLOR,
            font=("Segoe UI", 11, "bold"),
        ).pack(pady=(16, 6))

        tk.Label(
            progress_win,
            text="Сканируются диски: " + ", ".join(mount_points),
            bg=BACKGROUND_PANEL_COLOR, fg=TEXT_COLOR_DIM,
            font=("Segoe UI", 8),
        ).pack(pady=(0, 6))

        progress_label_var = tk.StringVar(value="0 файлов просканировано")
        tk.Label(
            progress_win, textvariable=progress_label_var,
            bg=BACKGROUND_PANEL_COLOR, fg=TEXT_COLOR_MAIN,
            font=("Segoe UI", 9),
        ).pack(pady=(0, 8))

        progress_bar = ttk.Progressbar(
            progress_win, mode="indeterminate", length=460,
        )
        progress_bar.pack(pady=(0, 10))
        progress_bar.start(15)

        cancel_flag = {"cancelled": False}

        def on_cancel():
            cancel_flag["cancelled"] = True
            try:
                progress_bar.stop()
                progress_win.destroy()
            except tk.TclError:
                pass
            self.status_var.set("Сканирование отменено.")

        tk.Button(
            progress_win, text="Отмена", command=on_cancel,
            bg=BACKGROUND_PANEL_COLOR_3, fg=TEXT_COLOR_MAIN,
            relief=tk.FLAT, cursor="hand2", padx=20,
        ).pack(pady=(0, 12))

        def worker():
            top_files = []          # список (size, filepath)
            scanned = 0
            last_update = [0]
            skipped_errors = 0

            def on_walk_error(error):
                nonlocal skipped_errors
                skipped_errors += 1
                # не падаем — пропускаем недоступные каталоги

            try:
                for mount in mount_points:
                    if cancel_flag["cancelled"]:
                        return

                    for dirpath, dirnames, filenames in os.walk(
                        mount, onerror=on_walk_error, followlinks=False
                    ):
                        if cancel_flag["cancelled"]:
                            return

                        # Пропускаем псевдо-ФС и мусорные каталоги на Linux
                        if platform.system() == "Linux":
                            base = os.path.basename(dirpath)
                            if base in ("proc", "sys", "dev", "run", "snap", "boot"):
                                dirnames[:] = []
                                continue

                        for filename in filenames:
                            filepath = os.path.join(dirpath, filename)
                            try:
                                size = os.path.getsize(filepath)
                            except OSError:
                                continue
                            if size <= 0:
                                continue

                            top_files.append((size, filepath))
                            scanned += 1

                            # Периодически чистим
                            if len(top_files) > top_n * 4:
                                top_files.sort(key=lambda x: x[0], reverse=True)
                                del top_files[top_n:]

                            if scanned - last_update[0] >= 3000:
                                last_update[0] = scanned
                                try:
                                    self.after(
                                        0,
                                        lambda s=scanned: progress_label_var.set(
                                            f"{s} файлов просканировано…"
                                        ),
                                    )
                                except tk.TclError:
                                    return

                # Финальная сортировка
                top_files.sort(key=lambda x: x[0], reverse=True)
                top_files = top_files[:top_n]

                def finish():
                    try:
                        progress_bar.stop()
                        progress_win.destroy()
                    except tk.TclError:
                        pass
                    self._display_top_files_ui(
                        top_files, "весь ПК", top_n, skipped_errors
                    )

                try:
                    self.after(0, finish)
                except tk.TclError:
                    pass

            except Exception as error:
                def show_error(err=error):
                    try:
                        progress_win.destroy()
                    except tk.TclError:
                        pass
                    self.status_var.set(f"Ошибка поиска: {err}")
                try:
                    self.after(0, show_error)
                except tk.TclError:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _display_top_files_ui(self, top_files, root_path, top_n=100, skipped_errors=0):
        if not top_files:
            self.status_var.set(f"Файлы не найдены ({root_path}).")
            return

        top_win = tk.Toplevel(self)
        top_win.title(f"Топ-{top_n} файлов: {root_path}")
        top_win.geometry("950x650")
        top_win.configure(bg=BACKGROUND_PANEL_COLOR)
        top_win.transient(self)

        # Заголовок
        header = tk.Frame(top_win, bg=BACKGROUND_PANEL_COLOR)
        header.pack(fill=tk.X, padx=12, pady=(12, 6))

        tk.Label(
            header, text=f"🏆 Топ-{top_n} самых больших файлов ({root_path})",
            bg=BACKGROUND_PANEL_COLOR, fg=ACCENT_COLOR,
            font=("Segoe UI", 12, "bold"),
        ).pack(side=tk.LEFT)

        total_found = sum(s for s, _ in top_files)
        tk.Label(
            header,
            text=f"Суммарно: {get_readable_size(total_found)}",
            bg=BACKGROUND_PANEL_COLOR, fg=TEXT_COLOR_DIM,
            font=("Segoe UI", 10),
        ).pack(side=tk.RIGHT)

        # Стиль Treeview
        style = ttk.Style(top_win)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Treeview", background=BACKGROUND_PANEL_COLOR_2,
            foreground=TEXT_COLOR_MAIN, fieldbackground=BACKGROUND_PANEL_COLOR_2,
            borderwidth=0, rowheight=24,
        )
        style.configure(
            "Treeview.Heading", background=BACKGROUND_PANEL_COLOR_3,
            foreground=TEXT_COLOR_MAIN, font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "Treeview",
            background=[("selected", ACCENT_COLOR)],
            foreground=[("selected", BACKGROUND_COLOR)],
        )

        container = tk.Frame(top_win, bg=BACKGROUND_PANEL_COLOR)
        container.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        columns = ("rank", "size", "path")
        tree = ttk.Treeview(
            container, columns=columns, show="headings", style="Treeview",
        )
        tree.heading("rank", text="#")
        tree.heading("size", text="Размер")
        tree.heading("path", text="Путь к файлу")
        tree.column("rank", width=50, anchor=tk.CENTER, stretch=False)
        tree.column("size", width=110, anchor=tk.E, stretch=False)
        tree.column("path", width=720, anchor=tk.W)

        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=scrollbar.set)

        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Цветовые теги для топ-3
        tree.tag_configure("gold", foreground="#ffd60a")
        tree.tag_configure("silver", foreground="#c0c0c0")
        tree.tag_configure("bronze", foreground="#cd7f32")

        for i, (size, filepath) in enumerate(top_files, start=1):
            if i == 1:
                tags = ("gold",)
            elif i == 2:
                tags = ("silver",)
            elif i == 3:
                tags = ("bronze",)
            else:
                tags = ()
            tree.insert(
                "", tk.END,
                values=(i, get_readable_size(size), filepath),
                tags=tags,
            )

        def on_double_click(event):
            item = tree.identify_row(event.y)
            if item:
                values = tree.item(item, "values")
                if len(values) >= 3:
                    filepath = values[2]
                    if os.path.exists(filepath):
                        reveal_in_os(filepath)

        tree.bind("<Double-1>", on_double_click)

        def on_tree_right_click(event):
            item = tree.identify_row(event.y)
            if item:
                tree.selection_set(item)
                values = tree.item(item, "values")
                if len(values) >= 3:
                    filepath = values[2]
                    menu = tk.Menu(
                        top_win, tearoff=0,
                        bg=BACKGROUND_PANEL_COLOR_2, fg=TEXT_COLOR_MAIN,
                        activebackground=ACCENT_COLOR,
                        activeforeground=BACKGROUND_COLOR,
                    )
                    menu.add_command(
                        label="📂 Показать в проводнике",
                        command=lambda p=filepath: reveal_in_os(p),
                    )
                    menu.add_command(
                        label="📋 Копировать путь",
                        command=lambda p=filepath: self.clipboard_set(p),
                    )
                    try:
                        menu.tk_popup(event.x_root, event.y_root)
                    finally:
                        menu.grab_release()

        tree.bind("<Button-3>", on_tree_right_click)

        status = (
            f"Найдено топ-{len(top_files)} файлов. "
            f"Суммарный размер: {get_readable_size(total_found)}"
        )
        if skipped_errors > 0:
            status += f" | Пропущено недоступных мест: {skipped_errors}"
        self.status_var.set(status)

    # ==================== Экспорт ====================

    def export_to_csv(self):
        if not self.filtered_items:
            self.status_var.set("Нет данных для экспорта.")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV файлы", "*.csv")],
            initialfile=f"disk_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )

        if not file_path:
            return

        try:
            with open(file_path, mode="w", encoding="utf-8-sig", newline="") as file:
                writer = csv.writer(file, delimiter=";")
                writer.writerow(["Имя", "Размер (байт)", "Размер (формат)", "Тип"])
                for name, size in self.filtered_items:
                    item_type = "Каталог" if name.endswith(os.sep) else "Файл"
                    writer.writerow([
                        name.rstrip(os.sep), size, get_readable_size(size), item_type,
                    ])
            self.status_var.set(f"Экспорт выполнен: {file_path}")
        except Exception as error:
            self.status_var.set(f"Ошибка экспорта: {error}")


def main():
    app = DiskVisualizer()
    app.mainloop()


if __name__ == "__main__":
    main()