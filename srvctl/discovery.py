from __future__ import annotations

import json
import os
from pathlib import Path

from .models import ProjectType
from .registry import get_root

ROOT_DIRS = {
    "projects": "projects",
    "personal": "personal",
    "neron": "neron",
}

DEFAULT_PORT_RANGE = range(5180, 5200)


def root_path(root: str) -> Path:
    return get_root() / ROOT_DIRS[root]


def scan_dirs(root: str) -> list[str]:
    """Liste les dossiers de premier niveau sous un des trois racines
    connues (projects/personal/neron), en ignorant les dossiers cachés."""
    p = root_path(root)
    if not p.exists():
        return []
    return sorted(d.name for d in p.iterdir() if d.is_dir() and not d.name.startswith("."))


def detect_type(project_dir: Path) -> ProjectType:
    """static  : pas de package.json (site statique servi tel quel)
    vite    : dépendance/script vite détecté
    custom  : package.json avec un script dev/build/serve mais pas vite
              (cycle de vie sur mesure, comme wwdc26Bingo/oraneCoatch —
              nécessite une branche dédiée dans dev-project/start-project)
    """
    pkg = project_dir / "package.json"
    if not pkg.exists():
        return "static"
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "static"
    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    scripts = data.get("scripts", {})
    if "vite" in deps or any("vite" in str(v) for v in scripts.values()):
        return "vite"
    if scripts.get("dev") or scripts.get("build") or scripts.get("serve"):
        return "custom"
    return "static"


def reserved_ports() -> set[int]:
    """Ports à ne jamais attribuer à un projet : celui du dashboard
    (DASHBOARD_PORT, 5199 par défaut — il tombe dans la plage 5180-5199)."""
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
        "— élargis DEFAULT_PORT_RANGE dans srvctl/discovery.py"
    )
