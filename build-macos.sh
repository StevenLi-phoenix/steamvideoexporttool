#!/usr/bin/env bash
# Build for the current Mac architecture. FFmpeg is discovered at runtime.
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != Darwin ]]; then
    echo "Run this script on macOS." >&2
    exit 1
fi
unset UV_MANAGED_PYTHON
if [[ ! -d .venv ]]; then
    uv venv
fi
source .venv/bin/activate
uv sync --group build
macos_dist_dir="${MACOS_DIST_DIR:-$PWD/dist-macos}"
echo "Building SteamQuickExport.app for $(uname -m)..."
uv run python -m PyInstaller --clean --noconfirm --windowed --onedir \
    --name SteamQuickExport \
    --osx-bundle-identifier com.stevenli.steamquickexport \
    --add-data "assets/app-icon.ico:assets" \
    --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQml \
    --exclude-module PySide6.QtPdf --exclude-module PySide6.QtNetwork \
    --exclude-module PySide6.QtSvg --exclude-module PySide6.QtOpenGL \
    --distpath "$macos_dist_dir" --workpath build-simple/macos \
    steam_quick_export.py
# Cloud-synced working folders can attach Finder metadata during collection,
# which makes codesign reject the otherwise valid generated bundle.
xattr -cr "$macos_dist_dir/SteamQuickExport.app"
codesign --force --deep --sign - "$macos_dist_dir/SteamQuickExport.app"
codesign --verify --deep --strict "$macos_dist_dir/SteamQuickExport.app"
echo "Built $macos_dist_dir/SteamQuickExport.app (requires FFmpeg; brew install ffmpeg-full)."
