from __future__ import annotations

from .discovery import root_path
from .registry import load_registry


def _block(lines: list[str], varname: str, names: list[str]) -> None:
    if not names:
        lines.append(f"{varname} :=")
        lines.append("")
        return
    lines.append(f"{varname} := \\")
    for i, n in enumerate(names):
        sep = " \\" if i < len(names) - 1 else ""
        lines.append(f"\t{n}{sep}")
    lines.append("")


def generate() -> str:
    """Génère le contenu de .projects.mk à partir de /srv/projects.json.
    Appelé par `python3 -m srvctl.cli generate-mk`, lui-même invoqué par
    la règle Make `.projects.mk: projects.json` (voir Makefile)."""
    reg = load_registry()
    projects = reg.projects

    lines: list[str] = [
        "# Fichier généré automatiquement par srvctl (makegen.py).",
        "# NE PAS ÉDITER À LA MAIN : modifier /srv/projects.json puis",
        "# lancer `make sync` (ou n'importe quelle cible make, qui",
        "# régénère ce fichier tout seul si projects.json a changé).",
        "",
    ]
    _block(lines, "PROJECTS", [p.name for p in projects])
    _block(lines, "STATIC_PROJECTS", [p.name for p in projects if p.type == "static"])
    _block(lines, "WEB_PROJECTS", [p.name for p in projects if p.type in ("vite", "custom")])
    _block(lines, "CUSTOM_WEB_PROJECTS", [p.name for p in projects if p.type == "custom"])
    _block(lines, "VERCEL_PROJECTS", [p.name for p in projects if p.vercel])

    lines.append("# Chemin de chaque projet (PROJECT_DIR_<nom>) — PROJECT_DIR = $(PROJECT_DIR_$(PROJECT)).")
    for p in projects:
        path = root_path(p.root) / p.name
        lines.append(f"PROJECT_DIR_{p.name} := {path}")
    lines.append("")

    return "\n".join(lines) + "\n"
