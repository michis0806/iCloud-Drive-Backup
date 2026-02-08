#!/usr/bin/env python3
"""iCloud Drive Backup – Synchronisiert iCloud Drive Ordner auf ein lokales Zielverzeichnis."""

import argparse
import fnmatch
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from shutil import copyfileobj

import yaml

log = logging.getLogger("icloud-drive-backup")


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    """Lädt die YAML-Konfigurationsdatei."""
    config_path = Path(path)
    if not config_path.exists():
        log.error("Konfigurationsdatei nicht gefunden: %s", config_path)
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# iCloud-Authentifizierung
# ---------------------------------------------------------------------------

def authenticate(username: str, password: str | None = None, cookie_directory: str | None = None,
                 interactive: bool = False):
    """Erstellt eine authentifizierte PyiCloudService-Instanz.

    Nutzt vorhandene Session-Tokens aus dem Cookie-Verzeichnis.
    Bei interactive=True wird bei fehlendem Token/2FA interaktiv nach
    Passwort und 2FA-Code gefragt.
    """
    from pyicloud import PyiCloudService

    # pyicloud speichert Session-Dateien als Flat-Files im cookie_directory:
    #   <dir>/<normalized_username>.session
    #   <dir>/<normalized_username>.cookiejar
    # Standard von pyicloud ist ~/.pyicloud/
    if cookie_directory:
        cookie_dir = os.path.expanduser(cookie_directory)
    else:
        cookie_dir = os.path.expanduser("~/.pyicloud")

    kwargs = {"apple_id": username, "cookie_directory": cookie_dir}
    if password:
        kwargs["password"] = password

    # Dateinamen, den pyicloud verwenden wird (nur Wortzeichen aus der Apple-ID)
    normalized = "".join(c for c in username if c.isalnum() or c == "_")
    log.info("Authentifiziere als %s (Token: %s/%s.session)", username, cookie_dir, normalized)

    try:
        api = PyiCloudService(**kwargs)
    except Exception:
        if not interactive:
            raise
        # Kein gespeicherter Token – Passwort interaktiv abfragen
        import getpass
        pw = getpass.getpass(f"Passwort für {username}: ")
        kwargs["password"] = pw
        api = PyiCloudService(**kwargs)

    if api.requires_2fa:
        if not interactive:
            log.error(
                "Account %s benötigt 2FA. Bitte mit --auth-only interaktiv "
                "authentifizieren oder icloudpd verwenden.",
                username,
            )
            raise SystemExit(1)
        # Interaktive 2FA
        print(f"\nAccount {username} benötigt Zwei-Faktor-Authentifizierung.")
        print("Ein Code wurde an deine Apple-Geräte gesendet.")
        code = input("2FA-Code eingeben: ").strip()
        if not api.validate_2fa_code(code):
            log.error("Ungültiger 2FA-Code.")
            raise SystemExit(1)
        print("2FA erfolgreich! Speichere Trust-Token ...")
        api.trust_session()

    return api


# ---------------------------------------------------------------------------
# Drive-Navigation
# ---------------------------------------------------------------------------

def resolve_drive_folder(drive, folder_path: str):
    """Navigiert von der iCloud-Drive-Root zum angegebenen Ordner.

    folder_path: z.B. "Documents/Projekte/2024"
    """
    node = drive
    for part in folder_path.strip("/").split("/"):
        if not part:
            continue
        try:
            node = node[part]
        except (KeyError, IndexError):
            log.error("Ordner nicht gefunden auf iCloud Drive: %s (bei '%s')", folder_path, part)
            return None
    return node


# ---------------------------------------------------------------------------
# Etag-Cache
# ---------------------------------------------------------------------------

def _state_path(destination: str, folder_path: str) -> Path:
    """Pfad zur State-Datei für einen Sync-Ordner."""
    safe_name = folder_path.strip("/").replace("/", "_") or "root"
    return Path(destination) / f".icloud-backup-state-{safe_name}.json"


def load_state(destination: str, folder_path: str) -> dict:
    """Lädt den gespeicherten Sync-State (etags + Dateilisten)."""
    path = _state_path(destination, folder_path)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("State-Datei beschädigt, starte mit leerem Cache: %s", exc)
    return {"folder_etags": {}, "folder_files": {}}


def save_state(destination: str, folder_path: str, state: dict) -> None:
    """Speichert den Sync-State nach erfolgreichem Durchlauf."""
    path = _state_path(destination, folder_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def is_excluded(rel_path: str, full_path: str, excludes: list[str]) -> bool:
    """Prüft ob ein Pfad durch ein Exclude-Pattern ausgeschlossen wird.

    rel_path:  Pfad relativ zum synced Folder (z.B. "Projects/Old")
    full_path: Voller Pfad ab iCloud-Drive-Root (z.B. "Documents/Projects/Old")

    Pattern werden gegen beide Pfade geprüft:
      - "Projects"           → matcht Projects in jedem synced Folder
      - "Documents/Projects" → matcht nur Projects unter Documents
      - ".git"               → Glob: matcht jeden Pfadteil namens ".git"
      - "*.tmp"              → Glob: matcht alle .tmp-Dateien
    """
    for pattern in excludes:
        # Pattern mit Wildcard/Glob-Zeichen
        if any(c in pattern for c in "*?["):
            # Gegen beide Pfade matchen
            if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(full_path, pattern):
                return True
            # Gegen jeden einzelnen Pfadteil matchen (z.B. ".git" in "a/.git/config")
            for part in full_path.split("/"):
                if fnmatch.fnmatch(part, pattern):
                    return True
        else:
            pattern_stripped = pattern.rstrip("/")
            # Gegen relativen Pfad (innerhalb des Folders)
            if rel_path == pattern_stripped or rel_path.startswith(pattern_stripped + "/"):
                return True
            # Gegen vollen Pfad (ab iCloud-Drive-Root)
            if full_path == pattern_stripped or full_path.startswith(pattern_stripped + "/"):
                return True
    return False


def walk_remote(node, rel_path: str = "", folder_path: str = "",
                excludes: list[str] | None = None,
                cached_state: dict | None = None, new_state: dict | None = None,
                _counter: list | None = None) -> list[tuple[str, object]]:
    """Durchläuft rekursiv einen iCloud Drive Ordner.

    rel_path:    Pfad relativ zum synced Folder (z.B. "Sub/Dir")
    folder_path: Top-Level-Folder aus der Config (z.B. "Documents")

    Gibt eine Liste von (relativer_pfad, DriveNode|None) Tupeln zurück (nur Dateien).
    Bei Cache-Treffern ist der DriveNode None (Datei ist unverändert).
    """
    if excludes is None:
        excludes = []
    if cached_state is None:
        cached_state = {"folder_etags": {}, "folder_files": {}}
    if new_state is None:
        new_state = {"folder_etags": {}, "folder_files": {}}
    if _counter is None:
        _counter = [0, 0, 0]  # [dateien, ordner, übersprungen]

    entries = []
    try:
        log.debug("Scanne Ordner: %s", rel_path or "/")
        children = node.get_children()
    except Exception as exc:
        log.warning("Konnte Unterordner nicht lesen (%s): %s", rel_path or "/", exc)
        return entries

    for child in children:
        child_rel = f"{rel_path}/{child.name}" if rel_path else child.name
        child_full = f"{folder_path}/{child_rel}" if folder_path else child_rel
        if excludes and is_excluded(child_rel, child_full, excludes):
            log.info("  Übersprungen (exclude): %s", child_full)
            continue
        if child.type == "folder":
            _counter[1] += 1
            child_etag = child.data.get("etag")
            cached_etag = cached_state["folder_etags"].get(child_rel)
            cached_files = cached_state["folder_files"].get(child_rel, [])

            if child_etag and cached_etag == child_etag and cached_files:
                # Ordner unverändert – Dateiliste aus Cache verwenden
                _counter[2] += 1
                _counter[0] += len(cached_files)
                log.info("  Ordner unverändert (etag cache): %s (%d Dateien)",
                         child_full, len(cached_files))
                # Gecachte Dateien ohne Node (None) zurückgeben
                for f in cached_files:
                    entries.append((f, None))
                # Cache-Daten in den neuen State übernehmen
                new_state["folder_etags"][child_rel] = child_etag
                new_state["folder_files"][child_rel] = cached_files
                # Auch verschachtelte Ordner-States übernehmen
                for k, v in cached_state["folder_etags"].items():
                    if k.startswith(child_rel + "/"):
                        new_state["folder_etags"][k] = v
                for k, v in cached_state["folder_files"].items():
                    if k.startswith(child_rel + "/"):
                        new_state["folder_files"][k] = v
            else:
                log.info("  Scanne Ordner [%d Dateien, %d Ordner, %d aus Cache]: %s",
                         _counter[0], _counter[1], _counter[2], child_full)
                sub_entries = walk_remote(child, child_rel, folder_path, excludes,
                                         cached_state, new_state, _counter)
                entries.extend(sub_entries)
                # Etag und Dateiliste für diesen Ordner speichern
                if child_etag:
                    new_state["folder_etags"][child_rel] = child_etag
                    new_state["folder_files"][child_rel] = [
                        path for path, _ in sub_entries
                    ]
        else:
            _counter[0] += 1
            entries.append((child_rel, child))

    return entries


# ---------------------------------------------------------------------------
# Synchronisation
# ---------------------------------------------------------------------------

def download_file(node, dest_path: Path, dry_run: bool = False) -> bool:
    """Lädt eine Datei von iCloud Drive herunter."""
    if dry_run:
        log.info("[DRY RUN] Würde herunterladen: %s", dest_path)
        return True

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")

    try:
        with node.open(stream=True) as response:
            with open(tmp_path, "wb") as f:
                copyfileobj(response.raw, f)
        tmp_path.rename(dest_path)

        # Änderungsdatum vom iCloud-Eintrag übernehmen
        if node.date_modified:
            mtime = node.date_modified.replace(tzinfo=timezone.utc).timestamp()
            os.utime(dest_path, (mtime, mtime))

        return True
    except Exception as exc:
        log.error("Fehler beim Herunterladen von %s: %s", dest_path, exc)
        if tmp_path.exists():
            tmp_path.unlink()
        return False


def file_needs_update(node, local_path: Path) -> bool:
    """Prüft, ob eine lokale Datei aktualisiert werden muss.

    Vergleicht Dateigröße und Änderungsdatum.
    """
    if not local_path.exists():
        return True

    stat = local_path.stat()

    # Größenvergleich
    remote_size = node.size
    if remote_size is not None and stat.st_size != remote_size:
        return True

    # Zeitvergleich – Remote ist neuer?
    if node.date_modified:
        remote_mtime = node.date_modified.replace(tzinfo=timezone.utc).timestamp()
        # Toleranz von 2 Sekunden für Dateisystem-Rundungsfehler
        if remote_mtime - stat.st_mtime > 2:
            return True

    return False


def sync_folder(drive, folder_path: str, destination: str,
                excludes: list[str] | None = None,
                dry_run: bool = False, full_scan: bool = False) -> dict:
    """Synchronisiert einen iCloud Drive Ordner ins Zielverzeichnis.

    Gibt Statistiken zurück: {downloaded, deleted, skipped, errors}
    folder_path "/" oder "" bedeutet iCloud-Drive-Root.
    """
    # Normalisieren: "/" → "" (Root)
    folder_path = folder_path.strip("/")

    stats = {"downloaded": 0, "deleted": 0, "skipped": 0, "errors": 0}
    if folder_path:
        dest_base = Path(destination) / folder_path.replace("/", os.sep)
    else:
        dest_base = Path(destination)

    log.info("Synchronisiere '%s' → %s", folder_path or "(Root)", dest_base)

    # Remote-Ordner auflösen
    remote_root = resolve_drive_folder(drive, folder_path)
    if remote_root is None:
        stats["errors"] += 1
        return stats

    # Etag-Cache laden
    cached_state = {} if full_scan else load_state(destination, folder_path)
    new_state = {"folder_etags": {}, "folder_files": {}}

    # Alle Remote-Dateien sammeln
    log.info("Lese Dateiliste von iCloud Drive/%s (kann bei vielen Ordnern dauern) ...", folder_path)
    remote_files = walk_remote(remote_root, folder_path=folder_path,
                               excludes=excludes or [],
                               cached_state=cached_state, new_state=new_state)
    log.info("Scan abgeschlossen: %d Dateien gefunden", len(remote_files))
    remote_paths = set()

    for rel_path, node in remote_files:
        remote_paths.add(rel_path)
        local_path = dest_base / rel_path

        if node is None:
            # Aus Cache – Datei war in einem unveränderten Ordner.
            # Lokale Datei existiert bereits (wurde beim letzten Sync heruntergeladen).
            log.debug("Unverändert (cache): %s", rel_path)
            stats["skipped"] += 1
        elif file_needs_update(node, local_path):
            log.info("Herunterladen: %s", rel_path)
            if download_file(node, local_path, dry_run):
                stats["downloaded"] += 1
            else:
                stats["errors"] += 1
        else:
            log.debug("Unverändert: %s", rel_path)
            stats["skipped"] += 1

    # Lokale Dateien entfernen, die auf iCloud Drive nicht mehr existieren
    if dest_base.exists():
        for local_file in sorted(dest_base.rglob("*")):
            if local_file.is_dir():
                continue
            if local_file.name.startswith(".icloud-backup-state"):
                continue
            rel = str(local_file.relative_to(dest_base))
            if rel not in remote_paths:
                if dry_run:
                    log.info("[DRY RUN] Würde löschen: %s", local_file)
                else:
                    log.info("Lösche (nicht mehr auf iCloud): %s", rel)
                    local_file.unlink()
                stats["deleted"] += 1

        # Leere Verzeichnisse aufräumen
        if not dry_run:
            for dirpath in sorted(dest_base.rglob("*"), reverse=True):
                if dirpath.is_dir() and not any(dirpath.iterdir()):
                    dirpath.rmdir()
                    log.debug("Leeres Verzeichnis entfernt: %s", dirpath)

    # State speichern (nur bei echtem Lauf ohne Fehler)
    if not dry_run and stats["errors"] == 0:
        save_state(destination, folder_path, new_state)

    return stats


# ---------------------------------------------------------------------------
# Job-Verarbeitung
# ---------------------------------------------------------------------------

def run_job(job: dict, global_settings: dict) -> bool:
    """Führt einen einzelnen Backup-Job aus."""
    name = job["name"]
    username = job["username"]
    password = job.get("password")
    cookie_directory = job.get("cookie_directory")
    folders = job["folders"]
    destination = job["destination"]
    excludes = job.get("exclude", [])
    dry_run = global_settings.get("dry_run", False)
    full_scan = global_settings.get("full_scan", False)

    log.info("=" * 60)
    log.info("Job: %s", name)
    log.info("=" * 60)

    try:
        api = authenticate(username, password, cookie_directory)
    except SystemExit:
        return False
    except Exception:
        return False

    total_stats = {"downloaded": 0, "deleted": 0, "skipped": 0, "errors": 0}
    for folder in folders:
        stats = sync_folder(api.drive, folder, destination, excludes, dry_run, full_scan)
        for key in total_stats:
            total_stats[key] += stats[key]

    log.info(
        "Job '%s' abgeschlossen: %d heruntergeladen, %d gelöscht, "
        "%d übersprungen, %d Fehler",
        name,
        total_stats["downloaded"],
        total_stats["deleted"],
        total_stats["skipped"],
        total_stats["errors"],
    )

    return total_stats["errors"] == 0


# ---------------------------------------------------------------------------
# Interaktive Modi
# ---------------------------------------------------------------------------

def cmd_auth_only(config: dict, job_filter: str | None = None) -> None:
    """Prüft die Authentifizierung für alle (oder einen) Job(s).

    Führt bei Bedarf die vollständige Anmeldung inkl. Passwort und 2FA durch.
    """
    jobs = config.get("jobs", [])
    if job_filter:
        jobs = [j for j in jobs if j["name"] == job_filter]
    if not jobs:
        print("Keine passenden Jobs gefunden.")
        sys.exit(1)

    for job in jobs:
        username = job["username"]
        cookie_directory = job.get("cookie_directory")
        password = job.get("password")
        print(f"\n--- Authentifizierung: {job['name']} ({username}) ---")
        try:
            api = authenticate(username, password, cookie_directory, interactive=True)
            # Kurzer Test: Drive-Zugriff
            api.drive.dir()
            print(f"Authentifizierung erfolgreich für {username}.")
            print(f"iCloud Drive Zugriff: OK")
        except SystemExit:
            print(f"Authentifizierung fehlgeschlagen für {username}.")
        except Exception as exc:
            print(f"Fehler: {exc}")


def cmd_select_folders(config: dict, config_path: str, job_filter: str | None = None) -> None:
    """Ruft die Top-Level-Ordner ab und lässt den Benutzer auswählen."""
    jobs = config.get("jobs", [])
    if job_filter:
        jobs = [j for j in jobs if j["name"] == job_filter]
    if not jobs:
        print("Keine passenden Jobs gefunden.")
        sys.exit(1)

    changed = False
    for job in jobs:
        username = job["username"]
        cookie_directory = job.get("cookie_directory")
        password = job.get("password")
        print(f"\n--- Ordnerauswahl: {job['name']} ({username}) ---")

        try:
            api = authenticate(username, password, cookie_directory, interactive=True)
        except (SystemExit, Exception) as exc:
            print(f"Authentifizierung fehlgeschlagen: {exc}")
            continue

        print("Lade Top-Level-Ordner von iCloud Drive ...")
        try:
            children = api.drive.root.get_children()
        except Exception as exc:
            print(f"Fehler beim Laden der Ordner: {exc}")
            continue

        folders_available = sorted(
            [c.name for c in children if c.type == "folder"]
        )
        current_folders = set(job.get("folders", []))

        print(f"\nGefundene Ordner ({len(folders_available)}):")
        print("(Enter = aktuellen Wert beibehalten)\n")

        selected = []
        for name in folders_available:
            is_current = name in current_folders
            default = "J" if is_current else "n"
            prompt = f"  {name} [{'J/n' if is_current else 'j/N'}]: "
            answer = input(prompt).strip().lower()
            if not answer:
                # Default beibehalten
                if is_current:
                    selected.append(name)
            elif answer in ("j", "y"):
                selected.append(name)

        if not selected:
            print("Keine Ordner ausgewählt – überspringe.")
            continue

        print(f"\nAusgewählt: {', '.join(selected)}")
        job["folders"] = selected
        changed = True

    if changed:
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True,
                      sort_keys=False)
        print(f"\nconfig.yaml aktualisiert: {config_path}")
    else:
        print("\nKeine Änderungen vorgenommen.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="iCloud Drive Backup – Synchronisiert iCloud Drive Ordner auf ein lokales Zielverzeichnis."
    )
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="Pfad zur Konfigurationsdatei (Standard: config.yaml)",
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Trockenlauf – keine Dateien schreiben oder löschen",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Ausführliche Ausgabe (DEBUG-Level)",
    )
    parser.add_argument(
        "-j", "--job",
        help="Nur einen bestimmten Job ausführen (nach Name)",
    )
    parser.add_argument(
        "--full-scan",
        action="store_true",
        help="Etag-Cache ignorieren und alle Ordner komplett neu scannen",
    )
    parser.add_argument(
        "--auth-only",
        action="store_true",
        help="Nur Authentifizierung prüfen/durchführen (inkl. 2FA), kein Sync",
    )
    parser.add_argument(
        "--select-folders",
        action="store_true",
        help="Top-Level-Ordner von iCloud Drive abrufen und interaktiv auswählen",
    )
    args = parser.parse_args()

    # Log-Level setzen (vor allem für auth-only/select-folders relevant)
    log_level = "DEBUG" if args.verbose else "INFO"
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = load_config(args.config)
    settings = config.get("settings", {})

    if not args.verbose:
        log_level = settings.get("log_level", "INFO")
        logging.getLogger().setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # --- Interaktive Modi ---
    if args.auth_only:
        cmd_auth_only(config, args.job)
        return

    if args.select_folders:
        cmd_select_folders(config, args.config, args.job)
        return

    # --- Normaler Sync-Modus ---
    if args.dry_run:
        settings["dry_run"] = True
    if args.full_scan:
        settings["full_scan"] = True

    if settings.get("dry_run"):
        log.info("*** TROCKENLAUF – es werden keine Änderungen vorgenommen ***")

    jobs = config.get("jobs", [])
    if not jobs:
        log.error("Keine Jobs in der Konfiguration definiert.")
        sys.exit(1)

    # Einzelnen Job filtern
    if args.job:
        jobs = [j for j in jobs if j["name"] == args.job]
        if not jobs:
            log.error("Job '%s' nicht in der Konfiguration gefunden.", args.job)
            sys.exit(1)

    log.info("Starte iCloud Drive Backup (%d Job(s))", len(jobs))

    all_ok = True
    for job in jobs:
        if not run_job(job, settings):
            all_ok = False

    if all_ok:
        log.info("Alle Jobs erfolgreich abgeschlossen.")
    else:
        log.warning("Es gab Fehler bei mindestens einem Job.")
        sys.exit(1)


if __name__ == "__main__":
    main()
