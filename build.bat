@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"
title DiskViever — сборка exe

REM ==== Настройки ====
set APP_NAME=DiskViever
set SCRIPT_NAME=main.py
set VENV_DIR=.venv
set DIST_DIR=dist
set BUILD_DIR=build
REM Иконка необязательна: если icons\icon-512.png нет — соберём без неё.
set ICON_SRC=icons\icon-512.png
set ICON_FILE=%BUILD_DIR%\app.ico
REM ====================

echo [1/6] Поиск Python 3.11...
set "SYS_PYTHON="
for %%p in ("%ProgramFiles%\Python311\python.exe" "%LocalAppData%\Programs\Python\Python311\python.exe") do (
    if not defined SYS_PYTHON if exist "%%p" set "SYS_PYTHON=%%p"
)
if not defined SYS_PYTHON (
    where python >nul 2>nul
    if not errorlevel 1 set "SYS_PYTHON=python"
)
if not defined SYS_PYTHON (
    echo [ОШИБКА] Python 3.11 не найден. Установите его и запустите build.bat снова.
    echo           https://www.python.org/downloads/release/python-3110/
    pause
    exit /b 1
)
"%SYS_PYTHON%" --version
echo.

echo [2/6] Подготовка виртуального окружения "%VENV_DIR%"...
if not exist "%VENV_DIR%\Scripts\python.exe" (
    "%SYS_PYTHON%" -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось создать venv.
        pause
        exit /b 1
    )
) else (
    echo Окружение уже существует, используем его.
)
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
echo.

echo [3/6] Установка зависимостей...
if not exist "requirements.txt" (
    echo [ОШИБКА] Файл requirements.txt не найден рядом с build.bat.
    pause
    exit /b 1
)
"%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel -q
if errorlevel 1 (
    echo [ОШИБКА] Не удалось обновить pip.
    pause
    exit /b 1
)
"%PYTHON_EXE%" -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить зависимости.
    pause
    exit /b 1
)
echo.

echo [4/6] Установка PyInstaller...
"%PYTHON_EXE%" -m pip install --upgrade pyinstaller -q
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить PyInstaller.
    pause
    exit /b 1
)
echo.

echo [5/6] Подготовка иконки...
if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"
set "ICON_ARG="
if exist "%ICON_SRC%" (
    REM Pillow нужен только для конвертации png в ico, в само exe он не попадает.
    "%PYTHON_EXE%" -m pip install pillow -q
    "%PYTHON_EXE%" -c "from PIL import Image; Image.open('%ICON_SRC:\=/%').save('%ICON_FILE:\=/%', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])" >nul 2>&1
    if exist "%ICON_FILE%" (
        set "ICON_ARG=--icon "%CD%\%ICON_FILE%""
        echo Иконка: %ICON_FILE%
    ) else (
        echo Не удалось конвертировать %ICON_SRC% в ico.
    )
)
if not defined ICON_ARG echo Иконка не создана — собираем без неё.
echo.

echo [6/6] Сборка %APP_NAME%.exe (это может занять несколько минут)...
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"

REM theme.py, ui_kit.py и пакет smartclean\ — обычные Python-модули,
REM PyInstaller подхватывает их через импорт в main.py.
REM send2trash и winreg импортируются лениво внутри функций (smartclean\fsutil.py,
REM smartclean\installed.py) — без явного указания они потеряются и корзина
REM перестанет работать. matplotlib тянет mpl-data и бэкенд TkAgg.
REM Если exe молча не запускается — временно замените --windowed на --console,
REM чтобы увидеть traceback.
"%PYTHON_EXE%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "%APP_NAME%" ^
    !ICON_ARG! ^
    --hidden-import matplotlib.backends.backend_tkagg ^
    --collect-data matplotlib ^
    --hidden-import tkinter ^
    --hidden-import tkinter.ttk ^
    --hidden-import tkinter.filedialog ^
    --hidden-import tkinter.messagebox ^
    --collect-submodules send2trash ^
    --hidden-import winreg ^
    --collect-submodules smartclean ^
    --distpath "%CD%\%DIST_DIR%" ^
    --workpath "%CD%\%BUILD_DIR%" ^
    --specpath "%CD%\%BUILD_DIR%" ^
    "%CD%\%SCRIPT_NAME%"

if errorlevel 1 (
    echo.
    echo [ОШИБКА] Сборка не удалась. Смотрите вывод выше.
    pause
    exit /b 1
)

if not exist "%DIST_DIR%\%APP_NAME%.exe" (
    echo.
    echo [ОШИБКА] exe не найден в %DIST_DIR%\%APP_NAME%.exe
    pause
    exit /b 1
)

echo.
echo ==================================================
echo  Готово! Файл: %DIST_DIR%\%APP_NAME%.exe
echo.
echo  Всё приложение (включая matplotlib и smartclean\)
echo  упаковано в один exe, никаких внешних файлов не нужно.
echo  Журнал очистки: %USERPROFILE%\.diskvieuver\cleanup_log.jsonl
if defined ICON_ARG echo  Иконка встроена: %ICON_FILE%
echo ==================================================
echo.

if exist "%DIST_DIR%" explorer "%DIST_DIR%"

pause
endlocal