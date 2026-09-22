"""Couche métier du dashboard — partagée par l'interface web et l'API.

Aucune logique de déploiement n'est dupliquée ici : tout passe par le
Makefile (`make <action> <projet>`) ou par `srvctl`. Ce module ajoute
seulement : l'exécution en arrière-plan, le verrou par projet, et
l'enregistrement dans le journal (srvctl.journal).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

# /srv doit être sur sys.path pour `import srvctl` quel que soit le cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from srvctl import journal  # noqa: E402
from srvctl.discovery import root_path  # noqa: E402
from srvctl.models import ProjectEntry  # noqa: E402
from srvctl.registry import get_root, load_registry, save_registry  # noqa: E402
from srvctl.status import git_status, port_is_up, recent_commits  # noqa: E402
from srvctl.vercel import is_linked  # noqa: E402

PROJECT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
VERCEL_URL_RE = re.compile(r"https://[A-Za-z0-9][A-Za-z0-9.-]*\.vercel\.app[^\s\"']*")

ROOTS = ("projects", "personal", "neron")
TYPES = ("static", "vite", "custom")
STATUSES = ("active", "paused", "done", "idea")
PRIORITIES = ("low", "normal", "high")

STATUS_LABELS = {"active": "Actif", "paused": "En pause", "done": "Terminé", "idea": "Idée"}
PRIORITY_LABELS = {"low": "Basse", "normal": "Normale", "high": "Haute"}

# Liste blanche fermée : le dashboard et l'API ne peuvent lancer que ça.
ACTIONS: dict[str, dict] = {
    "start": {"label": "Démarrer", "target": "start", "group": "service"},
    "stop": {"label": "Arrêter", "target": "stop", "group": "service"},
    "restart": {"label": "Redémarrer", "target": "restart", "group": "service"},
    "dev": {"label": "Mode dev", "target": "dev", "group": "service"},
    "build": {"label": "Build", "target": "build", "group": "build"},
    "test": {"label": "Tests", "target": "test", "group": "build"},
    "git-push": {"label": "Git push", "target": "git-push", "group": "git"},
    "vercel-link": {"label": "Lier à Vercel", "target": "vercel-link", "group": "vercel", "vercel": True},
    "deploy": {"label": "Déployer (preview)", "target": "deploy", "group": "vercel", "vercel": True},
    "deploy-prod": {
        "label": "Mettre en production", "target": "deploy-prod", "group": "vercel",
        "vercel": True, "confirm": True,
    },
}

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="srv-action")
_busy: set[str] = set()
_busy_lock = threading.Lock()
_registry_lock = threading.Lock()


class ServiceError(Exception):
    """Erreur métier traduisible en code HTTP (API) ou en message (web)."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# --- lecture --------------------------------------------------------------

def project_dir(entry: ProjectEntry) -> Path:
    return root_path(entry.root) / entry.name


def _entry_or_404(name: str) -> ProjectEntry:
    entry = load_registry().get(name)
    if entry is None:
        raise ServiceError(f"Projet inconnu : {name}", 404)
    return entry


def project_view(entry: ProjectEntry, host: Optional[str] = None, last_activity: Optional[dict] = None) -> dict:
    pdir = project_dir(entry)
    gs = git_status(pdir)
    with _busy_lock:
        busy = entry.name in _busy
    return {
        "name": entry.name,
        "root": entry.root,
        "type": entry.type,
        "port": entry.port,
        "status": entry.status,
        "status_label": STATUS_LABELS.get(entry.status, entry.status),
        "priority": entry.priority,
        "priority_label": PRIORITY_LABELS.get(entry.priority, entry.priority),
        "description": entry.description,
        "notes": entry.notes,
        "vercel_enabled": entry.vercel,
        "vercel_linked": is_linked(pdir) if entry.vercel else None,
        "github_repo": entry.github_repo,
        "github_url": f"https://github.com/{entry.github_repo}" if entry.github_repo else None,
        "path": str(pdir),
        "exists": pdir.exists(),
        "up": port_is_up(entry.port) if entry.port else False,
        "url": f"http://{host}:{entry.port}" if host and entry.port else None,
        "running": busy,
        "git": {
            "tracked": bool(gs.get("tracked")),
            "branch": gs.get("branch"),
            "dirty": bool(gs.get("dirty")),
            "changes": gs.get("changes") or 0,
        },
        "has_log": (get_root() / ".logs" / f"{entry.name}.log").exists(),
        "last_activity": last_activity,
    }


def list_projects(status: Optional[str] = None, root: Optional[str] = None, host: Optional[str] = None) -> list[dict]:
    reg = load_registry()
    latest = journal.latest_by_project()
    out = []
    for entry in reg.projects:
        if status and entry.status != status:
            continue
        if root and entry.root != root:
            continue
        out.append(project_view(entry, host=host, last_activity=latest.get(entry.name)))
    return out


def get_project(name: str, host: Optional[str] = None) -> dict:
    entry = _entry_or_404(name)
    view = project_view(entry, host=host, last_activity=journal.latest_by_project().get(name))
    view["commits"] = recent_commits(project_dir(entry), limit=10)
    view["deployments"] = journal.list_deployments(project=name, limit=20)
    view["activity"] = journal.list_activity(project=name, limit=20)
    view["last_production"] = journal.last_production(name)
    return view


def read_logs(name: str, lines: int = 200) -> str:
    _entry_or_404(name)
    log_path = get_root() / ".logs" / f"{name}.log"
    if not log_path.exists():
        return ""
    content = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-max(1, min(int(lines), 2000)):])


def summary(days: int = 14) -> dict:
    projects = list_projects()
    by_status = {s: 0 for s in STATUSES}
    for p in projects:
        by_status[p["status"]] = by_status.get(p["status"], 0) + 1
    return {
        "total": len(projects),
        "up": sum(1 for p in projects if p["up"]),
        "down": sum(1 for p in projects if not p["up"]),
        "running": sum(1 for p in projects if p["running"]),
        "vercel": sum(1 for p in projects if p["vercel_enabled"]),
        "by_status": by_status,
        "deploys_7d": journal.deployments_since(7),
        "failures_7d": journal.count_since(7, status="error"),
        "actions_7d": journal.count_since(7),
        "activity_daily": journal.daily_counts(days),
    }


# --- exécution ------------------------------------------------------------

def _run(cmd: list[str], timeout: int = 1800) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd, cwd=str(get_root()), capture_output=True, text=True,
            timeout=timeout, env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        return 124, f"[délai dépassé après {timeout}s]"
    except OSError as exc:
        return 127, f"[impossible de lancer {' '.join(cmd)} : {exc}]"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _release(name: Optional[str]) -> None:
    if not name:
        return
    with _busy_lock:
        _busy.discard(name)


def _execute_action(activity_id: int, name: str, action: str) -> dict:
    spec = ACTIONS[action]
    started = time.monotonic()
    try:
        code, output = _run(["make", "--no-print-directory", spec["target"], name])
        duration = int((time.monotonic() - started) * 1000)
        ok = code == 0
        journal.finish_activity(activity_id, ok, code, output, duration)
        if action in ("deploy", "deploy-prod"):
            urls = VERCEL_URL_RE.findall(output)
            journal.record_deployment(
                activity_id, name,
                "production" if action == "deploy-prod" else "preview",
                ok, urls[-1] if urls else None,
            )
    except Exception as exc:  # jamais silencieux : la ligne du journal doit se fermer
        duration = int((time.monotonic() - started) * 1000)
        journal.finish_activity(activity_id, False, None, f"[erreur interne] {exc!r}", duration)
    finally:
        _release(name)
    return journal.get_activity(activity_id)


def run_action(name: str, action: str, source: str = "dashboard", wait: bool = False) -> dict:
    if action not in ACTIONS:
        raise ServiceError(f"Action inconnue : {action}", 422)
    entry = _entry_or_404(name)
    if ACTIONS[action].get("vercel") and not entry.vercel:
        raise ServiceError(f"{name} n'est pas éligible Vercel (vercel=false dans projects.json)", 400)

    with _busy_lock:
        if name in _busy:
            raise ServiceError(f"Une action est déjà en cours sur {name}", 409)
        _busy.add(name)

    activity_id = journal.start_activity(name, action, source)
    if wait:
        return _execute_action(activity_id, name, action)
    try:
        _executor.submit(_execute_action, activity_id, name, action)
    except Exception:
        _release(name)
        journal.finish_activity(activity_id, False, None, "[impossible de démarrer la tâche]", 0)
        raise
    return journal.get_activity(activity_id)


def sync(source: str = "dashboard", wait: bool = True) -> dict:
    activity_id = journal.start_activity(None, "sync", source)

    def _do() -> dict:
        started = time.monotonic()
        code, output = _run([sys.executable, "-m", "srvctl.cli", "sync"], timeout=900)
        journal.finish_activity(activity_id, code == 0, code, output, int((time.monotonic() - started) * 1000))
        return journal.get_activity(activity_id)

    if wait:
        return _do()
    _executor.submit(_do)
    return journal.get_activity(activity_id)


# --- écriture -------------------------------------------------------------

def create_project(
    name: str,
    root: str = "projects",
    type: str = "static",
    git: bool = True,
    vercel: bool = False,
    visibility: str = "public",
    description: str = "",
    status: str = "active",
    priority: str = "normal",
    source: str = "dashboard",
) -> dict:
    name = (name or "").strip()
    if not PROJECT_NAME_RE.match(name):
        raise ServiceError(
            "Nom invalide : doit commencer par une lettre, puis lettres, chiffres, « - », « _ » ou « . »", 422
        )
    if root not in ROOTS:
        raise ServiceError(f"Dossier inconnu : {root}", 422)
    if type not in TYPES:
        raise ServiceError(f"Type inconnu : {type}", 422)
    if status not in STATUSES:
        raise ServiceError(f"Statut inconnu : {status}", 422)
    if priority not in PRIORITIES:
        raise ServiceError(f"Priorité inconnue : {priority}", 422)
    if visibility not in ("public", "private"):
        raise ServiceError(f"Visibilité inconnue : {visibility}", 422)
    if load_registry().get(name):
        raise ServiceError(f"{name} est déjà enregistré", 409)

    target_dir = root_path(root) / name
    is_new_dir = not target_dir.exists()
    target_dir.mkdir(parents=True, exist_ok=True)
    if is_new_dir and type == "static":
        (target_dir / "index.html").write_text(
            "<!doctype html>\n<html lang=\"fr\">\n<head><meta charset=\"utf-8\">"
            f"<title>{name}</title></head>\n<body><h1>{name}</h1>"
            "<p>Nouveau projet créé depuis le dashboard srv.</p></body>\n</html>\n",
            encoding="utf-8",
        )

    activity_id = journal.start_activity(name, "create", source)
    started = time.monotonic()
    cmd = [sys.executable, "-m", "srvctl.cli", "add", name, "--root", root, "--type", type, "--visibility", visibility]
    if not git:
        cmd.append("--no-git")
    if not vercel:
        cmd.append("--exclude-vercel")
    code, output = _run(cmd, timeout=900)
    journal.finish_activity(activity_id, code == 0, code, output, int((time.monotonic() - started) * 1000))
    if code != 0:
        raise ServiceError(f"La création de {name} a échoué — voir l'activité #{activity_id}", 500)

    # Métadonnées de suivi : posées après coup, srvctl ne les connaît pas.
    update_project(name, {"description": description, "status": status, "priority": priority})
    return get_project(name)


def update_project(name: str, changes: dict) -> dict:
    allowed = {"status", "priority", "description", "notes"}
    unknown = set(changes) - allowed
    if unknown:
        raise ServiceError(f"Champ non modifiable : {', '.join(sorted(unknown))}", 422)
    if "status" in changes and changes["status"] not in STATUSES:
        raise ServiceError(f"Statut inconnu : {changes['status']}", 422)
    if "priority" in changes and changes["priority"] not in PRIORITIES:
        raise ServiceError(f"Priorité inconnue : {changes['priority']}", 422)

    with _registry_lock:
        reg = load_registry()
        entry = reg.get(name)
        if entry is None:
            raise ServiceError(f"Projet inconnu : {name}", 404)
        for field, value in changes.items():
            if value is not None:
                setattr(entry, field, value)
        reg.upsert(entry)
        save_registry(reg)
    return get_project(name)
