#!/usr/bin/env python3

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


# Le dépôt est autonome : tout est relatif à ce fichier, plus aucun chemin
# /srv/dashboard en dur. Le registre vit à côté du code (projects.json) ;
# SRV_REGISTRY permet de le surcharger (tests, déploiement ailleurs).
BASE_DIR = Path(__file__).resolve().parent
REGISTRY_FILE = Path(os.environ.get("SRV_REGISTRY") or BASE_DIR / "projects.json")
LOG_DIR = BASE_DIR / "logs"
PID_DIR = BASE_DIR / "pids"

# Racine du serveur — surchargeable via SRV_ROOT (même variable que le Makefile).
SERVER_ROOT = Path(os.environ.get("SRV_ROOT") or "/srv")

# Nom de la racine logique -> dossier réel sous SERVER_ROOT.
# Attention : sous Linux la casse compte, le dossier est /srv/Neron.
ROOT_DIRS = {
    "projects": SERVER_ROOT / "projects",
    "personal": SERVER_ROOT / "personal",
    "neron": SERVER_ROOT / "Neron",
}

# Plages de ports par racine (le port du dashboard est exclu, voir next_free_port).
DEFAULT_PORT_RANGE = range(5180, 5300)
NERON_PORT_RANGE = range(8000, 8100)

PROJECT_TYPES = ("web", "webapp", "custom")


def get_root():
    return SERVER_ROOT


def root_path(root):
    try:
        return ROOT_DIRS[root]
    except KeyError:
        raise ValueError(f"Racine inconnue : {root}")


def project_path(project):
    path = project.get("path")
    if path:
        return Path(path)
    return root_path(project["root"]) / project["name"]



LOG_DIR.mkdir(parents=True, exist_ok=True)
PID_DIR.mkdir(parents=True, exist_ok=True)


def load_registry():
    if not REGISTRY_FILE.exists():
        return {}

    with REGISTRY_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    projects = data.get("projects", [])
    return {p["name"]: p for p in projects}


def save_registry(projects):
    ordered = sorted(
        projects.values(),
        key=lambda p: (p.get("port") is None, p.get("port") or 0, p["name"]),
    )

    with REGISTRY_FILE.open("w", encoding="utf-8") as f:
        json.dump({"projects": ordered}, f, indent=2, ensure_ascii=False)
        f.write("\n")


def next_free_port(root):
    port_range = NERON_PORT_RANGE if root == "neron" else DEFAULT_PORT_RANGE

    used = {
        int(project["port"])
        for project in load_registry().values()
        if project.get("port") is not None
    }

    try:
        reserved = {int(os.environ.get("DASHBOARD_PORT", "5199"))}
    except ValueError:
        reserved = {5199}

    used |= reserved

    for port in port_range:
        if port not in used:
            return port

    raise RuntimeError(
        f"Aucun port libre dans {port_range.start}-{port_range.stop - 1}"
    )


def start_command(project_type, port):
    if project_type == "web":
        return f"npx serve . -l {port} --no-clipboard"

    if project_type == "webapp":
        return f"pnpm dev --host 0.0.0.0 --port {port}"

    if project_type == "custom":
        raise ValueError(
            "Un projet custom doit fournir une commande start explicite"
        )

    raise ValueError(f"Type inconnu: {project_type}")


def make_entry(name, root, project_type, port, start, vercel=True,
               visibility="public", github_repo=None, git=False):
    """Entrée de registre complète — utilisée par create_project et par cli.py,
    pour que tous les chemins de création produisent le même format."""
    return {
        "name": name,
        "path": str(root_path(root) / name),
        "type": project_type,
        "port": port,
        "start": start,
        "root": root,
        "vercel": bool(vercel),
        "description": "",
        "status": "active",
        "priority": "normal",
        "notes": "",
        "github_repo": github_repo,
        "git": bool(git),
        "vercel_enabled": bool(vercel),
        "visibility": visibility,
    }


def create_project(name, root="projects", project_type="web", start=None,
                   vercel=True, visibility="public"):
    name = (name or "").strip()

    if not name:
        raise ValueError("Nom de projet vide")

    if root not in ROOT_DIRS:
        raise ValueError(f"Racine inconnue: {root}")

    if project_type not in ("web", "webapp", "custom"):
        raise ValueError(f"Type inconnu: {project_type}")

    if visibility not in ("public", "private"):
        raise ValueError(f"Visibilité inconnue: {visibility}")

    projects = load_registry()

    if name in projects:
        raise ValueError(f"{name} est déjà enregistré")

    project_dir = root_path(root) / name
    project_dir.mkdir(parents=True, exist_ok=True)

    port = next_free_port(root)

    if project_type == "custom" and not start:
        raise ValueError(
            "Un projet custom nécessite une commande start explicite"
        )

    command = start or start_command(project_type, port)

    entry = make_entry(
        name, root, project_type, port, command,
        vercel=vercel, visibility=visibility,
    )

    projects[name] = entry
    save_registry(projects)

    return entry

def get_project(name):
    projects = load_registry()

    if name not in projects:
        print(f"Projet inconnu: {name}", file=sys.stderr)
        print("Projets disponibles:", file=sys.stderr)
        for project in projects.values():
            print(f"  {project['name']}", file=sys.stderr)
        raise SystemExit(1)

    return projects[name]


def pid_file(project):
    return PID_DIR / f"{project['name']}.pid"


def log_file(project):
    return LOG_DIR / f"{project['name']}.log"


def read_pid(project):
    path = pid_file(project)

    if not path.exists():
        return None

    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return None


def process_exists(pid):
    if not pid:
        return False

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def port_is_open(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)

    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def status(project):
    pid = read_pid(project)
    running = process_exists(pid)

    if running:
        return "running", pid

    if pid_file(project).exists():
        try:
            pid_file(project).unlink()
        except OSError:
            pass

    if port_is_open(project["port"]):
        return "port-active", None

    return "stopped", None


def cmd_list(_args):
    projects = load_registry()

    print(f"{'PROJECT':30} {'TYPE':10} {'PORT':6} STATUS")
    print("-" * 65)

    for project in projects.values():
        state, pid = status(project)
        suffix = f" pid={pid}" if pid else ""
        print(
            f"{project['name']:30} "
            f"{project['type']:10} "
            f"{project['port']:<6} "
            f"{state}{suffix}"
        )


def cmd_status(args):
    project = get_project(args.project)
    state, pid = status(project)

    print(f"Project : {project['name']}")
    print(f"Type    : {project['type']}")
    print(f"Path    : {project['path']}")
    print(f"Port    : {project['port']}")
    print(f"Status  : {state}")

    if pid:
        print(f"PID     : {pid}")

    print(f"Command : {project['start']}")


def cmd_start(args):
    project = get_project(args.project)

    state, pid = status(project)

    if state == "running":
        print(f"{project['name']} déjà démarré (PID {pid})")
        return

    project_path = Path(project["path"])

    if not project_path.is_dir():
        print(f"Répertoire introuvable: {project_path}", file=sys.stderr)
        raise SystemExit(1)

    if port_is_open(project["port"]):
        print(
            f"Le port {project['port']} est déjà utilisé.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    log = log_file(project)

    print(f"Starting {project['name']}...")
    print(f"  type : {project['type']}")
    print(f"  path : {project_path}")
    print(f"  port : {project['port']}")
    print(f"  cmd  : {project['start']}")
    print(f"  log  : {log}")

    with log.open("a", encoding="utf-8") as output:
        output.write(
            f"\n=== START {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
        )

        process = subprocess.Popen(
            project["start"],
            cwd=project_path,
            shell=True,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            executable="/bin/bash",
        )

    pid_file(project).write_text(str(process.pid), encoding="utf-8")

    time.sleep(1)

    if process.poll() is not None:
        print(
            f"Échec du démarrage de {project['name']}. "
            f"Voir {log}",
            file=sys.stderr,
        )
        try:
            pid_file(project).unlink()
        except OSError:
            pass
        raise SystemExit(1)

    print(f"{project['name']} démarré (PID {process.pid})")


def cmd_stop(args):
    project = get_project(args.project)

    state, pid = status(project)

    if state != "running" or not pid:
        print(f"{project['name']} n'est pas démarré")
        return

    print(f"Stopping {project['name']} (PID {pid})...")

    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    for _ in range(30):
        if not process_exists(pid):
            break
        time.sleep(0.2)

    if process_exists(pid):
        print("Processus encore actif, SIGKILL...")
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    try:
        pid_file(project).unlink()
    except OSError:
        pass

    print(f"{project['name']} arrêté")


def cmd_restart(args):
    cmd_stop(args)
    cmd_start(args)


def cmd_logs(args):
    project = get_project(args.project)
    log = log_file(project)

    if not log.exists():
        print(f"Aucun log pour {project['name']}")
        return

    if args.follow:
        subprocess.run(["tail", "-n", str(args.lines), "-f", str(log)])
    else:
        subprocess.run(["tail", "-n", str(args.lines), str(log)])


def cmd_sync(_args):
    projects = load_registry()

    for project in projects.values():
        path = Path(project["path"])

        if not path.is_dir():
            print(f"[WARN] {project['name']}: répertoire absent")
            continue

        print(
            f"[OK] {project['name']}: "
            f"type={project['type']} "
            f"port={project['port']}"
        )

    save_registry(projects)
    print(f"\nRegistry: {REGISTRY_FILE}")


def main():
    parser = argparse.ArgumentParser(
        prog="srvctl",
        description="Gestionnaire central des projets /srv",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="Lister les projets")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("status", help="État d'un projet")
    p.add_argument("project")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("start", help="Démarrer un projet")
    p.add_argument("project")
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("stop", help="Arrêter un projet")
    p.add_argument("project")
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("restart", help="Redémarrer un projet")
    p.add_argument("project")
    p.set_defaults(func=cmd_restart)

    p = sub.add_parser("logs", help="Afficher les logs")
    p.add_argument("project")
    p.add_argument("-f", "--follow", action="store_true")
    p.add_argument("-n", "--lines", type=int, default=50)
    p.set_defaults(func=cmd_logs)

    p = sub.add_parser("sync", help="Vérifier le registre")
    p.set_defaults(func=cmd_sync)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
