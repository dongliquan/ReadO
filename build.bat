@echo off
REM Build reado.exe with PyInstaller.
REM Prereq:  pip install pywebview pyinstaller
setlocal
cd /d "%~dp0"

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
