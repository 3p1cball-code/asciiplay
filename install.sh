#!/usr/bin/env bash
# Installs the asciiplay icon and desktop entry for the current user, and (unless
# --no-default is passed) makes asciiplay the default opener for common video/audio
# types. Everything here is per-user (~/.local/share/...) and easily reversible - see
# the "Desktop integration" section of README.md.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$DIR/asciiplay.py"
SET_DEFAULT=1
[[ "${1:-}" == "--no-default" ]] && SET_DEFAULT=0

if [[ ! -f "$APP" ]]; then
    echo "error: $APP not found" >&2
    exit 1
fi
chmod +x "$APP"

echo "Installing icon..."
SCALABLE="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$SCALABLE"
cp "$DIR/asciiplay.svg" "$SCALABLE/asciiplay.svg"
for size in 16 32 48 64 128 256 512; do
    d="$HOME/.local/share/icons/hicolor/${size}x${size}/apps"
    mkdir -p "$d"
    cp "$DIR/icons/asciiplay-${size}.png" "$d/asciiplay.png"
done

echo "Installing desktop entry..."
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
sed "s#__EXEC__#$APP#" "$DIR/asciiplay.desktop.in" > "$APPS_DIR/asciiplay.desktop"
desktop-file-validate "$APPS_DIR/asciiplay.desktop" && echo "  desktop entry is valid"

echo "Refreshing desktop/icon caches..."
update-desktop-database "$APPS_DIR" 2>/dev/null || true
gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
kbuildsycoca6 2>/dev/null || kbuildsycoca5 2>/dev/null || true

if [[ "$SET_DEFAULT" == "1" ]]; then
    echo "Setting asciiplay as the default opener for video/audio files..."
    MIMES=$(grep '^MimeType=' "$DIR/asciiplay.desktop.in" | cut -d= -f2- | tr ';' ' ')
    xdg-mime default asciiplay.desktop $MIMES
    echo "  done. Run '$0 --no-default' to install without changing defaults,"
    echo "  or 'xdg-mime default <old-app>.desktop <mimetype>' to switch a type back."
else
    echo "Skipped setting default associations (--no-default). asciiplay is still"
    echo "available in each file's right-click -> Open With menu."
fi

echo
echo "Done. asciiplay should now appear in your application launcher with its icon,"
echo "and double-clicking a video/audio file should open it (may need to log out of"
echo "the desktop session once for the icon/launcher entry to show up everywhere)."
