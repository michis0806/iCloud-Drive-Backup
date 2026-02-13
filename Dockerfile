FROM python:3.12-slim

# Cron installieren
RUN apt-get update && \
    apt-get install -y --no-install-recommends cron && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backup.py .
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Verzeichnisse für Konfiguration, Tokens und Backups
RUN mkdir -p /config /data /root/.pyicloud

# Volumes: Config, Tokens und Backup-Ziel
VOLUME ["/config", "/data", "/root/.pyicloud"]

ENV CRON_SCHEDULE="0 3 * * *"
ENV BACKUP_ARGS=""

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["cron"]
