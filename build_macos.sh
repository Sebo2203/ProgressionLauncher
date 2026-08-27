#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

BUILD_ROOT=".build/ferny_progressor_build_macos"
VENV="$BUILD_ROOT/.venv"
DIST="dist"
APP_DIR="$(pwd)"

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install --upgrade pip pyinstaller

mkdir -p "$DIST"

"$VENV/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --windowed \
  --name "Progression Launcher" \
  --add-data "$APP_DIR/progression_logo.png:." \
  --add-data "$APP_DIR/collection_cache.json:." \
  --distpath "$DIST" \
  --workpath "$BUILD_ROOT/pyinstaller-work" \
  --specpath "$BUILD_ROOT" \
  progressor.py

echo
echo "Built: $DIST/Progression Launcher.app"
