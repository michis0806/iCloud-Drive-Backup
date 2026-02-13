"""Setup Web UI – Browser-basierte iCloud-Authentifizierung (inkl. 2FA).

Ermöglicht die Erstanmeldung und Token-Erneuerung über eine einfache
Web-Oberfläche, ohne dass SSH-Zugriff benötigt wird.
"""

import logging
import os
import threading
from pathlib import Path

import yaml
from flask import Flask, request, redirect, url_for, render_template_string

log = logging.getLogger("setup-web")

app = Flask(__name__)
app.secret_key = os.urandom(24)

CONFIG_FILE = os.environ.get("CONFIG_FILE", "/config/config.yaml")

# Zwischenspeicher für laufende 2FA-Flows: job_name -> PyiCloudService
_pending = {}
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _load_jobs():
    """Lädt die Jobs aus der config.yaml."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return cfg.get("jobs", [])
    except Exception as exc:
        log.error("Config nicht lesbar: %s", exc)
        return []


def _cookie_dir(job):
    return os.path.expanduser(job.get("cookie_directory", "~/.pyicloud"))


def _has_session(job):
    """Prüft ob eine Session-Datei für diesen Job existiert."""
    cookie_dir = _cookie_dir(job)
    username = job["username"]
    normalized = "".join(c for c in username if c.isalnum() or c == "_")
    return (Path(cookie_dir) / f"{normalized}.session").exists()


def _find_job(name):
    """Findet einen Job anhand seines Namens."""
    for job in _load_jobs():
        if job["name"] == name:
            return job
    return None


# ---------------------------------------------------------------------------
# HTML / CSS
# ---------------------------------------------------------------------------

_CSS = """\
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #f5f5f7; color: #1d1d1f; min-height: 100vh;
}
.wrap { max-width: 560px; margin: 0 auto; padding: 32px 16px; }
h1 { font-size: 1.4rem; margin-bottom: 24px; text-align: center; }
.card {
  background: #fff; border-radius: 12px; padding: 20px;
  margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.08);
}
.card h2 { font-size: 1.05rem; margin-bottom: 2px; }
.sub { color: #86868b; font-size: .85rem; margin-bottom: 12px; }
.badge {
  display: inline-block; padding: 3px 10px; border-radius: 12px;
  font-size: .78rem; font-weight: 600;
}
.badge.ok  { background: #d4edda; color: #155724; }
.badge.warn { background: #fff3cd; color: #856404; }
.btn {
  display: inline-block; padding: 10px 20px; border: none; border-radius: 8px;
  font-size: .9rem; cursor: pointer; text-decoration: none; font-weight: 500;
}
.btn-primary { background: #0071e3; color: #fff; }
.btn-primary:hover { background: #0077ed; }
.row {
  display: flex; justify-content: space-between; align-items: center;
  flex-wrap: wrap; gap: 8px;
}
input[type=password], input[type=text] {
  width: 100%; padding: 12px; border: 1px solid #d2d2d7;
  border-radius: 8px; font-size: 1rem; margin-bottom: 12px;
}
input:focus {
  outline: none; border-color: #0071e3;
  box-shadow: 0 0 0 3px rgba(0,113,227,.15);
}
.msg {
  padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; font-size: .88rem;
}
.msg.ok   { background: #d4edda; color: #155724; }
.msg.err  { background: #f8d7da; color: #721c24; }
.msg.info { background: #cce5ff; color: #004085; }
.back {
  display: inline-block; margin-bottom: 16px;
  color: #0071e3; text-decoration: none; font-size: .88rem;
}
label { display: block; font-size: .88rem; font-weight: 500; margin-bottom: 6px; }
.hint { color: #86868b; font-size: .82rem; margin-top: -6px; margin-bottom: 14px; }
"""


def _html(body):
    """Verpackt HTML-Body in ein vollständiges Dokument mit CSS."""
    return (
        '<!DOCTYPE html><html lang="de"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>iCloud Backup – Setup</title>"
        f"<style>{_CSS}</style>"
        '</head><body><div class="wrap">'
        "<h1>iCloud Drive Backup</h1>"
        f"{body}"
        "</div></body></html>"
    )


# ---------------------------------------------------------------------------
# Routen
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    jobs = _load_jobs()
    for j in jobs:
        j["has_session"] = _has_session(j)
    msg = request.args.get("msg", "")
    msg_type = request.args.get("t", "ok")

    body = render_template_string(
        '{% if msg %}<div class="msg {{ t }}">{{ msg }}</div>{% endif %}'
        "{% if not jobs %}"
        '<div class="card"><p>Keine Jobs in der Konfiguration gefunden.</p>'
        '<p class="sub" style="margin-top:8px">'
        "Erstelle eine config.yaml und starte den Container neu.</p></div>"
        "{% else %}"
        "{% for job in jobs %}"
        '<div class="card">'
        '<div class="row">'
        "<div><h2>{{ job.name }}</h2>"
        '<div class="sub">{{ job.username }}</div></div>'
        '<span class="badge {{ \'ok\' if job.has_session else \'warn\' }}">'
        "{{ 'Token vorhanden' if job.has_session else 'Nicht angemeldet' }}"
        "</span></div>"
        '<a href="{{ url_for(\'auth_page\', job_name=job.name) }}" '
        'class="btn btn-primary">Anmelden</a>'
        "</div>"
        "{% endfor %}"
        "{% endif %}",
        jobs=jobs, msg=msg, t=msg_type,
    )
    return _html(body)


@app.route("/auth/<job_name>")
def auth_page(job_name):
    job = _find_job(job_name)
    if not job:
        return redirect(url_for("index", msg="Job nicht gefunden", t="err"))

    error = request.args.get("error", "")
    body = render_template_string(
        '<a class="back" href="{{ url_for(\'index\') }}">&larr; Zurück</a>'
        '<div class="card">'
        "<h2>{{ name }}</h2>"
        '<div class="sub">{{ username }}</div>'
        '{% if error %}<div class="msg err">{{ error }}</div>{% endif %}'
        '<form method="post" action="{{ url_for(\'auth_login\', job_name=name) }}">'
        '<label for="pw">Apple-ID Passwort</label>'
        '<input type="password" id="pw" name="password" '
        'placeholder="Passwort" required autofocus>'
        '<button type="submit" class="btn btn-primary" style="width:100%">'
        "Anmelden</button></form></div>",
        name=job_name, username=job["username"], error=error,
    )
    return _html(body)


@app.route("/auth/<job_name>/login", methods=["POST"])
def auth_login(job_name):
    job = _find_job(job_name)
    if not job:
        return redirect(url_for("index", msg="Job nicht gefunden", t="err"))

    password = request.form.get("password", "")
    if not password:
        return redirect(url_for("auth_page", job_name=job_name,
                                error="Bitte Passwort eingeben."))

    try:
        from pyicloud import PyiCloudService
        api = PyiCloudService(
            apple_id=job["username"],
            password=password,
            cookie_directory=_cookie_dir(job),
        )
    except Exception as exc:
        log.error("Login fehlgeschlagen für %s: %s", job["username"], exc)
        return redirect(url_for("auth_page", job_name=job_name,
                                error=f"Anmeldung fehlgeschlagen: {exc}"))

    if api.requires_2fa:
        with _lock:
            _pending[job_name] = api
        return redirect(url_for("tfa_page", job_name=job_name))

    # Kein 2FA nötig – direkt fertig
    return redirect(url_for("index",
                            msg=f"Anmeldung erfolgreich für {job['username']}!",
                            t="ok"))


@app.route("/auth/<job_name>/2fa")
def tfa_page(job_name):
    job = _find_job(job_name)
    if not job:
        return redirect(url_for("index", msg="Job nicht gefunden", t="err"))

    with _lock:
        if job_name not in _pending:
            return redirect(url_for("auth_page", job_name=job_name))

    error = request.args.get("error", "")
    body = render_template_string(
        '<a class="back" href="{{ url_for(\'index\') }}">&larr; Zurück</a>'
        '<div class="card">'
        "<h2>{{ name }}</h2>"
        '<div class="sub">{{ username }}</div>'
        '<div class="msg info">'
        "Ein Bestätigungscode wurde an deine Apple-Geräte gesendet.</div>"
        '{% if error %}<div class="msg err">{{ error }}</div>{% endif %}'
        '<form method="post" action="{{ url_for(\'auth_verify\', job_name=name) }}">'
        '<label for="code">Bestätigungscode</label>'
        '<input type="text" id="code" name="code" '
        'placeholder="6-stelliger Code" pattern="[0-9]{6}" '
        'maxlength="6" inputmode="numeric" autocomplete="one-time-code" '
        "required autofocus>"
        '<p class="hint">Prüfe dein iPhone, iPad oder deinen Mac.</p>'
        '<button type="submit" class="btn btn-primary" style="width:100%">'
        "Bestätigen</button></form></div>",
        name=job_name, username=job["username"], error=error,
    )
    return _html(body)


@app.route("/auth/<job_name>/verify", methods=["POST"])
def auth_verify(job_name):
    job = _find_job(job_name)
    if not job:
        return redirect(url_for("index", msg="Job nicht gefunden", t="err"))

    with _lock:
        api = _pending.get(job_name)
    if not api:
        return redirect(url_for("auth_page", job_name=job_name))

    code = request.form.get("code", "").strip()
    if not code:
        return redirect(url_for("tfa_page", job_name=job_name,
                                error="Bitte Code eingeben."))

    try:
        if not api.validate_2fa_code(code):
            return redirect(url_for("tfa_page", job_name=job_name,
                                    error="Ungültiger Code. Bitte erneut versuchen."))
        api.trust_session()
    except Exception as exc:
        log.error("2FA fehlgeschlagen für %s: %s", job["username"], exc)
        return redirect(url_for("tfa_page", job_name=job_name,
                                error=f"Fehler: {exc}"))
    finally:
        with _lock:
            _pending.pop(job_name, None)

    return redirect(url_for(
        "index",
        msg=f"Authentifizierung erfolgreich für {job['username']}! Token gespeichert.",
        t="ok",
    ))


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def run(host="0.0.0.0", port=8080):
    """Startet die Setup Web UI."""
    log.info("Setup Web UI gestartet: http://%s:%d", host, port)
    # Werkzeug-Banner unterdrücken
    wlog = logging.getLogger("werkzeug")
    wlog.setLevel(logging.WARNING)
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    run(port=int(os.environ.get("SETUP_PORT", "8080")))
