@echo off
REM Build reado.exe with PyInstaller.
REM Prereq:  pip install pywebview pyinstaller
setlocal
cd /d "%~dp0"

REM ReadO must run offline, so Monaco/marked/fonts are bundled from vendor\.
REM They are not committed - fetch them before the first build.
if not exist vendor\monaco\vs\loader.js (
    echo === vendor assets missing - fetching ===
    python fetch-vendor.py
    if not exist vendor\monaco\vs\loader.js (
        echo [error] fetch-vendor.py failed ^- cannot build an offline exe.
        exit /b 1
    )
)

if not exist icon.ico (
    echo [warn] icon.ico not found ^- exe will use default icon
    set ICON_OPT=
) else (
    set ICON_OPT=--icon icon.ico
)

echo === cleaning previous build ===
if exist build rmdir /S /Q build
if exist dist  rmdir /S /Q dist
if exist reado.spec del reado.spec

echo === building reado.exe ===
pyinstaller --noconfirm --onefile --windowed --name reado ^
    --add-data "source.html;." ^
    --add-data "vendor;vendor" ^
    --hidden-import server ^
    --paths . ^
    %ICON_OPT% ^
    reado.py

if not exist dist\reado.exe (
    echo [error] build failed.
    exit /b 1
)

echo.
echo === build done ===
echo  output: %~dp0dist\reado.exe
echo  size:
dir dist\reado.exe | findstr reado.exe
echo.
echo Run dist\reado.exe to launch the desktop app.
