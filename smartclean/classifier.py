"""Сопоставление каталогов с установленными программами.

Используется для поиска «сиротских» папок: остатков от удалённых игр
и приложений (сохранения, конфиги, кэш).
"""

from __future__ import annotations

import re

from .installed import InstalledProgram

# Папки, которые точно не являются остатками удалённых программ.
SYSTEM_FOLDER_NAMES = {
    "microsoft", "windows", "windowsapps", "packages", "programs", "temp",
    "temporary", "intel", "nvidia", "amd", "realtek", "common files",
    "desktop", "documents", "downloads", "pictures", "music", "videos",
    "saved games", "start menu", "google", "mozilla", "adobe", "steam",
    "epic", "epicgames", "gog", "gogcom", "battle.net", "ubisoft",
    "origin", "ea games", "electronic arts", "discord", "slack", "teams",
    "zoom", "skype", "python", "node", "npm", "pip", "git", "docker",
    "jetbrains", "vscode", "visual studio", "dotnet", "nuget",
    "crashdumps", "d3dscache", "nvidia corporation",
    "connecteddevicesplatform", "comms", "publishers", "virtualstore",
    "history", "microsoft corporation", "microsoft edge", "microsoft office",
    "onedrive", "internet explorer", "windows defender", "windows mail",
    "windows media player", "microsoft visual studio", "microsoft vs code",
    "microsoft teams", "tempstate", "cache", "caches", "logs", "log",
    "crashreportclient", "packagedcom", "placeholdertilelogofolder",
    "pixelbot", "squirreltemp", "virtualbox", "vmware", "obs-studio",
    "spotify", "telegram desktop", "whatsapp", "viber", "signal",
    "yandex", "opera software", "bravesoftware", "chromium",
    "package cache", "usoshared", "crashpad", "crashreports", "cef",
    "electron", "hp", "dell", "lenovo", "asus", "canon", "epson",
    "logitech", "razer", "corsair", "steelseries", "mcafee", "avast",
    "avira", "kaspersky", "eset", "malwarebytes", "sophos", "oracle",
    "java", "sun", "adobe", "zoom.us", "telegramdesktop", "element",
    "notion", "figma", "postman", "insomnia", "cursor", "windsurf",
    "openvpn", "wireguard", "tailscale", "docker desktop", "wsl",
    "npm-cache", "yarn", "yarn-cache", "pnpm", "uv", "deno", "cargo",
    "rustup", "go-build", "gradle", "maven", "nuget", "programs",
    "tempstate", "d3dscache", "nvidia", "amd", "intel corporation",
    "my games", "my pictures", "my music", "my videos",
    "application data", "local settings", "templates", "sendto", "recent",
    "favorites", "contacts", "links", "searches", "3d objects",
    "my documents", "printers", "network", "drivers", "assembly",
}

# Слишком общие имена — по ним нельзя судить о принадлежности папки.
STOP_TOKENS = {
    "the", "and", "for", "with", "game", "games", "app", "apps", "pro",
    "plus", "version", "edition", "setup", "installer", "update", "launcher",
    "client", "studio", "software", "corporation", "inc", "ltd", "llc",
    "microsoft", "windows", "program", "programs", "data", "local",
    "roaming", "system", "x86", "x64", "win", "win64", "win32",
}

_TOKEN_RE = re.compile(r"[a-z0-9а-я]+")
_CLEAN_RE = re.compile(r"[^a-z0-9а-я]+")


def normalize(text: str) -> str:
    """Приводит имя к нижнему регистру без разделителей."""
    return _CLEAN_RE.sub("", (text or "").lower())


def tokenize(text: str) -> set[str]:
    """Разбивает строку на осмысленные токены (без стоп-слов)."""
    tokens = set(_TOKEN_RE.findall((text or "").lower()))
    return {token for token in tokens if len(token) >= 3 and token not in STOP_TOKENS}


def build_program_index(programs: list[InstalledProgram]) -> tuple[set[str], set[str]]:
    """Возвращает (нормализованные имена, токены) установленных программ."""
    normalized: set[str] = set()
    tokens: set[str] = set()

    for program in programs:
        name_norm = normalize(program.name)
        if len(name_norm) >= 3:
            normalized.add(name_norm)
        tokens.update(tokenize(program.name))

        if program.location:
            base = normalize(os_basename(program.location))
            if len(base) >= 3:
                normalized.add(base)
                tokens.update(tokenize(os_basename(program.location)))

        if program.publisher:
            tokens.update(tokenize(program.publisher))

    return normalized, tokens


def os_basename(path: str) -> str:
    path = (path or "").rstrip("\\/")
    for separator in ("\\", "/"):
        if separator in path:
            path = path.rsplit(separator, 1)[-1]
    return path


def is_system_folder(name: str) -> bool:
    """Системная или служебная папка, которую нельзя считать остатком."""
    lowered = (name or "").strip().lower()
    if not lowered:
        return True
    if lowered.startswith("."):
        return True
    if lowered in SYSTEM_FOLDER_NAMES:
        return True
    if any(
        lowered.startswith(prefix)
        for prefix in ("microsoft.", "windows.", "temp", "cache", "logs")
    ):
        return True
    return False


def match_installed(name: str, normalized: set[str], tokens: set[str]) -> str | None:
    """Пытается сопоставить имя папки с установленной программой.

    Возвращает имя совпавшей программы/токена или None, если совпадений нет.
    """
    candidate = normalize(name)
    if not candidate or len(candidate) < 3:
        return None

    if candidate in normalized:
        return candidate

    candidate_tokens = tokenize(name)
    for token in candidate_tokens:
        if token in tokens:
            return token

    # Частичное вхождение: "Cyberpunk2077Save" vs "cyberpunk2077"
    for installed in normalized:
        if len(installed) >= 4 and (
            installed in candidate or candidate in installed
        ):
            return installed

    for token in tokens:
        if len(token) >= 4 and token in candidate:
            return token

    return None
