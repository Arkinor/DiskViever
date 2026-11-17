"""Сканер мусора: применяет правила и ищет остатки удалённых программ."""

from __future__ import annotations

import os
import threading
import time

from . import fsutil
from .installed import collect_installed_programs
from .models import CleanableItem, ScanResult
from .orphans import find_orphans
from .rules import CleanRule, build_default_rules


class Scanner:
    """Полный проход по правилам очистки + поиск «сиротских» папок."""

    def __init__(self, rules: list[CleanRule] | None = None):
        self.rules = rules if rules is not None else build_default_rules()

    # ---------- Публичный API ----------

    def scan(
        self,
        progress_cb=None,
        cancel_event: threading.Event | None = None,
        include_orphans: bool = True,
    ) -> ScanResult:
        started = time.time()
        items: list[CleanableItem] = []
        errors = 0
        rules_checked = 0
        installed_programs = 0

        total_rules = len(self.rules)
        for index, rule in enumerate(self.rules):
            if cancel_event is not None and cancel_event.is_set():
                break
            rules_checked += 1
            if progress_cb is not None:
                try:
                    progress_cb(f"Правило {index + 1}/{total_rules}: {rule.name}")
                except Exception:
                    pass
            try:
                items.extend(self._scan_rule(rule, cancel_event))
            except Exception:
                errors += 1
                continue

        if include_orphans and not (cancel_event and cancel_event.is_set()):
            if progress_cb is not None:
                try:
                    progress_cb("Ищу остатки удалённых программ…")
                except Exception:
                    pass
            try:
                programs = collect_installed_programs()
                installed_programs = len(programs)
                if programs:
                    items.extend(find_orphans(
                        programs,
                        progress_cb=progress_cb,
                        cancel_event=cancel_event,
                    ))
            except Exception:
                errors += 1

        items = self._deduplicate(items)
        items.sort(key=lambda item: item.size, reverse=True)
        return ScanResult(
            items=items,
            errors=errors,
            duration=time.time() - started,
            rules_checked=rules_checked,
            installed_programs=installed_programs,
        )

    # ---------- Внутреннее ----------

    @staticmethod
    def _deduplicate(items: list[CleanableItem]) -> list[CleanableItem]:
        seen: set[str] = set()
        unique: list[CleanableItem] = []
        for item in items:
            key = os.path.normcase(os.path.abspath(item.path))
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _scan_rule(
        self,
        rule: CleanRule,
        cancel_event: threading.Event | None,
    ) -> list[CleanableItem]:
        results: list[CleanableItem] = []
        for target in rule.iter_targets():
            if cancel_event is not None and cancel_event.is_set():
                break

            is_file = os.path.isfile(target)
            if is_file and rule.min_age_days > 0:
                if fsutil.age_days(target) < rule.min_age_days:
                    continue

            if rule.contents_only and not is_file:
                size = self._measure_contents(target, cancel_event)
            else:
                size = fsutil.measure_path(target, cancel_event)

            if size <= 0:
                continue

            name = os.path.basename(target.rstrip("\\/")) or target
            note = ""
            if rule.requires_admin:
                note = "Может потребоваться запуск от имени администратора"
            if rule.report_only:
                note = "Только информация — удаление вручную системными средствами"

            results.append(CleanableItem(
                rule_id=rule.id,
                name=name,
                path=target,
                size=size,
                risk=rule.risk,
                category=rule.category,
                description=rule.description,
                can_delete=not rule.report_only,
                contents_only=rule.contents_only,
                note=note,
                # Ничего не выбираем автоматически: пользователь должен
                # осознанно нажать «Выбрать безопасное» или отметить вручную.
                selected=False,
                extra={
                    "rule_name": rule.name,
                    "requires_admin": rule.requires_admin,
                    "report_only": rule.report_only,
                },
            ))
        return results

    @staticmethod
    def _measure_contents(
        path: str,
        cancel_event: threading.Event | None,
    ) -> int:
        total = 0
        for child in fsutil.iter_children(path):
            total += fsutil.measure_path(child, cancel_event)
        return total
