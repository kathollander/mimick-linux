#!/usr/bin/env bash
# Removes Mimick's launcher, environment and cached voices.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo
echo "This removes Mimick's launcher, its private environment, and any"
echo "downloaded offline voices. Your PDFs are not touched."
read -r -p "Continue? [y/N] " reply
[[ "$reply" =~ ^[Yy]$ ]] || { echo "Cancelled."; exit 0; }

rm -f  "$HOME/.local/share/applications/mimick.desktop"
rm -f  "$HOME/.local/share/icons/hicolor/scalable/apps/mimick.svg"
rm -f  "$HOME/.local/bin/mimick"
rm -rf "$HERE/.venv"
rm -rf "$HOME/.cache/mimick"
update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true

echo "Mimick removed. Your settings are still in ~/.config/mimick"
echo "(delete that folder too if you want a clean slate)."
