#!/usr/bin/env bash
# Mimick installer. Sets up everything Mimick needs and adds it to your
# applications menu. Safe to run more than once.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/.venv"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
BIN="$HOME/.local/bin"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
info() { printf '  \033[36m→\033[0m %s\n' "$1"; }
die()  { printf '\n\033[31m✗ %s\033[0m\n\n' "$1" >&2; exit 1; }

echo
bold "Installing Mimick"
echo "  Natural-sounding read-aloud for PDFs."
echo

# --- 1. system packages ------------------------------------------------------
bold "Step 1 of 4  ·  Checking system packages"

NEEDED=()
need_pkg() { dpkg -s "$1" >/dev/null 2>&1 || NEEDED+=("$1"); }

need_pkg python3-venv
need_pkg ffmpeg
need_pkg libportaudio2       # sound output
need_pkg libxcb-cursor0      # required by Qt 6 on Ubuntu
need_pkg tesseract-ocr-eng   # English data for recognising the text in scans

command -v python3 >/dev/null || die "Python 3 is not installed. Run: sudo apt install python3"

if [ ${#NEEDED[@]} -gt 0 ]; then
  info "These system packages are needed: ${NEEDED[*]}"
  info "You will be asked for your password."
  echo
  if command -v sudo >/dev/null; then
    sudo apt-get update -qq || true
    sudo apt-get install -y "${NEEDED[@]}" || die "Could not install: ${NEEDED[*]}
Try running this yourself, then run the installer again:
  sudo apt install ${NEEDED[*]}"
  else
    die "Please install these first:  su -c 'apt install ${NEEDED[*]}'"
  fi
  ok "System packages installed"
else
  ok "All system packages already present"
fi

# --- 2. python environment ---------------------------------------------------
echo
bold "Step 2 of 4  ·  Setting up Mimick's private environment"
info "Nothing outside this folder is changed."

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" || die "Could not create the Python environment."
  ok "Environment created"
else
  ok "Environment already exists"
fi

"$VENV/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true

# "python -m mimick" otherwise finds the package through the *working
# directory* -- the project folder in a terminal, but your home folder when the
# applications menu launches it, so the menu entry died instantly with "No
# module named mimick" and no window. A .pth file in the environment names this
# folder, which fixes every way of starting Mimick at once, and leaves a
# relative filename argument resolving against wherever you actually are.
# install.ps1 does the same on Windows.
SITE="$("$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
printf '%s\n' "$HERE" > "$SITE/mimick.pth" || die "Could not tell the environment where Mimick lives."
ok "Environment knows where Mimick lives"

echo
bold "Step 3 of 4  ·  Downloading Mimick's components"
info "This can take a few minutes the first time."
if ! "$VENV/bin/python" -m pip install --quiet -r "$HERE/requirements.txt"; then
  die "Could not download the components. Check your internet connection and try again."
fi
ok "Components installed"

# --- 3. launcher -------------------------------------------------------------
echo
bold "Step 4 of 4  ·  Adding Mimick to your applications"

mkdir -p "$APPS" "$ICONS" "$BIN"
cp -f "$HERE/assets/mimick.svg" "$ICONS/mimick.svg"

# No PYTHONPATH and no cd: the .pth file written in step 2 is what lets this
# run from anywhere.
cat > "$BIN/mimick" <<LAUNCH
#!/usr/bin/env bash
# This file holds the path Mimick was installed from. Renaming or moving that
# folder breaks it, and the applications menu runs this with Terminal=false --
# so the error goes nowhere and Mimick simply does not open, with nothing said.
# That happened on 17 September, when the repository folder was renamed. Check
# first, and say it somewhere a person will actually see.
if [ ! -x "$VENV/bin/python" ] || [ ! -f "$HERE/mimick/__main__.py" ]; then
  TROUBLE="Mimick cannot start, because its folder has been moved or renamed.

It expected to find it here:
  $HERE

To fix it, open Mimick's folder in a terminal and run:
  ./install.sh"
  printf '%s\n' "\$TROUBLE" >&2
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --no-wrap --title="Mimick" --text="\$TROUBLE" 2>/dev/null
  elif command -v kdialog >/dev/null 2>&1; then
    kdialog --title "Mimick" --error "\$TROUBLE" 2>/dev/null
  elif command -v notify-send >/dev/null 2>&1; then
    notify-send -u critical "Mimick cannot start" "\$TROUBLE" 2>/dev/null
  fi
  exit 1
fi
exec "$VENV/bin/python" -m mimick "\$@"
LAUNCH
chmod +x "$BIN/mimick"

cat > "$APPS/mimick.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Mimick
GenericName=PDF Read Aloud
Comment=Listen to documents in natural, human-sounding voices
Exec=$BIN/mimick %f
Icon=mimick
Terminal=false
Categories=Office;Viewer;
MimeType=application/pdf;text/plain;application/vnd.openxmlformats-officedocument.wordprocessingml.document;application/vnd.oasis.opendocument.text;application/epub+zip;
Keywords=pdf;docx;odt;epub;read;aloud;speech;tts;audiobook;
StartupNotify=true
StartupWMClass=mimick
DESKTOP

update-desktop-database "$APPS" >/dev/null 2>&1 || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
ok "Added to your applications menu"

# --- done --------------------------------------------------------------------
echo
bold "Mimick is ready."
echo
echo "  Open it from your applications menu — search for \"Mimick\"."
echo "  Or right-click any PDF and choose  Open With → Mimick."
echo
if ! printf '%s' "$PATH" | grep -q "$BIN"; then
  echo "  (To launch it from a terminal, add this to your ~/.bashrc:)"
  echo "     export PATH=\"\$HOME/.local/bin:\$PATH\""
  echo
fi
