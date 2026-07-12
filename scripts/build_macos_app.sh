#!/bin/zsh
set -euo pipefail

PROJECT_DIR="${0:A:h:h}"
APP_DIR="${PROJECT_DIR}/dist/StreamDock.app"
CONTENTS="${APP_DIR}/Contents"
MACOS="${CONTENTS}/MacOS"

rm -rf "$APP_DIR"
mkdir -p "$MACOS"

cat > "${CONTENTS}/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>StreamDock</string>
  <key>CFBundleDisplayName</key><string>StreamDock</string>
  <key>CFBundleIdentifier</key><string>local.streamdock.app</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>StreamDock</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
</dict></plist>
PLIST

cat > "${MACOS}/StreamDock" <<LAUNCHER
#!/bin/zsh
exec "${PROJECT_DIR}/start_streamdock.command"
LAUNCHER

chmod +x "${MACOS}/StreamDock"
echo "已生成：${APP_DIR}"
