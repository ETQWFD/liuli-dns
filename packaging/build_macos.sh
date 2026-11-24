#!/usr/bin/env bash
# Build LiuliDNS for macOS on a real macOS host (PyInstaller cannot cross-compile).
# Optional signing/notarization identities are supplied by the developer:
#   CODESIGN_IDENTITY="Developer ID Application: ..."
#   NOTARY_PROFILE="notarytool keychain profile name"
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build-tools"
REL="$ROOT/release"
VENV="${VENV:-$ROOT/.venv}"
PY="$VENV/bin/python"
VERSION="${VERSION:-0.2.1}"
mkdir -p "$BUILD/tunnel-dist" "$REL"

cd "$ROOT/tunnel"
CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build -trimpath -ldflags='-s -w' -o "$BUILD/tunnel-dist/liuli-tunnel-arm64" .
CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 go build -trimpath -ldflags='-s -w' -o "$BUILD/tunnel-dist/liuli-tunnel-amd64" .
lipo -create -output "$BUILD/tunnel-dist/liuli-tunnel" \
  "$BUILD/tunnel-dist/liuli-tunnel-arm64" "$BUILD/tunnel-dist/liuli-tunnel-amd64"
chmod +x "$BUILD/tunnel-dist/liuli-tunnel"

CF="$BUILD/cloudflared-darwin-universal"
if [ ! -x "$CF" ]; then
  for arch in arm64 amd64; do
    tgz="$BUILD/cloudflared-darwin-$arch.tgz"
    [ -f "$tgz" ] || curl -fL --retry 3 -o "$tgz" \
      "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-$arch.tgz"
    mkdir -p "$BUILD/cf-$arch"
    tar -xzf "$tgz" -C "$BUILD/cf-$arch"
  done
  lipo -create -output "$CF" "$BUILD/cf-arm64/cloudflared" "$BUILD/cf-amd64/cloudflared"
  chmod +x "$CF"
fi

"$PY" -m PyInstaller --noconfirm --clean --onefile --console --name liuli-dns-server \
  --paths "$ROOT" --distpath "$BUILD/server-dist-macos" --workpath "$BUILD/pyi-server-macos" \
  --specpath "$BUILD/pyi-server-macos" \
  --add-data "$ROOT/backend/app/admin/templates:backend/app/admin/templates" \
  --hidden-import backend.app.main --hidden-import backend.app.admin \
  --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.lifespan.on \
  "$ROOT/server_entry.py"

"$PY" -m PyInstaller --noconfirm --clean --windowed --onedir --name LiuliDNS \
  --osx-bundle-identifier cc.asnia.liulidns --paths "$ROOT" \
  --distpath "$BUILD/dist-macos" --workpath "$BUILD/pyi-macos" --specpath "$BUILD/pyi-macos" \
  --add-data "$ROOT/client/app/qml:client/app/qml" \
  --add-data "$ROOT/client/resources:client/resources" \
  --hidden-import PySide6.QtCore --hidden-import PySide6.QtGui --hidden-import PySide6.QtQml \
  --hidden-import PySide6.QtQuick --hidden-import PySide6.QtQuickControls2 \
  --hidden-import PySide6.QtNetwork --hidden-import PySide6.QtSvg --hidden-import PySide6.QtWidgets \
  --exclude-module tkinter --exclude-module PySide6.QtWebEngineCore \
  "$ROOT/packaging/entry.py"

APP="$BUILD/dist-macos/LiuliDNS.app"
cp "$BUILD/server-dist-macos/liuli-dns-server" "$APP/Contents/MacOS/liuli-dns-server"
cp "$BUILD/tunnel-dist/liuli-tunnel" "$APP/Contents/MacOS/liuli-tunnel"
cp "$CF" "$APP/Contents/MacOS/cloudflared"
chmod +x "$APP/Contents/MacOS/"*

if [ -n "${CODESIGN_IDENTITY:-}" ]; then
  codesign --force --deep --options runtime --timestamp --sign "$CODESIGN_IDENTITY" "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP"
else
  echo "WARN: CODESIGN_IDENTITY not set; app is unsigned and Gatekeeper will warn." >&2
fi

DMG="$REL/LiuliDNS-$VERSION-macos-universal.dmg"
rm -f "$DMG"
STAGE="$BUILD/dmg-stage"
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "LiuliDNS" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
if [ -n "${CODESIGN_IDENTITY:-}" ]; then
  codesign --force --sign "$CODESIGN_IDENTITY" "$DMG"
fi
if [ -n "${NOTARY_PROFILE:-}" ]; then
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
fi
shasum -a 256 "$DMG"
echo "DMG: $DMG"
