# iCloud Drive Backup

Backs up selected folders from the iCloud Drives of multiple family members to a Linux server. Uses existing session tokens from [pyicloud](https://github.com/picklepete/pyicloud) or authenticates independently (including 2FA).

## How It Works

- **Mirror Sync**: The target directory is kept as an exact mirror of the iCloud Drive folders
- New/changed files are downloaded
- Files deleted on iCloud are also removed locally
- Comparison via file size and modification date

## Prerequisites

- Python 3.10+
- Optional: Existing pyicloud session tokens in `~/.pyicloud/` (e.g. from icloudpd). Without existing tokens, you will be prompted interactively for password and 2FA code on first run.

## Quick Start

```bash
# Setup – creates venv, installs dependencies, prompts for configuration,
# checks authentication and offers folder selection
./setup.sh
```

The setup script guides you through the complete initial setup:
1. Create venv and install dependencies
2. Prompt for Apple ID and target directory → create `config.yaml`
3. Check authentication (password + 2FA if needed)
4. Select folders interactively

## Configuration

The `config.yaml` can also be created/edited manually:

```yaml
jobs:
  - name: "dad"
    username: "dad@example.com"
    folders:
      - "Documents"
      - "Desktop"
    destination: "/mnt/backup/dad/icloud-drive"

  - name: "mom"
    username: "mom@example.com"
    folders:
      - "Documents"
    destination: "/mnt/backup/mom/icloud-drive"

settings:
  log_level: "INFO"
  dry_run: false
```

### Job Options

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Name of the job (used in logs and `--job` filter) |
| `username` | yes | Apple ID |
| `cookie_directory` | no | Directory containing pyicloud session files (default: `~/.pyicloud`) |
| `password` | no | Password (usually not needed with existing tokens) |
| `folders` | yes | List of iCloud Drive folders (relative to root, `"/"` for entire drive) |
| `exclude` | no | List of exclusion patterns (see below) |
| `destination` | yes | Local target directory |

### Token Files

pyicloud stores session tokens as flat files in the `cookie_directory` (default: `~/.pyicloud/`):

```
~/.pyicloud/dadexamplecom.session
~/.pyicloud/dadexamplecom.cookiejar
```

The filename is automatically derived from the Apple ID (word characters only). `cookie_directory` only needs to be specified if the tokens are not in `~/.pyicloud/`.

### Exclude Patterns

Files and folders can be excluded from the backup using `exclude`:

```yaml
exclude:
  - "Projects"              # Relative: skips Projects/ in every synced folder
  - "Documents/Projects"    # Absolute: only Documents/Projects, not Desktop/Projects
  - ".git"                  # Glob on folder name: skips every .git folder
  - "*.tmp"                 # Glob on filename: skips all .tmp files
  - ".DS_Store"             # Single file everywhere
```

Patterns are matched against both the relative path (within the folder) and the full path (from iCloud Drive root). This allows excludes to be targeted to specific folders. Excluded folders are skipped entirely (no API call), meaning excludes also speed up the scan.

## Usage

```bash
# Run all jobs
python backup.py

# Dry run (no changes)
python backup.py --dry-run

# Run a specific job only
python backup.py --job "dad"

# Verbose output
python backup.py --verbose

# Custom configuration file
python backup.py --config /etc/icloud-backup/config.yaml

# Full scan (ignore etag cache)
python backup.py --full-scan

# Check/set up authentication (password + 2FA interactively)
python backup.py --auth-only
python backup.py --auth-only --job "dad"

# Interactively select top-level folders and write to config.yaml
python backup.py --select-folders
```

### Etag Cache

From the second run onward, folders whose `etag` has not changed since the last sync are skipped. This saves significant API calls and time for daily backups. The cache is stored as `.icloud-backup-state-*.json` in the target directory.

- The cache is only updated after a successful run
- `--full-scan` forces a complete scan without cache
- `--dry-run` does not modify the cache

## Automation (Cron)

```cron
# Daily at 3:00 AM
0 3 * * * /opt/icloud-drive-backup/venv/bin/python /opt/icloud-drive-backup/backup.py -c /opt/icloud-drive-backup/config.yaml >> /var/log/icloud-backup.log 2>&1
```

## Target Directory Structure

For a job with `destination: /mnt/backup/dad` and `folders: [Documents, Desktop]`:

```
/mnt/backup/dad/
├── Documents/
│   ├── Contract.pdf
│   └── Notes/
│       └── todo.txt
└── Desktop/
    └── screenshot.png
```

## Docker / Synology NAS

The backup can run as a Docker container – ideal for a Synology NAS with Container Manager.

### 1. Prepare directories

Create the directory structure on your Synology (via SSH or File Station):

```bash
mkdir -p /volume1/docker/icloud-backup/config
mkdir -p /volume1/docker/icloud-backup/pyicloud
mkdir -p /volume1/docker/icloud-backup/backups
```

### 2. Create config.yaml

Place your `config.yaml` in the config directory. **Important**: `destination` must point to `/data/...` (the mount point inside the container):

```yaml
jobs:
  - name: "dad"
    username: "dad@example.com"
    folders:
      - "Documents"
      - "Desktop"
    exclude:
      - ".git"
      - ".DS_Store"
    destination: "/data/dad"

  - name: "mom"
    username: "mom@example.com"
    folders:
      - "Documents"
    destination: "/data/mom"

settings:
  log_level: "INFO"
  dry_run: false
```

### 3. Build and start

Clone the repo and build the image on your Synology (via SSH):

```bash
cd /volume1/docker/icloud-backup
git clone https://github.com/michis0806/iCloud-Drive-Backup.git app
cd app

# Build the Docker image
docker build -t icloud-drive-backup .
```

### 4. Initial authentication (2FA)

Before the container can run automatically, you must authenticate interactively once:

```bash
docker run -it --rm \
  -v /volume1/docker/icloud-backup/config:/config \
  -v /volume1/docker/icloud-backup/pyicloud:/root/.pyicloud \
  -v /volume1/docker/icloud-backup/backups:/data \
  icloud-drive-backup auth
```

This will prompt for your password and 2FA code. The trust token is stored in the `pyicloud/` directory and is valid for approximately 2 months.

Repeat for each Apple ID / job if needed:

```bash
docker run -it --rm \
  -v /volume1/docker/icloud-backup/config:/config \
  -v /volume1/docker/icloud-backup/pyicloud:/root/.pyicloud \
  -v /volume1/docker/icloud-backup/backups:/data \
  icloud-drive-backup auth --job "mom"
```

### 5. Run with docker-compose

Create or adjust the `docker-compose.yml`:

```yaml
services:
  icloud-backup:
    build: ./app
    container_name: icloud-drive-backup
    restart: unless-stopped
    environment:
      - CRON_SCHEDULE=0 3 * * *
      - BACKUP_ARGS=
    volumes:
      - /volume1/docker/icloud-backup/config:/config
      - /volume1/docker/icloud-backup/pyicloud:/root/.pyicloud
      - /volume1/docker/icloud-backup/backups:/data
```

```bash
docker-compose up -d
```

The container will:
1. Run an initial backup immediately on start
2. Then execute backups on the configured cron schedule (default: daily at 3:00 AM)

### 6. Synology Container Manager (GUI)

For a detailed step-by-step guide with DSM screenshots instructions, see **[SYNOLOGY.md](SYNOLOGY.md)**.

Quick summary:

1. **Image**: Build the image via SSH (step 3)
2. **Container Manager** > **Project** > **Create**: paste the docker-compose.yml
3. Or create the container manually with these volume mappings:
   - `/volume1/docker/icloud-backup/config` → `/config`
   - `/volume1/docker/icloud-backup/pyicloud` → `/root/.pyicloud`
   - `/volume1/docker/icloud-backup/backups` → `/data`

### Docker commands

```bash
# View logs
docker logs -f icloud-drive-backup

# Manual backup run
docker exec icloud-drive-backup python /app/backup.py -c /config/config.yaml

# Dry run
docker exec icloud-drive-backup python /app/backup.py -c /config/config.yaml --dry-run

# Re-authenticate (when token expires, every ~2 months)
docker run -it --rm \
  -v /volume1/docker/icloud-backup/config:/config \
  -v /volume1/docker/icloud-backup/pyicloud:/root/.pyicloud \
  -v /volume1/docker/icloud-backup/backups:/data \
  icloud-drive-backup auth

# Select folders interactively
docker run -it --rm \
  -v /volume1/docker/icloud-backup/config:/config \
  -v /volume1/docker/icloud-backup/pyicloud:/root/.pyicloud \
  -v /volume1/docker/icloud-backup/backups:/data \
  icloud-drive-backup select-folders
```

## Notes

- **2FA**: `--auth-only` performs the full authentication interactively (password + 2FA code). Afterwards, a trust token is stored that is valid for approximately 2 months.
- **Session Expiry**: When the session expires, run `--auth-only` again (or `docker run ... auth` for Docker).
- **Shared Folders**: Shared folders may not be supported by the pyicloud API.
