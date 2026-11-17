"""Декларативные правила поиска мусора.

Каждое правило описывает, *что* искать, *насколько* это безопасно удалять
и *как* удалять (целиком или только содержимое каталога).

Правила специально описаны данными, а не кодом: чтобы добавить новую
категорию мусора, достаточно добавить один `CleanRule` в `build_default_rules`.
"""

from __future__ import annotations

import glob
import os
import platform
from dataclasses import dataclass

from .models import Risk


@dataclass(frozen=True)
class CleanRule:
    """Одно правило очистки."""

    id: str
    name: str
    description: str
    risk: Risk
    category: str
    paths: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    min_age_days: int = 0
    contents_only: bool = False
    report_only: bool = False
    requires_admin: bool = False

    def iter_targets(self):
        """Разворачивает шаблоны путей в существующие цели (без дублей)."""
        seen: set[str] = set()
        for template in self.paths:
            expanded = os.path.expandvars(os.path.expanduser(template))
            if not expanded:
                continue
            for base in glob.glob(expanded) or (
                [expanded] if os.path.exists(expanded) else []
            ):
                if not os.path.exists(base):
                    continue
                if self.patterns:
                    for pattern in self.patterns:
                        for match in glob.glob(os.path.join(base, pattern)):
                            key = os.path.normcase(match)
                            if key in seen:
                                continue
                            seen.add(key)
                            yield match
                else:
                    key = os.path.normcase(base)
                    if key in seen:
                        continue
                    seen.add(key)
                    yield base


# ---------- Построение набора правил ----------

def _join(root: str, *parts: str) -> str:
    return os.path.join(root, *parts) if root else ""


def _windows_rules() -> list[CleanRule]:
    env = os.environ
    local = env.get("LOCALAPPDATA", "")
    roaming = env.get("APPDATA", "")
    temp = env.get("TEMP", "")
    programdata = env.get("PROGRAMDATA", "")
    windir = env.get("SystemRoot", r"C:\Windows")
    systemdrive = env.get("SystemDrive", "C:")
    profile = env.get("USERPROFILE", "")
    pf = env.get("ProgramFiles", r"C:\Program Files")
    pf86 = env.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

    rules: list[CleanRule] = []

    def add(rule: CleanRule) -> None:
        if any(rule.paths):
            rules.append(rule)

    # --- Временные файлы ---
    add(CleanRule(
        id="temp_user",
        name="Временные файлы пользователя",
        description="Содержимое %TEMP%: кэш установщиков, временные файлы программ.",
        risk=Risk.SAFE,
        category="Временные файлы",
        paths=(temp,),
        contents_only=True,
    ))
    add(CleanRule(
        id="temp_windows",
        name="Временные файлы Windows",
        description="C:\\Windows\\Temp — временные файлы системы и служб.",
        risk=Risk.CAUTION,
        category="Временные файлы",
        paths=(_join(windir, "Temp"),),
        contents_only=True,
        requires_admin=True,
    ))
    add(CleanRule(
        id="inet_cache",
        name="Кэш Internet Explorer / WinINet",
        description="Кэш загрузок встроенного в Windows HTTP-клиента.",
        risk=Risk.SAFE,
        category="Системный кэш",
        paths=(_join(local, "Microsoft", "Windows", "INetCache"),),
        contents_only=True,
    ))
    add(CleanRule(
        id="webcache",
        name="Кэш WebCache Windows",
        description="Служебный кэш Windows (может быть занят системой).",
        risk=Risk.CAUTION,
        category="Системный кэш",
        paths=(_join(local, "Microsoft", "Windows", "WebCache"),),
        contents_only=True,
    ))
    add(CleanRule(
        id="thumbnails",
        name="Кэш миниатюр и иконок",
        description="thumbcache_*.db и iconcache_*.db — пересоздаются автоматически.",
        risk=Risk.SAFE,
        category="Системный кэш",
        paths=(_join(local, "Microsoft", "Windows", "Explorer"),),
        patterns=("thumbcache_*.db", "iconcache_*.db"),
    ))
    add(CleanRule(
        id="d3d_cache",
        name="Кэш шейдеров DirectX",
        description="Кэш скомпилированных шейдеров D3D.",
        risk=Risk.SAFE,
        category="Системный кэш",
        paths=(_join(local, "D3DSCache"),),
        contents_only=True,
    ))
    add(CleanRule(
        id="nvidia_cache",
        name="Кэш NVIDIA",
        description="DXCache и GLCache драйвера NVIDIA.",
        risk=Risk.SAFE,
        category="Кэш видеодрайверов",
        paths=(
            _join(local, "NVIDIA", "DXCache"),
            _join(local, "NVIDIA", "GLCache"),
        ),
        contents_only=True,
    ))
    add(CleanRule(
        id="amd_cache",
        name="Кэш AMD",
        description="Кэш шейдеров драйвера AMD.",
        risk=Risk.SAFE,
        category="Кэш видеодрайверов",
        paths=(
            _join(local, "AMD", "DxCache"),
            _join(local, "AMD", "GLCache"),
        ),
        contents_only=True,
    ))
    add(CleanRule(
        id="intel_cache",
        name="Кэш Intel",
        description="Кэш шейдеров драйвера Intel.",
        risk=Risk.SAFE,
        category="Кэш видеодрайверов",
        paths=(_join(local, "Intel", "ShaderCache"),),
        contents_only=True,
    ))

    # --- Windows Update и обслуживание ---
    add(CleanRule(
        id="update_download",
        name="Загруженные обновления Windows",
        description=(
            "Скачанные пакеты обновлений в SoftwareDistribution\\Download. "
            "Если Windows прямо сейчас устанавливает обновления, очистка "
            "может прервать загрузку — лучше дождаться завершения."
        ),
        risk=Risk.CAUTION,
        category="Windows Update",
        paths=(_join(windir, "SoftwareDistribution", "Download"),),
        contents_only=True,
        requires_admin=True,
    ))
    add(CleanRule(
        id="delivery_optimization",
        name="Кэш оптимизации доставки",
        description="Delivery Optimization — кэш раздачи обновлений другим ПК.",
        risk=Risk.SAFE,
        category="Windows Update",
        paths=(
            _join(
                windir, "ServiceProfiles", "NetworkService", "AppData", "Local",
                "Microsoft", "Windows", "DeliveryOptimization",
            ),
        ),
        contents_only=True,
        requires_admin=True,
    ))
    add(CleanRule(
        id="prefetch",
        name="Файлы Prefetch",
        description="Кэш предзагрузки приложений. Удаление замедлит первый запуск программ.",
        risk=Risk.CAUTION,
        category="Windows Update",
        paths=(_join(windir, "Prefetch"),),
        contents_only=True,
        requires_admin=True,
    ))

    # --- Логи и отчёты ---
    add(CleanRule(
        id="wer_user",
        name="Отчёты об ошибках (пользователь)",
        description="Архивы Windows Error Reporting пользователя.",
        risk=Risk.SAFE,
        category="Логи и отчёты",
        paths=(_join(local, "Microsoft", "Windows", "WER"),),
        contents_only=True,
    ))
    add(CleanRule(
        id="wer_system",
        name="Отчёты об ошибках (система)",
        description="Архивы Windows Error Reporting в ProgramData.",
        risk=Risk.CAUTION,
        category="Логи и отчёты",
        paths=(_join(programdata, "Microsoft", "Windows", "WER"),),
        contents_only=True,
        requires_admin=True,
    ))
    add(CleanRule(
        id="crash_dumps",
        name="Дампы падений приложений",
        description="Аварийные дампы в %LOCALAPPDATA%\\CrashDumps.",
        risk=Risk.SAFE,
        category="Логи и отчёты",
        paths=(_join(local, "CrashDumps"),),
        contents_only=True,
    ))
    add(CleanRule(
        id="minidumps",
        name="Дампы памяти Windows",
        description="Minidump и MEMORY.DMP — диагностика синих экранов.",
        risk=Risk.CAUTION,
        category="Логи и отчёты",
        paths=(_join(windir, "Minidump"), _join(windir, "MEMORY.DMP")),
        contents_only=True,
        requires_admin=True,
    ))
    add(CleanRule(
        id="windows_logs",
        name="Логи Windows",
        description="Каталоги C:\\Windows\\Logs и C:\\Windows\\Panther.",
        risk=Risk.CAUTION,
        category="Логи и отчёты",
        paths=(_join(windir, "Logs"), _join(windir, "Panther")),
        contents_only=True,
        requires_admin=True,
    ))
    add(CleanRule(
        id="font_cache",
        name="Кэш шрифтов",
        description="Служебный кэш шрифтов Windows.",
        risk=Risk.CAUTION,
        category="Логи и отчёты",
        paths=(
            _join(
                windir, "ServiceProfiles", "LocalService", "AppData", "Local",
                "FontCache",
            ),
        ),
        contents_only=True,
        requires_admin=True,
    ))

    # --- Кэш браузеров ---
    chrome_cache = ("Cache", "Code Cache", "GPUCache", "Service Worker\\CacheStorage")
    add(CleanRule(
        id="chrome_cache",
        name="Кэш Google Chrome",
        description="Кэш страниц и скриптов всех профилей Chrome.",
        risk=Risk.SAFE,
        category="Кэш браузеров",
        paths=(_join(local, "Google", "Chrome", "User Data", "*"),),
        patterns=chrome_cache,
    ))
    add(CleanRule(
        id="edge_cache",
        name="Кэш Microsoft Edge",
        description="Кэш страниц и скриптов всех профилей Edge.",
        risk=Risk.SAFE,
        category="Кэш браузеров",
        paths=(_join(local, "Microsoft", "Edge", "User Data", "*"),),
        patterns=chrome_cache,
    ))
    add(CleanRule(
        id="brave_cache",
        name="Кэш Brave",
        description="Кэш страниц и скриптов Brave.",
        risk=Risk.SAFE,
        category="Кэш браузеров",
        paths=(_join(local, "BraveSoftware", "Brave-Browser", "User Data", "*"),),
        patterns=chrome_cache,
    ))
    add(CleanRule(
        id="yandex_cache",
        name="Кэш Яндекс.Браузера",
        description="Кэш страниц и скриптов Яндекс.Браузера.",
        risk=Risk.SAFE,
        category="Кэш браузеров",
        paths=(_join(local, "Yandex", "YandexBrowser", "User Data", "*"),),
        patterns=chrome_cache,
    ))
    add(CleanRule(
        id="opera_cache",
        name="Кэш Opera",
        description="Кэш страниц и скриптов Opera.",
        risk=Risk.SAFE,
        category="Кэш браузеров",
        paths=(
            _join(local, "Opera Software", "Opera Stable"),
            _join(roaming, "Opera Software", "Opera Stable"),
        ),
        patterns=("Cache", "Code Cache", "GPUCache"),
    ))
    add(CleanRule(
        id="firefox_cache",
        name="Кэш Mozilla Firefox",
        description="Кэш cache2 всех профилей Firefox.",
        risk=Risk.SAFE,
        category="Кэш браузеров",
        paths=(_join(local, "Mozilla", "Firefox", "Profiles", "*"),),
        patterns=("cache2", "startupCache"),
    ))

    # --- Кэш приложений ---
    add(CleanRule(
        id="discord_cache",
        name="Кэш Discord",
        description="Кэш изображений и скриптов Discord.",
        risk=Risk.SAFE,
        category="Кэш приложений",
        paths=(_join(roaming, "discord"),),
        patterns=("Cache", "Code Cache", "GPUCache"),
    ))
    add(CleanRule(
        id="slack_cache",
        name="Кэш Slack",
        description="Кэш Slack.",
        risk=Risk.SAFE,
        category="Кэш приложений",
        paths=(_join(roaming, "Slack"),),
        patterns=("Cache", "Code Cache", "GPUCache"),
    ))
    add(CleanRule(
        id="teams_cache",
        name="Кэш Microsoft Teams",
        description="Кэш Teams (классический клиент).",
        risk=Risk.SAFE,
        category="Кэш приложений",
        paths=(_join(roaming, "Microsoft", "Teams"),),
        patterns=("Cache", "Code Cache", "GPUCache"),
    ))
    add(CleanRule(
        id="spotify_cache",
        name="Кэш Spotify",
        description="Кэш обложек и данных Spotify.",
        risk=Risk.SAFE,
        category="Кэш приложений",
        paths=(_join(local, "Spotify", "Storage"),),
        contents_only=True,
    ))
    add(CleanRule(
        id="pip_cache",
        name="Кэш pip",
        description="Скачанные wheel-пакеты Python.",
        risk=Risk.SAFE,
        category="Кэш разработчика",
        paths=(_join(local, "pip", "Cache"),),
        contents_only=True,
    ))
    add(CleanRule(
        id="npm_cache",
        name="Кэш npm",
        description="Кэш пакетов npm.",
        risk=Risk.SAFE,
        category="Кэш разработчика",
        paths=(_join(roaming, "npm-cache"), _join(local, "npm-cache")),
        contents_only=True,
    ))
    add(CleanRule(
        id="nuget_cache",
        name="Кэш NuGet",
        description="Кэш пакетов .NET NuGet.",
        risk=Risk.SAFE,
        category="Кэш разработчика",
        paths=(_join(local, "NuGet", "v3-cache"),),
        contents_only=True,
    ))
    add(CleanRule(
        id="steam_shader_cache",
        name="Кэш шейдеров Steam",
        description="Кэш шейдеров игр Steam (перекачается при запуске игры).",
        risk=Risk.SAFE,
        category="Игровые кэши",
        paths=(
            _join(pf86, "Steam", "steamapps", "shadercache"),
            _join(pf, "Steam", "steamapps", "shadercache"),
        ),
        contents_only=True,
        requires_admin=True,
    ))

    # --- Пользовательские файлы ---
    add(CleanRule(
        id="downloads_installers",
        name="Старые установщики в «Загрузках»",
        description="EXE/MSI/ISO старше 45 дней в папке Downloads.",
        risk=Risk.CAUTION,
        category="Загрузки",
        paths=(_join(profile, "Downloads"),),
        patterns=("*.exe", "*.msi", "*.msix", "*.iso"),
        min_age_days=45,
    ))

    # --- Корзина и системные файлы ---
    add(CleanRule(
        id="recycle_bin",
        name="Корзина",
        description=(
            "Содержимое корзины. Безопаснее очищать её средствами Windows: "
            "программа только показывает размер и не удаляет файлы."
        ),
        risk=Risk.CAUTION,
        category="Корзина",
        paths=(_join(systemdrive + os.sep, "$Recycle.Bin"),),
        contents_only=True,
        report_only=True,
        requires_admin=True,
    ))
    add(CleanRule(
        id="windows_old",
        name="Windows.old (предыдущая версия Windows)",
        description="Резервная копия старой установки Windows. Удаляется только вручную.",
        risk=Risk.DANGER,
        category="Системные файлы",
        paths=(_join(systemdrive + os.sep, "Windows.old"),),
        report_only=True,
        requires_admin=True,
    ))
    add(CleanRule(
        id="winsxs_backup",
        name="Резервные копии WinSxS",
        description="Компоненты обновлений. Удаляются только через DISM /StartComponentCleanup.",
        risk=Risk.DANGER,
        category="Системные файлы",
        paths=(_join(windir, "WinSxS", "Backup"),),
        report_only=True,
        requires_admin=True,
    ))
    add(CleanRule(
        id="windows_installer",
        name="Кэш установщика Windows",
        description="MSI-кэш C:\\Windows\\Installer. Не удаляйте вручную — сломает удаление программ.",
        risk=Risk.DANGER,
        category="Системные файлы",
        paths=(_join(windir, "Installer"),),
        report_only=True,
        requires_admin=True,
    ))
    add(CleanRule(
        id="system_files",
        name="Файлы подкачки и гибернации",
        description="pagefile.sys / hiberfil.sys. Отключаются через настройки системы.",
        risk=Risk.DANGER,
        category="Системные файлы",
        paths=(
            _join(systemdrive + os.sep, "pagefile.sys"),
            _join(systemdrive + os.sep, "hiberfil.sys"),
            _join(systemdrive + os.sep, "swapfile.sys"),
        ),
        report_only=True,
        requires_admin=True,
    ))

    return rules


def _posix_rules() -> list[CleanRule]:
    home = os.path.expanduser("~")
    return [
        CleanRule(
            id="tmp_posix",
            name="Временные файлы /tmp",
            description="Содержимое /tmp (файлы, не занятые процессами).",
            risk=Risk.CAUTION,
            category="Временные файлы",
            paths=("/tmp",),
            contents_only=True,
        ),
        CleanRule(
            id="thumbnails_posix",
            name="Кэш миниатюр",
            description="Кэш превью файлового менеджера.",
            risk=Risk.SAFE,
            category="Системный кэш",
            paths=(_join(home, ".cache", "thumbnails"),),
            contents_only=True,
        ),
        CleanRule(
            id="pip_cache_posix",
            name="Кэш pip",
            description="Скачанные wheel-пакеты Python.",
            risk=Risk.SAFE,
            category="Кэш разработчика",
            paths=(_join(home, ".cache", "pip"),),
            contents_only=True,
        ),
        CleanRule(
            id="npm_cache_posix",
            name="Кэш npm",
            description="Кэш пакетов npm.",
            risk=Risk.SAFE,
            category="Кэш разработчика",
            paths=(_join(home, ".npm", "_cacache"),),
            contents_only=True,
        ),
        CleanRule(
            id="chrome_cache_posix",
            name="Кэш Chrome/Chromium",
            description="Кэш браузера Chromium.",
            risk=Risk.SAFE,
            category="Кэш браузеров",
            paths=(
                _join(home, ".cache", "google-chrome"),
                _join(home, ".cache", "chromium"),
            ),
            contents_only=True,
        ),
        CleanRule(
            id="firefox_cache_posix",
            name="Кэш Firefox",
            description="Кэш браузера Firefox.",
            risk=Risk.SAFE,
            category="Кэш браузеров",
            paths=(_join(home, ".cache", "mozilla"),),
            contents_only=True,
        ),
    ]


def build_default_rules() -> list[CleanRule]:
    """Возвращает набор правил для текущей ОС."""
    if platform.system() == "Windows":
        return _windows_rules()
    return _posix_rules()
