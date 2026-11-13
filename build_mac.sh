#!/usr/bin/env bash
# Build ReadO.app and ReadO-mac-<arch>.dmg with PyInstaller (macOS).
# Prereq:  pip install -r requirements.txt   (pywebview, pyinstaller, Pillow)
# Usage:   ./build_mac.sh          -> dist/ReadO.app and dist/ReadO-mac-$(uname -m).dmg
set -euo pipefail
cd "$(dirname "$0")"

# ReadO runs offline: Monaco / marked / fonts / ripgrep are bundled from vendor/ (not committed)
if [ ! -f vendor/monaco/vs/loader.js ] || [ ! -f vendor/rg/rg ]; then
  echo "=== vendor assets missing - fetching ==="
  python3 fetch-vendor.py
fi

# icon.icns from icon.ico (Pillow draws the iconset, iconutil packs it)
echo "=== icon ==="
rm -rf build-icon && mkdir -p build-icon/ReadO.iconset
python3 - <<'PY'
from PIL import Image
ico = Image.open("icon.ico")
sizes = sorted(ico.info.get("sizes") or {ico.size})
ico.size = sizes[-1]
im = ico.convert("RGBA")
for n in (16, 32, 128, 256, 512):
    for scale in (1, 2):
        name = f"icon_{n}x{n}" + ("@2x" if scale == 2 else "") + ".png"
        im.resize((n * scale, n * scale), Image.LANCZOS).save("build-icon/ReadO.iconset/" + name)
PY
iconutil -c icns build-icon/ReadO.iconset -o build-icon/icon.icns

echo "=== building dist/ReadO.app ==="
rm -rf build dist/ReadO dist/ReadO.app
python3 -m PyInstaller --noconfirm --windowed --name ReadO \
  --distpath dist --workpath build \
  --icon build-icon/icon.icns \
  --osx-bundle-identifier app.reado.desktop \
  --add-data "source.html:." \
  --add-data "ui:ui" \
  --add-data "git.js:." \
  --add-data "git.css:." \
  --add-data "diffwin.html:." \
  --add-data "diffwin.js:." \
  --add-data "vendor:vendor" \
  --add-data "icon.ico:." \
  --hidden-import gitview --hidden-import nowmi --hidden-import startguard \
  --hidden-import server \
  --hidden-import srv_search --hidden-import srv_goto --hidden-import srv_links \
  --hidden-import srv_tags --hidden-import srv_fileops \
  --paths . \
  reado.py

[ -d dist/ReadO.app ] || { echo "[error] build failed"; exit 1; }
chmod +x dist/ReadO.app/Contents/Resources/vendor/rg/rg 2>/dev/null || true

echo "=== dmg ==="
DMG="dist/ReadO-mac-$(uname -m).dmg"
rm -f "$DMG"
STAGE=$(mktemp -d)
cp -R dist/ReadO.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname ReadO -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"
echo "done: $DMG"
