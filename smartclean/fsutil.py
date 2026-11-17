"""Низкоуровневые файловые утилиты для сканера очистки."""

from __future__ import annotations

import os
import threading
import time


def measure_path(path: str, cancel_event: threading.Event | None = None) -> int:
    """Считает суммарный размер файла или каталога (без разыменования ссылок)."""
    if not path:
        return 0
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
    except OSError:
        return 0

    total = 0
    stack = [path]
    while stack:
        if cancel_event is not None and cancel_event.is_set():
            return total
        current = stack.pop()
        try:
            with os.scandir(current) as iterator:
                for entry in iterator:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def age_days(path: str) -> float:
    """Возраст элемента в днях по времени последнего изменения."""
    try:
        return (time.time() - os.path.getmtime(path)) / 86400.0
    except OSError:
        return 0.0


def is_empty_dir(path: str) -> bool:
    """Проверяет, что каталог пуст (без учёта скрытых системных файлов)."""
    try:
        with os.scandir(path) as iterator:
            for _ in iterator:
                return False
        return True
    except OSError:
        return False


def _windows_recycle(path: str) -> bool:
    """Перемещает объект в корзину через WinAPI (без send2trash)."""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    FO_DELETE = 3
    FOF_ALLOWUNDO = 0x0040
    FOF_NOCONFIRMATION = 0x0010
    FOF_SILENT = 0x0004
    FOF_NOERRORUI = 0x0400

    operation = SHFILEOPSTRUCTW()
    operation.hwnd = None
    operation.wFunc = FO_DELETE
    operation.pFrom = os.path.abspath(path) + "\0\0"
    operation.pTo = None
    operation.fFlags = (
        FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    )
    try:
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    except Exception:
        return False
    return result == 0 and not operation.fAnyOperationsAborted


def _try_recycle_bin(path: str) -> bool:
    try:
        from send2trash import send2trash
    except ImportError:
        send2trash = None

    if send2trash is not None:
        try:
            send2trash(path)
            return True
        except Exception:
            return False

    if os.name == "nt":
        return _windows_recycle(path)
    return False


def remove_path(path: str, use_recycle_bin: bool = True) -> None:
    """Удаляет файл/каталог.

    Если запрошена корзина, но переместить туда не удалось — выбрасывает
    исключение, а не удаляет безвозвратно (безопасность важнее).
    """
    if use_recycle_bin:
        if _try_recycle_bin(path):
            return
        raise OSError(
            "Не удалось переместить в корзину. Установите send2trash "
            "или снимите галочку «В корзину» для безвозвратного удаления."
        )

    import shutil

    def on_error(function, target, _exc_info):
        try:
            os.chmod(target, 0o700)
            function(target)
        except OSError:
            raise

    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, onerror=on_error)
    else:
        try:
            os.remove(path)
        except PermissionError:
            os.chmod(path, 0o700)
            os.remove(path)


def iter_children(path: str):
    """Безопасно перечисляет непосредственных потомков каталога."""
    try:
        with os.scandir(path) as iterator:
            for entry in iterator:
                yield entry.path
    except OSError:
        return
