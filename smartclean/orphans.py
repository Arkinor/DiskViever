"""Поиск «сиротских» каталогов — остатков от удалённых игр и программ.

Логика:
  1. Собираем установленные программы (реестр, Steam, Epic, GOG, меню «Пуск»).
  2. Смотрим верхнеуровневые папки в типичных местах хранения данных
     (AppData\\Local, AppData\\Roaming, LocalLow, ProgramData).
     «Документы» и «Сохранения игр» намеренно не сканируются: это
     пользовательские данные, а не мусор.
  3. Папка считается остатком, если:
       * её имя не похоже ни на одну установленную программу;
       * она не системная/служебная;
       * её размер больше `min_size`;
       * её содержимое не менялось дольше `min_age_days`.

Результат помечается риском CAUTION и НЕ выбирается автоматически.
"""

from __future__ import annotations

import os
import platform
import threading
import time

from . import fsutil
from .classifier import (
    build_program_index,
    is_system_folder,
    match_installed,
)
from .installed import InstalledProgram
from .models import CleanableItem, Risk

ORPHAN_CATEGORY = "Остатки удалённых программ"
ORPHAN_RULE_ID = "orphan_program_leftovers"

DEFAULT_MIN_SIZE = 5 * 1024 * 1024      # 5 МБ
DEFAULT_MIN_AGE_DAYS = 30

# Папки-контейнеры, внутри которых лежат данные разных игр.
# Их нужно раскрывать, а не помечать целиком.
CONTAINER_FOLDERS = {
    "my games", "saved games", "games", "rockstar games", "electronic arts",
    "ubisoft", "cd projekt red", "square enix", "bethesda softworks",
    "paradox interactive", "2k games", "sega", "capcom", "bandai namco",
    "activision", "blizzard entertainment", "riot games", "epic games",
    "gog.com", "wargaming.net", "ea games", "focus entertainment",
    "deep silver", "thq nordic", "techland", "bohemia interactive",
}


def _iter_candidates(root: str, depth: int = 0):
    """Перечисляет кандидатов, раскрывая папки-контейнеры (не глубже 2 уровней)."""
    try:
        entries = list(os.scandir(root))
    except OSError:
        return
    for entry in entries:
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        if entry.name.strip().lower() in CONTAINER_FOLDERS and depth < 2:
            yield from _iter_candidates(entry.path, depth + 1)
        else:
            yield entry


def candidate_roots() -> list[tuple[str, str]]:
    """Возвращает пары (путь, человекочитаемое место)."""
    roots: list[tuple[str, str]] = []
    if platform.system() != "Windows":
        return roots

    env = os.environ
    local = env.get("LOCALAPPDATA", "")
    roaming = env.get("APPDATA", "")
    programdata = env.get("PROGRAMDATA", "")
    profile = env.get("USERPROFILE", "")

    if local:
        roots.append((local, "AppData\\Local"))
        local_low = os.path.join(os.path.dirname(local), "LocalLow")
        roots.append((local_low, "AppData\\LocalLow"))
    if roaming:
        roots.append((roaming, "AppData\\Roaming"))
    if programdata:
        roots.append((programdata, "ProgramData"))
    # «Документы» и «Сохранения игр» не сканируем: там личные файлы
    # и сохранения игр, которые нельзя считать мусором.
    return roots


def find_orphans(
    programs: list[InstalledProgram],
    progress_cb=None,
    cancel_event: threading.Event | None = None,
    min_size: int = DEFAULT_MIN_SIZE,
    min_age_days: int = DEFAULT_MIN_AGE_DAYS,
) -> list[CleanableItem]:
    """Возвращает список каталогов, похожих на остатки удалённых программ."""
    if platform.system() != "Windows":
        return []

    normalized, tokens = build_program_index(programs)
    items: list[CleanableItem] = []
    checked: set[str] = set()

    for root, label in candidate_roots():
        if cancel_event is not None and cancel_event.is_set():
            break
        if not os.path.isdir(root):
            continue

        for entry in _iter_candidates(root):
            if cancel_event is not None and cancel_event.is_set():
                break

            name = entry.name
            key = os.path.normcase(entry.path)
            if key in checked:
                continue
            checked.add(key)

            if is_system_folder(name):
                continue
            if match_installed(name, normalized, tokens) is not None:
                continue

            try:
                folder_age = (time.time() - os.path.getmtime(entry.path)) / 86400.0
            except OSError:
                continue
            if folder_age < min_age_days:
                continue

            if progress_cb is not None:
                try:
                    progress_cb(f"Проверяю остатки: {name}")
                except Exception:
                    pass

            size = fsutil.measure_path(entry.path, cancel_event)
            if size < min_size:
                continue

            items.append(CleanableItem(
                rule_id=ORPHAN_RULE_ID,
                name=name,
                path=entry.path,
                size=size,
                risk=Risk.CAUTION,
                category=ORPHAN_CATEGORY,
                description=(
                    f"Папка в {label} не совпала ни с одной установленной "
                    f"программой и не менялась {int(folder_age)} дн. "
                    "Похоже на остатки удалённой игры/приложения. "
                    "Проверьте содержимое перед удалением."
                ),
                can_delete=True,
                is_orphan=True,
                note=f"Не найдено установленной программы: {name}",
            ))

    items.sort(key=lambda item: item.size, reverse=True)
    return items
