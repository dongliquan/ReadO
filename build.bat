@echo off
REM Build reado.exe with PyInstaller.
REM Prereq:  pip install pywebview pyinstaller
REM Usage:   build.bat              -> dist\reado.exe
REM          build.bat dist-next    -> dist-next\reado.exe (dist\ is left alone, e.g. while it runs)
setlocal
cd /d "%~dp0"
set "OUT=%~1"
if "%OUT%"=="" set "OUT=dist"
set "WORK=build"
if not "%OUT%"=="dist" set "WORK=build-%OUT%"

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

REM ripgrep powers Find in Files / Go to Definition. Without it the app still
REM works but falls back to the much slower Python search.
if not exist vendor\rg\rg.exe (
    echo === ripgrep missing - fetching ===
    python fetch-vendor.py
    if not exist vendor\rg\rg.exe echo [warn] ripgrep not bundled ^- search uses the slower Python fallback
)

REM Universal Ctags powers the symbol index (go to definition, Ctrl+T, outline).
REM Without it those fall back to search + declaration patterns.
if not exist vendor\ctags\ctags.exe (
    echo === ctags missing - fetching ===
    python fetch-vendor.py
    if not exist vendor\ctags\ctags.exe echo [warn] ctags not bundled ^- symbol index disabled, regex fallback only
)

if not exist icon.ico (
    echo [warn] icon.ico not found ^- exe will use default icon
    set ICON_OPT=
) else (
    set ICON_OPT=--icon "%~dp0icon.ico"
)

echo === cleaning previous build (%OUT%) ===
if exist "%WORK%" rmdir /S /Q "%WORK%"
if exist "%OUT%"  rmdir /S /Q "%OUT%"
if exist "%OUT%" (
    echo [error] %OUT%\ is in use ^(is that reado.exe running?^) - close it or build elsewhere: build.bat dist-next
    exit /b 1
)
if "%OUT%"=="dist" if exist reado.spec del reado.spec

echo === building %OUT%\reado.exe ===
set "SPEC_OPT="
if not "%OUT%"=="dist" set "SPEC_OPT=--specpath %WORK%"
pyinstaller --noconfirm --onefile --windowed --name reado ^
    --distpath "%OUT%" --workpath "%WORK%" %SPEC_OPT% ^
    --add-data "%~dp0source.html;." ^
    --add-data "%~dp0git.js;." ^
    --add-data "%~dp0git.css;." ^
    --add-data "%~dp0diffwin.html;." ^
    --add-data "%~dp0diffwin.js;." ^
    --hidden-import gitview ^
    --add-data "%~dp0vendor;vendor" ^
    --add-data "%~dp0icon.ico;." ^
    --hidden-import server ^
    --paths "%~dp0." ^
    %ICON_OPT% ^
    reado.py

if not exist "%OUT%\reado.exe" (
    echo [error] build failed.
    exit /b 1
)

echo.
echo === build done ===
echo  output: %~dp0%OUT%\reado.exe
echo  size:
dir "%OUT%\reado.exe" | findstr reado.exe
echo.
echo Run %OUT%\reado.exe to launch the desktop app.
