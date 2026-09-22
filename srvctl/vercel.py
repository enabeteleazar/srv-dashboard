from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def vercel_available() -> bool:
    return shutil.which("vercel") is not None


def is_linked(project_dir: Path) -> bool:
    return (project_dir / ".vercel").exists()


def link(project_dir: Path) -> dict:
    if is_linked(project_dir):
        return {"skipped": True, "reason": "déjà lié"}
    if not vercel_available():
        return {"error": "commande 'vercel' introuvable (npm i -g vercel)"}
    try:
        subprocess.run(
            ["vercel", "link", "--yes"], cwd=project_dir, check=True, capture_output=True, text=True,
        )
        return {"linked": True}
    except subprocess.CalledProcessError as exc:
        return {"error": f"vercel link a échoué: {exc.stderr.strip() if exc.stderr else exc}"}
