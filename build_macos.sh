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

# Bundle the native encoder for this Mac architecture.
case "$(uname -m)" in
  arm64) TODDS_ARCH=arm; TODDS_SHA=0fc7354dff9e98c255eea64e1e6f55add0a9c39ec8f79fe26aec61032cbfa908 ;;
  x86_64) TODDS_ARCH=i386; TODDS_SHA=a2c53d03e9b8c4d226f2330c30334b613c198448a66b42f3fae6afe159fe8f8e ;;
  *) echo "Unsupported Mac architecture" >&2; exit 1 ;;
esac
TODDS_ZIP="$BUILD_ROOT/todds-macos.zip"
curl --fail --location --retry 3 "https://github.com/todds-encoder/todds/releases/download/0.4.1/todds_Darwin_${TODDS_ARCH}_0.4.1.zip" -o "$TODDS_ZIP"
echo "$TODDS_SHA  $TODDS_ZIP" | shasum -a 256 -c -
unzip -o "$TODDS_ZIP" -d "$APP_DIR/todds"
chmod +x "$APP_DIR/todds/todds"

"$VENV/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --windowed \
  --name "Progression Launcher" \
  --add-data "$APP_DIR/progression_logo.png:." \
  --add-data "$APP_DIR/collection_cache.json:." \
  --add-data "$APP_DIR/todds:todds" \
  --distpath "$DIST" \
  --workpath "$BUILD_ROOT/pyinstaller-work" \
  --specpath "$BUILD_ROOT" \
  progressor.py

echo
echo "Built: $DIST/Progression Launcher.app"
