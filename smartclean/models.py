"""Модели данных модуля «Умная очистка»."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Risk(str, Enum):
    """Уровень риска удаления элемента."""

    SAFE = "safe"
    CAUTION = "caution"
    DANGER = "danger"

    @property
    def label(self) -> str:
        return {
            Risk.SAFE: "Безопасно",
            Risk.CAUTION: "Осторожно",
            Risk.DANGER: "Опасно",
        }[self]

    @property
    def color(self) -> str:
        return {
            Risk.SAFE: "#69db7c",
            Risk.CAUTION: "#ffd43b",
            Risk.DANGER: "#ff6b6b",
        }[self]

    @property
    def hint(self) -> str:
        """Короткое объяснение, что означает уровень риска."""
        return {
            Risk.SAFE: (
                "Можно удалять: это кэш или временные файлы, "
                "они пересоздаются автоматически."
            ),
            Risk.CAUTION: (
                "Проверьте содержимое: элемент может понадобиться "
                "программам или для восстановления."
            ),
            Risk.DANGER: (
                "Только для информации: удаление вручную может "
                "повредить системе."
            ),
        }[self]


@dataclass
class CleanableItem:
    """Один элемент, который можно очистить."""

    rule_id: str
    name: str
    path: str
    size: int
    risk: Risk
    category: str
    description: str
    can_delete: bool = True
    contents_only: bool = False
    is_orphan: bool = False
    note: str = ""
    selected: bool = False
    extra: dict = field(default_factory=dict)


@dataclass
class ScanResult:
    """Результат полного прохода сканера."""

    items: list[CleanableItem]
    errors: int = 0
    duration: float = 0.0
    rules_checked: int = 0
    installed_programs: int = 0

    @property
    def total_size(self) -> int:
        return sum(item.size for item in self.items)

    @property
    def safe_size(self) -> int:
        return sum(
            item.size for item in self.items if item.risk is Risk.SAFE
        )
