#!/usr/bin/env bash
# Setup-Script: erstellt ein venv, installiert Abhängigkeiten und
# führt optional durch die Ersteinrichtung der config.yaml.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
CONFIG_FILE="$SCRIPT_DIR/config.yaml"

echo "=== iCloud Drive Backup – Setup ==="
echo ""

# --- venv erstellen & Abhängigkeiten installieren ---
if [ ! -d "$VENV_DIR" ]; then
    echo "Erstelle virtuelle Umgebung in $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
fi

echo "Installiere Abhängigkeiten ..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" -q
echo "Abhängigkeiten installiert."
echo ""

# --- Interaktives Config-Setup (nur wenn config.yaml noch nicht existiert) ---
if [ -f "$CONFIG_FILE" ]; then
    echo "config.yaml existiert bereits – überspringe Ersteinrichtung."
    echo ""
else
    echo "Keine config.yaml gefunden – starte Ersteinrichtung."
    echo ""

    read -rp "Apple-ID (E-Mail): " APPLE_ID
    if [ -z "$APPLE_ID" ]; then
        echo "Fehler: Apple-ID darf nicht leer sein."
        exit 1
    fi

    # Normalisierte Apple-ID (wie pyicloud sie für Dateinamen verwendet)
    NORMALIZED_ID=$(echo "$APPLE_ID" | tr -cd '[:alnum:]_')

    # Prüfen ob schon Tokens vorhanden sind
    DEFAULT_COOKIE_DIR="$HOME/.pyicloud"
    if [ -f "$DEFAULT_COOKIE_DIR/$NORMALIZED_ID.session" ]; then
        echo "Vorhandene Session-Tokens gefunden: $DEFAULT_COOKIE_DIR/$NORMALIZED_ID.session"
    else
        echo "Keine vorhandenen Tokens gefunden – wird bei --auth-only erstellt."
    fi

    DEFAULT_DEST="$HOME/icloud-backup/$APPLE_ID"
    read -rp "Zielverzeichnis für Backups [$DEFAULT_DEST]: " DESTINATION
    DESTINATION="${DESTINATION:-$DEFAULT_DEST}"

    # Job-Name aus Apple-ID ableiten (Teil vor @)
    JOB_NAME="${APPLE_ID%%@*}"

    cat > "$CONFIG_FILE" <<YAML
jobs:
  - name: "$JOB_NAME"
    username: "$APPLE_ID"
    folders:
      - "Documents"
      - "Desktop"
    exclude:
      - ".git"
      - ".DS_Store"
    destination: "$DESTINATION"

settings:
  log_level: "INFO"
  dry_run: false
YAML

    echo ""
    echo "config.yaml erstellt mit Job '$JOB_NAME'."
    echo "Folders: Documents, Desktop (anpassbar via --select-folders)"
    echo ""
fi

# --- Authentifizierung prüfen ---
echo "=== Authentifizierung prüfen ==="
echo ""
"$VENV_DIR/bin/python" "$SCRIPT_DIR/backup.py" -c "$CONFIG_FILE" --auth-only

# --- Ordnerauswahl ---
echo ""
read -rp "Möchtest du die zu sichernden Ordner jetzt auswählen? [J/n]: " DO_SELECT
DO_SELECT="${DO_SELECT:-j}"
if [[ "$DO_SELECT" =~ ^[jJyY]$ ]]; then
    "$VENV_DIR/bin/python" "$SCRIPT_DIR/backup.py" -c "$CONFIG_FILE" --select-folders
fi

# --- Fertig ---
echo ""
echo "=== Setup abgeschlossen! ==="
echo ""
echo "Backup starten:"
echo "  $VENV_DIR/bin/python $SCRIPT_DIR/backup.py --dry-run   # Trockenlauf"
echo "  $VENV_DIR/bin/python $SCRIPT_DIR/backup.py             # Echtes Backup"
