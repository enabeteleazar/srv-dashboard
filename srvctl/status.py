from __future__ import annotations

import socket
import subprocess
from pathlib import Path


def port_is_up(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def git_status(project_dir: Path) -> dict:
    if not (project_dir / ".git").exists():
        return {"tracked": False}
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=project_dir,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        porcelain = subprocess.run(
            ["git", "status", "--porcelain"], cwd=project_dir,
            capture_output=True, text=True, check=True,
        ).stdout
        n = len([line for line in porcelain.splitlines() if line.strip()])
        return {"tracked": True, "branch": branch, "dirty": n > 0, "changes": n}
    except (subprocess.CalledProcessError, OSError):
        return {"tracked": True, "error": True}


_SEP = "\x1f"  # séparateur d'unités ASCII : ne peut pas apparaître dans un message de commit normal


def recent_commits(project_dir: Path, limit: int = 10) -> list[dict]:
    """Derniers commits de la branche courante (hash court, auteur, date ISO, sujet).
    Liste vide si pas de dépôt ou dépôt sans commit."""
    if not (project_dir / ".git").exists():
        return []
    fmt = _SEP.join(["%H", "%h", "%an", "%aI", "%s"])
    try:
        out = subprocess.run(
            ["git", "log", f"-n{int(limit)}", f"--pretty=format:{fmt}"],
            cwd=project_dir, capture_output=True, text=True, check=True, timeout=5,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return []
    commits = []
    for line in out.splitlines():
        parts = line.split(_SEP)
        if len(parts) != 5:
            continue
        full, short, author, date, subject = parts
        commits.append({"hash": full, "short": short, "author": author, "date": date, "subject": subject})
    return commits
