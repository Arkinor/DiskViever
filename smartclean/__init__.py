"""Модуль «Умная очистка» для DiskViever.

Содержит декларативные правила поиска мусора, сканер, безопасное удаление
и виджет вкладки. Модуль не зависит от `main.py`, чтобы его можно было
развивать отдельно и не ломать визуализатор.
"""

from .models import CleanableItem, Risk, ScanResult
from .scanner import Scanner
from .rules import build_default_rules

__all__ = [
    "CleanableItem",
    "Risk",
    "ScanResult",
    "Scanner",
    "build_default_rules",
]
