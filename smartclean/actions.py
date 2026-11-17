"""Безопасное удаление найденного мусора."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field

from . import fsutil
from .models import CleanableItem, Risk


@dataclass
class DeleteOutcome:
    deleted: int = 0
    freed: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped: int = 0


_PROTECTED_CACHE: set[str] | None = None


def _protected_paths() -> set[str]:
    """Точные пути, которые нельзя удалять целиком ни при каких условиях."""
    global _PROTECTED_CACHE
    if _PROTECTED_CACHE is not None:
        return _PROTECTED_CACHE

    env = os.environ
    system_drive = env.get("SystemDrive", "C:") + os.sep
    profile = env.get("USERPROFILE", "")
    programdata = env.get("PROGRAMDATA", "")
    windir = env.get("SystemRoot", r"C:\Windows")

    paths = {
        windir,
        os.path.join(windir, "System32"),
        os.path.join(windir, "SysWOW64"),
        os.path.join(windir, "WinSxS"),
        os.path.join(system_drive, "Program Files"),
        os.path.join(system_drive, "Program Files (x86)"),
        os.path.join(system_drive, "Users"),
        programdata,
    }
    if profile:
        paths.update({
            profile,
            os.path.join(profile, "AppData"),
            os.path.join(profile, "Documents"),
            os.path.join(profile, "Desktop"),
            os.path.join(profile, "Downloads"),
        })

    protected: set[str] = set()
    for path in paths:
        if not path:
            continue
        try:
            protected.add(
                os.path.normcase(os.path.abspath(path)).rstrip("\\/")
            )
        except OSError:
            continue
    _PROTECTED_CACHE = protected
    return protected


def _is_protected(path: str) -> bool:
    """Защита от удаления корней дисков и критичных каталогов."""
    if not path:
        return True
    normalized = os.path.normcase(os.path.abspath(path)).rstrip("\\/")
    # Корень диска: "c:", "d:" и т.п.
    if len(normalized) <= 2:
        return True
    return normalized in _protected_paths()


def _log_path() -> str:
    base = os.path.join(os.path.expanduser("~"), ".diskvieuver")
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        return ""
    return os.path.join(base, "cleanup_log.jsonl")


def _write_log(records: list[dict]) -> None:
    path = _log_path()
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as file:
            for record in records:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def delete_items(
    items: list[CleanableItem],
    use_recycle_bin: bool = True,
    progress_cb=None,
    cancel_event: threading.Event | None = None,
) -> DeleteOutcome:
    """Удаляет выбранные элементы. По умолчанию — в корзину."""
    outcome = DeleteOutcome()
    log_records: list[dict] = []
    total = len(items)

    for index, item in enumerate(items, start=1):
        if cancel_event is not None and cancel_event.is_set():
            break
        if progress_cb is not None:
            try:
                progress_cb(index, total, item.name)
            except Exception:
                pass

        if not item.can_delete or item.extra.get("report_only"):
            outcome.skipped += 1
            continue
        # Элементы с уровнем «опасно» не удаляем даже при ошибочном флаге.
        if item.risk is Risk.DANGER:
            outcome.skipped += 1
            continue
        if _is_protected(item.path):
            outcome.skipped += 1
            continue
        if not os.path.exists(item.path):
            outcome.skipped += 1
            continue

        try:
            if item.contents_only and os.path.isdir(item.path):
                freed = 0
                for child in list(fsutil.iter_children(item.path)):
                    if cancel_event is not None and cancel_event.is_set():
                        break
                    child_size = fsutil.measure_path(child)
                    fsutil.remove_path(child, use_recycle_bin=use_recycle_bin)
                    freed += child_size
                outcome.freed += freed
                outcome.deleted += 1
            else:
                freed = fsutil.measure_path(item.path)
                fsutil.remove_path(item.path, use_recycle_bin=use_recycle_bin)
                outcome.freed += freed
                outcome.deleted += 1

            log_records.append({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "path": item.path,
                "size": freed,
                "rule": item.rule_id,
                "recycle_bin": use_recycle_bin,
            })
        except Exception as error:  # noqa: BLE001 — нужен текст любой ошибки
            outcome.failed.append((item.path, str(error)))

    _write_log(log_records)
    return outcome
