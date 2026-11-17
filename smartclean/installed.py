"""Сбор списка установленных программ для поиска «сиротских» остатков.

Источники (Windows):
  * реестр Uninstall (HKLM, HKLM\\WOW6432Node, HKCU);
  * Steam (библиотеки из libraryfolders.vdf);
  * Epic Games Store (манифесты .item);
  * GOG (реестр);
  * ярлыки в меню «Пуск».

На других ОС возвращается пустой список — поиск остатков отключается.
"""

from __future__ import annotations

import glob
import json
import os
import platform
import re
from dataclasses import dataclass


@dataclass
class InstalledProgram:
    name: str
    location: str = ""
    publisher: str = ""
    source: str = ""


_VDF_PATH_RE = re.compile(r'"path"\s+"([^"]+)"')
_VDF_NAME_RE = re.compile(r'"name"\s+"([^"]+)"')


def _registry_programs() -> list[InstalledProgram]:
    if platform.system() != "Windows":
        return []
    try:
        import winreg
    except ImportError:
        return []

    roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    programs: list[InstalledProgram] = []

    for hive, subkey in roots:
        try:
            key = winreg.OpenKey(hive, subkey)
        except OSError:
            continue
        with key:
            try:
                subkeys_count = winreg.QueryInfoKey(key)[0]
            except OSError:
                continue
            for index in range(subkeys_count):
                try:
                    child_name = winreg.EnumKey(key, index)
                    with winreg.OpenKey(key, child_name) as child:
                        def read(field):
                            try:
                                return str(winreg.QueryValueEx(child, field)[0] or "")
                            except OSError:
                                return ""

                        display = read("DisplayName")
                        if not display:
                            continue
                        programs.append(InstalledProgram(
                            name=display,
                            location=read("InstallLocation"),
                            publisher=read("Publisher"),
                            source="registry",
                        ))
                except OSError:
                    continue
    return programs


def _steam_libraries() -> list[str]:
    if platform.system() != "Windows":
        return []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam_path = str(winreg.QueryValueEx(key, "SteamPath")[0] or "")
    except Exception:
        return []

    if not steam_path:
        return []

    libraries = [steam_path]
    vdf = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
    try:
        with open(vdf, "r", encoding="utf-8", errors="ignore") as file:
            content = file.read()
        for match in _VDF_PATH_RE.findall(content):
            path = match.replace("\\\\", "\\")
            if os.path.isdir(path) and path not in libraries:
                libraries.append(path)
    except OSError:
        pass
    return libraries


def _steam_programs() -> list[InstalledProgram]:
    programs: list[InstalledProgram] = []
    for library in _steam_libraries():
        common = os.path.join(library, "steamapps", "common")
        try:
            for entry in os.scandir(common):
                if entry.is_dir(follow_symlinks=False):
                    programs.append(InstalledProgram(
                        name=entry.name,
                        location=entry.path,
                        publisher="Steam",
                        source="steam",
                    ))
        except OSError:
            continue

        manifests = os.path.join(library, "steamapps")
        for manifest in glob.glob(os.path.join(manifests, "appmanifest_*.acf")):
            try:
                with open(manifest, "r", encoding="utf-8", errors="ignore") as file:
                    content = file.read()
                name_match = _VDF_NAME_RE.search(content)
                if name_match:
                    programs.append(InstalledProgram(
                        name=name_match.group(1),
                        publisher="Steam",
                        source="steam",
                    ))
            except OSError:
                continue
    return programs


def _epic_programs() -> list[InstalledProgram]:
    programdata = os.environ.get("PROGRAMDATA", "")
    if not programdata:
        return []
    manifests_dir = os.path.join(
        programdata, "Epic", "EpicGamesLauncher", "Data", "Manifests",
    )
    programs: list[InstalledProgram] = []
    for manifest in glob.glob(os.path.join(manifests_dir, "*.item")):
        try:
            with open(manifest, "r", encoding="utf-8", errors="ignore") as file:
                data = json.load(file)
        except (OSError, ValueError):
            continue
        name = data.get("DisplayName") or data.get("AppName") or ""
        location = data.get("InstallLocation") or ""
        if name:
            programs.append(InstalledProgram(
                name=str(name),
                location=str(location),
                publisher="Epic Games",
                source="epic",
            ))
    return programs


def _gog_programs() -> list[InstalledProgram]:
    if platform.system() != "Windows":
        return []
    try:
        import winreg
    except ImportError:
        return []

    programs: list[InstalledProgram] = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for path in (r"SOFTWARE\WOW6432Node\GOG.com\Games", r"SOFTWARE\GOG.com\Games"):
            try:
                key = winreg.OpenKey(hive, path)
            except OSError:
                continue
            with key:
                try:
                    count = winreg.QueryInfoKey(key)[0]
                except OSError:
                    continue
                for index in range(count):
                    try:
                        game_key_name = winreg.EnumKey(key, index)
                        with winreg.OpenKey(key, game_key_name) as game:
                            def read(field):
                                try:
                                    return str(winreg.QueryValueEx(game, field)[0] or "")
                                except OSError:
                                    return ""

                            name = read("gameName")
                            if name:
                                programs.append(InstalledProgram(
                                    name=name,
                                    location=read("path"),
                                    publisher="GOG",
                                    source="gog",
                                ))
                    except OSError:
                        continue
    return programs


def _start_menu_programs() -> list[InstalledProgram]:
    if platform.system() != "Windows":
        return []
    roots = []
    programdata = os.environ.get("PROGRAMDATA", "")
    roaming = os.environ.get("APPDATA", "")
    if programdata:
        roots.append(os.path.join(programdata, "Microsoft", "Windows", "Start Menu", "Programs"))
    if roaming:
        roots.append(os.path.join(roaming, "Microsoft", "Windows", "Start Menu", "Programs"))

    programs: list[InstalledProgram] = []
    for root in roots:
        for shortcut in glob.glob(os.path.join(root, "**", "*.lnk"), recursive=True):
            name = os.path.splitext(os.path.basename(shortcut))[0]
            programs.append(InstalledProgram(name=name, source="start_menu"))
    return programs


def _drive_program_folders() -> list[InstalledProgram]:
    """Сканирует каталоги программ на всех локальных дисках.

    Это ловит портативные игры/приложения и установки, которых нет в реестре.
    """
    if platform.system() != "Windows":
        return []
    try:
        import psutil
    except ImportError:
        return []

    candidate_dirs: list[str] = []
    try:
        partitions = psutil.disk_partitions(all=False)
    except Exception:
        return []

    subdirs = (
        "Program Files",
        "Program Files (x86)",
        "Games",
        os.path.join("SteamLibrary", "steamapps", "common"),
        os.path.join("Steam", "steamapps", "common"),
        "Epic Games",
        "GOG Games",
    )
    for partition in partitions:
        if "cdrom" in (partition.opts or "") or not partition.fstype:
            continue
        for sub in subdirs:
            path = os.path.join(partition.mountpoint, sub)
            if os.path.isdir(path):
                candidate_dirs.append(path)

    programs: list[InstalledProgram] = []
    for root in candidate_dirs:
        try:
            for entry in os.scandir(root):
                if entry.is_dir(follow_symlinks=False):
                    programs.append(InstalledProgram(
                        name=entry.name,
                        location=entry.path,
                        source="program_files",
                    ))
        except OSError:
            continue
    return programs


def collect_installed_programs() -> list[InstalledProgram]:
    """Собирает установленные программы из всех доступных источников."""
    if platform.system() != "Windows":
        return []

    collected: list[InstalledProgram] = []
    for collector in (
        _registry_programs,
        _steam_programs,
        _epic_programs,
        _gog_programs,
        _start_menu_programs,
        _drive_program_folders,
    ):
        try:
            collected.extend(collector())
        except Exception:
            continue
    return collected
