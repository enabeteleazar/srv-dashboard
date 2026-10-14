from __future__ import annotations

import json
import os
from pathlib import Path

from .srvctl import (
    DEFAULT_PORT_RANGE,
    NERON_PORT_RANGE,
    PROJECT_TYPES,
    ROOT_DIRS,
    get_root,
    root_path,
)

__all__ = [
    "DEFAULT_PORT_RANGE",
    "NERON_PORT_RANGE",
    "PROJECT_TYPES",
    "ROOT_DIRS",
    "get_root",
    "root_path",
    "normalize_project_name",
    "scan_dirs",
    "detect_type",
    "reserved_ports",
    "next_free_port",
]

IGNORED_DIRS = {
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    ".next",
    "dist",
    "build",
}


def normalize_project_name(name: str) -> str:
    """Clé de comparaison tolérant la casse et les séparateurs."""
    return "".join(c for c in name.lower() if c.isalnum())


def scan_dirs(root: str) -> list[str]:
    """Liste les dossiers de premier niveau sous une des racines connues
    (projects/personal/neron), en ignorant les dossiers cachés et techniques."""
    p = root_path(root)
    if not p.exists():
        return []
    return sorted(
        d.name
        for d in p.iterdir()
        if d.is_dir()
        and not d.name.startswith(".")
        and d.name not in IGNORED_DIRS
    )


def detect_type(project_dir: Path) -> str:
    """web    : pas de package.json (site statique servi tel quel)
    webapp : dépendance/script vite détecté (application avec serveur de dev)
    custom : package.json avec un script dev/build/serve mais pas vite
             (cycle de vie sur mesure : commande `start` à renseigner à la main)
    """
    pkg = project_dir / "package.json"
    if not pkg.exists():
        return "web"
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "web"
    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    scripts = data.get("scripts", {})
    if "vite" in deps or any("vite" in str(v) for v in scripts.values()):
        return "webapp"
    if scripts.get("dev") or scripts.get("build") or scripts.get("serve"):
        return "custom"
    return "web"


def reserved_ports() -> set[int]:
    """Ports à ne jamais attribuer à un projet : celui du dashboard
    (DASHBOARD_PORT, 5199 par défaut — il tombe dans la plage 5180-5299)."""
    try:
        return {int(os.environ.get("DASHBOARD_PORT", "5199"))}
    except ValueError:
        return {5199}


def next_free_port(used: set[int], port_range=DEFAULT_PORT_RANGE) -> int:
    taken = set(used) | reserved_ports()
    for port in port_range:
        if port not in taken:
            return port
    raise RuntimeError(
        f"Plus aucun port libre dans la plage {port_range.start}-{port_range.stop - 1} "
        "— élargis DEFAULT_PORT_RANGE dans srvctl/srvctl.py"
    )
