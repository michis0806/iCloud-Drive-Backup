# Einrichtung auf Synology NAS (DSM 7.2+)

Schritt-für-Schritt-Anleitung zur Einrichtung des iCloud Drive Backups über die DSM-Oberfläche (Container Manager).

Die Anmeldung bei Apple (inkl. 2FA) erfolgt komplett über den Browser – **kein SSH nötig** (außer einmalig zum Image-Build).

---

## Voraussetzungen

- Synology NAS mit DSM 7.2 oder neuer
- **Container Manager** aus dem Paketzentrum installiert
- SSH-Zugriff (nur einmalig zum Image-Build)

---

## Schritt 1: Verzeichnisse anlegen (File Station)

Öffne **File Station** und erstelle folgende Ordnerstruktur:

```
docker/
└── icloud-backup/
    ├── app/           ← hier kommt der Quellcode hin
    ├── config/        ← config.yaml
    ├── pyicloud/      ← Session-Tokens (werden automatisch befüllt)
    └── backups/       ← Backup-Zielverzeichnis
```

**So geht's:**

1. Öffne **File Station**
2. Navigiere zum Ordner `docker` (falls nicht vorhanden: Rechtsklick → *Ordner erstellen*)
3. Erstelle darin den Ordner `icloud-backup`
4. Erstelle darin die Unterordner: `app`, `config`, `pyicloud`, `backups`

---

## Schritt 2: config.yaml erstellen

Erstelle die Datei `config.yaml` und lade sie nach `docker/icloud-backup/config/` hoch.

**Wichtig:** Als `destination` muss `/data/...` verwendet werden – das ist der Pfad *innerhalb* des Containers.

```yaml
jobs:
  - name: "papa"
    username: "papa@icloud.com"
    folders:
      - "Documents"
      - "Desktop"
    exclude:
      - ".git"
      - ".DS_Store"
    destination: "/data/papa"

  - name: "mama"
    username: "mama@icloud.com"
    folders:
      - "Documents"
    destination: "/data/mama"

settings:
  log_level: "INFO"
  dry_run: false
```

**So geht's:**

1. Erstelle die Datei `config.yaml` auf deinem Computer (z.B. mit TextEdit/Notepad)
2. Passe Apple-IDs, Ordner und Job-Namen an
3. Öffne **File Station** → `docker/icloud-backup/config/`
4. Klicke auf **Hochladen** → **Dateien hochladen** → wähle `config.yaml`

---

## Schritt 3: Docker-Image bauen (SSH)

Dieser Schritt erfordert einmalig SSH-Zugriff.

### SSH aktivieren

1. Öffne **Systemsteuerung** → **Terminal & SNMP**
2. Hake **SSH-Dienst aktivieren** an
3. Klicke **Übernehmen**

### Image bauen

Verbinde dich per SSH (macOS Terminal / Windows PowerShell):

```bash
ssh dein-benutzer@synology-ip
```

Dann:

```bash
# Repository klonen
cd /volume1/docker/icloud-backup
sudo git clone https://github.com/michis0806/iCloud-Drive-Backup.git app

# Docker-Image bauen
cd app
sudo docker build -t icloud-drive-backup .
```

> Das Image erscheint danach automatisch im Container Manager unter **Image**.
>
> SSH kann danach wieder deaktiviert werden.

---

## Schritt 4: Projekt im Container Manager anlegen (GUI)

### Option A: Als Projekt (docker-compose) – empfohlen

1. Öffne **Container Manager** → **Projekt**
2. Klicke **Erstellen**
3. Fülle aus:
   - **Projektname:** `icloud-backup`
   - **Pfad:** `/volume1/docker/icloud-backup`
   - **Quelle:** Wähle *docker-compose.yml erstellen*
4. Füge folgende Compose-Konfiguration ein:

```yaml
services:
  icloud-backup:
    image: icloud-drive-backup
    container_name: icloud-drive-backup
    restart: unless-stopped
    environment:
      - CRON_SCHEDULE=0 3 * * *
      - BACKUP_ARGS=
      - SETUP_PORT=8080
    ports:
      - "8080:8080"
    volumes:
      - /volume1/docker/icloud-backup/config:/config
      - /volume1/docker/icloud-backup/pyicloud:/root/.pyicloud
      - /volume1/docker/icloud-backup/backups:/data
```

5. Klicke **Weiter**
6. Prüfe die Zusammenfassung und klicke **Fertig**
7. Der Container startet automatisch

> **Was passiert beim ersten Start?**
> Der Container startet im Cron-Modus und versucht ein erstes Backup.
> Da noch keine Anmeldung erfolgt ist, schlägt das fehl – das ist normal!
> Gleichzeitig startet die Setup Web UI auf Port 8080.

### Option B: Container manuell erstellen

Falls du kein Projekt verwenden möchtest:

#### 4.1 Container erstellen

1. Öffne **Container Manager** → **Container**
2. Klicke **Erstellen**
3. **Image auswählen:** `icloud-drive-backup:latest`
4. Klicke **Weiter**

#### 4.2 Allgemeine Einstellungen

- **Containername:** `icloud-drive-backup`
- **Automatischen Neustart aktivieren:** Ja
- Klicke auf **Erweiterte Einstellungen**

#### 4.3 Erweiterte Einstellungen – Umgebungsvariablen

Klicke auf den Reiter **Umgebung** und füge hinzu:

| Variable | Wert |
|----------|------|
| `CRON_SCHEDULE` | `0 3 * * *` |
| `BACKUP_ARGS` | *(leer lassen, oder z.B. `--verbose`)* |
| `SETUP_PORT` | `8080` |

> **Cron-Schedule Beispiele:**
> - `0 3 * * *` = täglich um 3:00 Uhr
> - `0 */6 * * *` = alle 6 Stunden
> - `0 3 * * 1` = jeden Montag um 3:00 Uhr

#### 4.4 Erweiterte Einstellungen – Ports

Klicke auf den Reiter **Port-Einstellungen** und füge hinzu:

| Lokaler Port | Container-Port | Protokoll |
|-------------|----------------|-----------|
| `8080` | `8080` | TCP |

#### 4.5 Erweiterte Einstellungen – Volumes

Klicke auf den Reiter **Volume** bzw. **Speicherplatz** und erstelle folgende Zuordnungen:

| Ordner auf NAS | Mount-Pfad im Container |
|------|-----------|
| `docker/icloud-backup/config` | `/config` |
| `docker/icloud-backup/pyicloud` | `/root/.pyicloud` |
| `docker/icloud-backup/backups` | `/data` |

**So fügst du ein Volume hinzu:**

1. Klicke **Ordner hinzufügen**
2. Navigiere zum jeweiligen Ordner (z.B. `docker/icloud-backup/config`)
3. Trage den Mount-Pfad ein (z.B. `/config`)
4. Wiederhole für alle drei Ordner

#### 4.6 Container starten

1. Klicke **Weiter** → Prüfe die Zusammenfassung
2. Klicke **Fertig**
3. Der Container startet automatisch

---

## Schritt 5: Anmeldung über den Browser (Setup Web UI)

Jetzt erfolgt die Apple-ID-Anmeldung inkl. 2FA direkt im Browser – **kein SSH nötig!**

1. Öffne im Browser: **http://DEINE-NAS-IP:8080**
2. Du siehst eine Übersicht aller Jobs aus der config.yaml
3. Klicke bei einem Job auf **Anmelden**
4. **Passwort eingeben** → Apple-ID-Passwort eintragen → **Anmelden**
5. **2FA-Code eingeben:**
   - Auf deinem iPhone/iPad erscheint eine Benachrichtigung → **Erlauben**
   - Den 6-stelligen Code im Browser eingeben → **Bestätigen**
6. Es erscheint: *"Authentifizierung erfolgreich! Token gespeichert."*
7. **Bei mehreren Apple-IDs:** Wiederhole den Vorgang für jeden Job

> Die Trust-Tokens sind ca. 2 Monate gültig.
> Wenn sie ablaufen, einfach wieder http://NAS-IP:8080 öffnen und erneut anmelden.

---

## Schritt 6: Logs prüfen

### Über die GUI

1. **Container Manager** → **Container**
2. Klicke auf `icloud-drive-backup`
3. Wähle den Reiter **Protokoll**
4. Hier siehst du die Ausgabe der Backup-Läufe

### Über SSH (optional)

```bash
sudo docker logs -f icloud-drive-backup
```

---

## Wartung

### Token erneuern (alle ~2 Monate)

Wenn die Session abgelaufen ist, schlägt das Backup fehl. Einfach:

1. Öffne **http://DEINE-NAS-IP:8080** im Browser
2. Klicke bei dem betroffenen Job auf **Anmelden**
3. Passwort + 2FA-Code eingeben – fertig!

### Setup Web UI deaktivieren

Wenn du die Web-Oberfläche nicht dauerhaft laufen lassen möchtest:

1. **Container Manager** → **Projekt** → `icloud-backup`
2. **Bearbeiten** → Entferne die Zeilen `SETUP_PORT=8080` und `"8080:8080"`
3. **Übernehmen** → Container wird neu gestartet

> Die Web UI kann jederzeit wieder aktiviert werden, wenn Token erneuert werden müssen.

### Manuelles Backup auslösen

Über SSH:

```bash
sudo docker exec icloud-drive-backup python /app/backup.py -c /config/config.yaml
```

### Trockenlauf (ohne Änderungen)

```bash
sudo docker exec icloud-drive-backup python /app/backup.py -c /config/config.yaml --dry-run
```

### Image aktualisieren

Wenn es ein Update des Backup-Scripts gibt:

```bash
cd /volume1/docker/icloud-backup/app
sudo git pull
sudo docker build -t icloud-drive-backup .
```

Danach im **Container Manager** den Container neu starten:

1. **Container** → `icloud-drive-backup`
2. Klicke **Aktion** → **Neu starten**

---

## Fehlerbehebung

| Problem | Lösung |
|---------|--------|
| `Konfigurationsdatei nicht gefunden` | `config.yaml` liegt nicht in `docker/icloud-backup/config/` |
| `Account benötigt 2FA` | Setup Web UI öffnen (http://NAS-IP:8080) und anmelden |
| Web UI nicht erreichbar | Prüfe ob `SETUP_PORT=8080` gesetzt und Port 8080 gemappt ist |
| Backup läuft nicht automatisch | Container-Status im Container Manager prüfen, Logs ansehen |
| `Fehler beim Herunterladen` | Netzwerkverbindung prüfen, ggf. Token erneuern |
| Leeres Backup-Verzeichnis | Prüfe ob `destination` in config.yaml auf `/data/...` zeigt |
