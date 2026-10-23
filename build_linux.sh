#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
APP_DIR="$(pwd)"
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  echo 'Build on an x86_64 Linux machine.' >&2
  exit 1
fi

BUILD_ROOT=.build/launcher-linux
VENV="$BUILD_ROOT/.venv"
if [[ ! -x "$VENV/bin/python" ]]; then python3 -m venv "$VENV"; fi
"$VENV/bin/python" -m pip install --upgrade pip pyinstaller
"$VENV/bin/python" -c 'import tkinter'
mkdir -p "$BUILD_ROOT" dist
TODDS_ZIP="$BUILD_ROOT/todds-linux.zip"
curl --fail --location --retry 3 'https://github.com/todds-encoder/todds/releases/download/0.4.1/todds_Linux_x86_64_0.4.1.zip' -o "$TODDS_ZIP"
echo "012787f95bca91d00aa5baaad87ace528fa9d39a478d3377107812cf376f1b11  $TODDS_ZIP" | sha256sum -c -
unzip -o "$TODDS_ZIP" -d todds
chmod +x todds/todds

"$VENV/bin/python" -m PyInstaller --noconfirm --clean --onedir \
  --name ProgressionLauncher \
  --add-data "$APP_DIR/progression_logo.png:." \
  --add-data "$APP_DIR/collection_cache.json:." \
  --add-data "$APP_DIR/todds:todds" \
  --distpath dist --workpath "$BUILD_ROOT/work" --specpath "$BUILD_ROOT" \
  "$(pwd)/progressor.py"

VERSION=$("$VENV/bin/python" -c 'import progressor; print(progressor.APP_VERSION)')
ARCHIVE="ProgressionLauncher-Linux-v${VERSION}-x86_64-test.tar.gz"
tar -czf "dist/$ARCHIVE" -C dist ProgressionLauncher
(cd dist && sha256sum "$ARCHIVE" > "$ARCHIVE.sha256")
echo "Built: dist/$ARCHIVE"
