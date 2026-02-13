#!/bin/bash
set -euo pipefail

CONFIG_FILE="/config/config.yaml"

# --- Modus: Setup Web UI (nur Weboberfläche, kein Backup) ---
if [ "${1:-}" = "setup" ]; then
    echo "=== Setup Web UI ==="
    echo "Öffne http://<NAS-IP>:${SETUP_PORT:-8080} im Browser."
    exec python /app/setup_web.py
fi

# --- Modus: Authentifizierung (interaktiv, per SSH) ---
if [ "${1:-}" = "auth" ]; then
    echo "=== Interaktive Authentifizierung ==="
    shift
    exec python /app/backup.py -c "$CONFIG_FILE" --auth-only "$@"
fi

# --- Modus: Ordnerauswahl (interaktiv) ---
if [ "${1:-}" = "select-folders" ]; then
    echo "=== Interaktive Ordnerauswahl ==="
    shift
    exec python /app/backup.py -c "$CONFIG_FILE" --select-folders "$@"
fi

# --- Modus: Einmaliger Backup-Lauf ---
if [ "${1:-}" = "backup" ]; then
    echo "=== Starte Backup ==="
    shift
    exec python /app/backup.py -c "$CONFIG_FILE" "$@"
fi

# --- Modus: Cron (Standard) ---
if [ "${1:-}" = "cron" ]; then
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "FEHLER: Keine config.yaml gefunden unter $CONFIG_FILE"
        echo ""
        echo "Erstelle eine config.yaml und mounte sie nach /config/config.yaml."
        echo "Siehe config.example.yaml als Vorlage."
        exit 1
    fi

    echo "=== iCloud Drive Backup (Docker) ==="
    echo "Cron-Schedule: ${CRON_SCHEDULE}"
    echo "Zusätzliche Argumente: ${BACKUP_ARGS:-keine}"

    # Setup Web UI im Hintergrund starten (falls SETUP_PORT gesetzt)
    if [ -n "${SETUP_PORT:-}" ]; then
        echo "Setup Web UI verfügbar auf Port ${SETUP_PORT}"
        python /app/setup_web.py &
    fi
    echo ""

    # Einmaliger Lauf beim Start
    echo "Starte initialen Backup-Lauf ..."
    python /app/backup.py -c "$CONFIG_FILE" ${BACKUP_ARGS} || true
    echo ""

    # Cron-Job einrichten
    # Umgebungsvariablen für den Cron-Job verfügbar machen
    env > /etc/environment

    echo "${CRON_SCHEDULE} python /app/backup.py -c ${CONFIG_FILE} ${BACKUP_ARGS} >> /proc/1/fd/1 2>> /proc/1/fd/2" \
        > /etc/cron.d/icloud-backup
    echo "" >> /etc/cron.d/icloud-backup
    chmod 0644 /etc/cron.d/icloud-backup
    crontab /etc/cron.d/icloud-backup

    echo "Cron-Daemon gestartet. Nächster Lauf gemäß Schedule: ${CRON_SCHEDULE}"
    exec cron -f
fi

# --- Fallback: beliebiger Befehl ---
exec "$@"
