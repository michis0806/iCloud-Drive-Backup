#!/usr/bin/env bash
# Update-Script: holt die neueste Version vom Repository und
# aktualisiert das venv mit den aktuellen Abhängigkeiten.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

echo "=== iCloud Drive Backup – Update ==="
echo ""

# --- Git Pull ---
cd "$SCRIPT_DIR"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

if [ -z "$CURRENT_BRANCH" ]; then
    echo "Fehler: Kein Git-Repository gefunden."
    exit 1
fi

echo "Aktualisiere Repository (Branch: $CURRENT_BRANCH) ..."
git pull origin "$CURRENT_BRANCH"
echo ""

# --- venv aktualisieren ---
if [ ! -d "$VENV_DIR" ]; then
    echo "Erstelle virtuelle Umgebung in $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
fi

echo "Aktualisiere Abhängigkeiten ..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install --upgrade -r "$SCRIPT_DIR/requirements.txt"
echo ""

echo "=== Update abgeschlossen! ==="
