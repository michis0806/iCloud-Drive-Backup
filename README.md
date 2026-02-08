# iCloud Drive Backup

Sichert ausgewählte Ordner aus den iCloud Drives mehrerer Familienmitglieder auf einen Linux-Server. Nutzt vorhandene Session-Tokens von [icloud_photos_downloader](https://github.com/icloud-photos-downloader/icloud_photos_downloader) oder authentifiziert sich selbstständig (inkl. 2FA).

## Funktionsweise

- **Mirror-Sync**: Das Zielverzeichnis wird als exaktes Abbild der iCloud-Drive-Ordner gehalten
- Neue/geänderte Dateien werden heruntergeladen
- Auf iCloud gelöschte Dateien werden auch lokal entfernt
- Vergleich über Dateigröße und Änderungsdatum

## Voraussetzungen

- Python 3.10+
- Optional: Bestehende pyicloud Session-Tokens in `~/.pyicloud/` (z.B. durch icloudpd). Ohne vorhandene Tokens wird beim ersten Start interaktiv nach Passwort und 2FA-Code gefragt.

## Schnellstart

```bash
# Setup – erstellt venv, installiert Abhängigkeiten, fragt Konfiguration ab,
# prüft Authentifizierung und bietet Ordnerauswahl an
./setup.sh
```

Das Setup-Script führt durch die komplette Ersteinrichtung:
1. venv erstellen und Abhängigkeiten installieren
2. Apple-ID und Zielverzeichnis abfragen → `config.yaml` erstellen
3. Authentifizierung prüfen (bei Bedarf Passwort + 2FA)
4. Ordner interaktiv auswählen

## Konfiguration

Die `config.yaml` kann auch manuell erstellt/bearbeitet werden:

```yaml
jobs:
  - name: "papa"
    username: "papa@example.com"
    folders:
      - "Documents"
      - "Desktop"
    destination: "/mnt/backup/papa/icloud-drive"

  - name: "mama"
    username: "mama@example.com"
    folders:
      - "Documents"
    destination: "/mnt/backup/mama/icloud-drive"

settings:
  log_level: "INFO"
  dry_run: false
```

### Job-Optionen

| Feld | Pflicht | Beschreibung |
|------|---------|-------------|
| `name` | ja | Name des Jobs (für Logs und `--job`-Filter) |
| `username` | ja | Apple-ID |
| `cookie_directory` | nein | Verzeichnis mit den pyicloud Session-Dateien (Standard: `~/.pyicloud`) |
| `password` | nein | Passwort (normalerweise nicht nötig bei vorhandenen Tokens) |
| `folders` | ja | Liste der iCloud-Drive-Ordner (relativ zum Root, `"/"` für gesamtes Drive) |
| `exclude` | nein | Liste von Ausschluss-Pattern (siehe unten) |
| `destination` | ja | Lokales Zielverzeichnis |

### Token-Dateien

pyicloud speichert Session-Tokens als Flat-Files im `cookie_directory` (Standard: `~/.pyicloud/`):

```
~/.pyicloud/papaexamplecom.session
~/.pyicloud/papaexamplecom.cookiejar
```

Der Dateiname wird automatisch aus der Apple-ID abgeleitet (nur Wortzeichen). `cookie_directory` muss nur angegeben werden, wenn die Tokens nicht in `~/.pyicloud/` liegen.

### Exclude-Pattern

Über `exclude` können Dateien und Ordner vom Backup ausgeschlossen werden:

```yaml
exclude:
  - "Projects"              # Relativ: überspringt Projects/ in jedem synced Folder
  - "Documents/Projects"    # Absolut: nur Documents/Projects, nicht Desktop/Projects
  - ".git"                  # Glob auf Ordnernamen: überspringt jeden .git-Ordner
  - "*.tmp"                 # Glob auf Dateinamen: überspringt alle .tmp-Dateien
  - ".DS_Store"             # Einzelne Datei überall
```

Pattern werden sowohl gegen den relativen Pfad (innerhalb des Folders) als auch gegen den vollen Pfad (ab iCloud-Drive-Root) geprüft. So lassen sich Excludes gezielt auf einzelne Folder einschränken. Ausgeschlossene Ordner werden komplett übersprungen (kein API-Call), d.h. Excludes beschleunigen auch den Scan.

## Verwendung

```bash
# Alle Jobs ausführen
python backup.py

# Trockenlauf (keine Änderungen)
python backup.py --dry-run

# Nur einen bestimmten Job
python backup.py --job "papa"

# Ausführliche Ausgabe
python backup.py --verbose

# Eigene Konfigurationsdatei
python backup.py --config /etc/icloud-backup/config.yaml

# Kompletter Scan (Etag-Cache ignorieren)
python backup.py --full-scan

# Authentifizierung prüfen/einrichten (Passwort + 2FA interaktiv)
python backup.py --auth-only
python backup.py --auth-only --job "papa"

# Top-Level-Ordner interaktiv auswählen und in config.yaml schreiben
python backup.py --select-folders
```

### Etag-Cache

Ab dem zweiten Lauf werden Ordner, deren `etag` sich seit dem letzten Sync nicht geändert hat, übersprungen. Das spart bei täglichen Backups erheblich API-Calls und Zeit. Der Cache wird als `.icloud-backup-state-*.json` im Zielverzeichnis gespeichert.

- Der Cache wird nur bei fehlerfreiem Durchlauf aktualisiert
- `--full-scan` erzwingt einen kompletten Scan ohne Cache
- `--dry-run` verändert den Cache nicht

## Automatisierung (Cron)

```cron
# Täglich um 3:00 Uhr
0 3 * * * /opt/icloud-drive-backup/venv/bin/python /opt/icloud-drive-backup/backup.py -c /opt/icloud-drive-backup/config.yaml >> /var/log/icloud-backup.log 2>&1
```

## Verzeichnisstruktur im Ziel

Für einen Job mit `destination: /mnt/backup/papa` und `folders: [Documents, Desktop]`:

```
/mnt/backup/papa/
├── Documents/
│   ├── Vertrag.pdf
│   └── Notizen/
│       └── todo.txt
└── Desktop/
    └── screenshot.png
```

## Hinweise

- **2FA**: `--auth-only` führt die vollständige Authentifizierung interaktiv durch (Passwort + 2FA-Code). Danach wird ein Trust-Token gespeichert, das ca. 2 Monate gültig ist.
- **Session-Ablauf**: Wenn die Session abläuft, erneut `--auth-only` ausführen.
- **Shared Folders**: Geteilte Ordner werden von der pyicloud-API möglicherweise nicht unterstützt.
