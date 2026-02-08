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

## Notes

- **2FA**: `--auth-only` performs the full authentication interactively (password + 2FA code). Afterwards, a trust token is stored that is valid for approximately 2 months.
- **Session Expiry**: When the session expires, run `--auth-only` again.
- **Shared Folders**: Shared folders may not be supported by the pyicloud API.
