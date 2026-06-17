#!/usr/bin/env bash
# Package the Aexy executable into a proper .app bundle (with a bundle id, so
# UNUserNotificationCenter + Keychain behave) and ad-hoc code-sign it so it runs
# + notifies locally. For distribution, replace the ad-hoc identity with a
# Developer ID and notarize.
set -euo pipefail
cd "$(dirname "$0")/.."

CONFIG="${1:-release}"
APP="Aexy.app"

echo "→ swift build -c $CONFIG"
swift build -c "$CONFIG"
BIN=".build/$CONFIG/Aexy"
[ -f "$BIN" ] || { echo "build output not found: $BIN" >&2; exit 1; }

echo "→ assembling $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/Aexy"
cp Packaging/Info.plist "$APP/Contents/Info.plist"

echo "→ ad-hoc code-signing"
codesign --force --deep --sign - "$APP"

echo "✓ Built $APP  (open with: open $APP)"
