from __future__ import annotations

from .srvctl import load_registry, project_path


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
    """Génère le contenu de .projects.mk à partir du registre
    (srvctl/projects.json). Appelé par `python3 -m srvctl.cli generate-mk`,
    lui-même invoqué par la règle Make `.projects.mk` (voir Makefile).

    Correspondance avec le vocabulaire historique du Makefile :
      web    -> STATIC_PROJECTS      (site statique, `npx serve`)
      webapp -> WEB_PROJECTS         (application Vite)
      custom -> WEB_PROJECTS + CUSTOM_WEB_PROJECTS (cycle de vie sur mesure)
    """
    projects = list(load_registry().values())

    lines: list[str] = [
        "# Fichier généré automatiquement par srvctl (makegen.py).",
        "# NE PAS ÉDITER À LA MAIN : modifier srvctl/projects.json puis",
        "# lancer `make sync` (ou n'importe quelle cible make, qui",
        "# régénère ce fichier tout seul si le registre a changé).",
        "",
    ]
    _block(lines, "PROJECTS", [p["name"] for p in projects])
    _block(lines, "STATIC_PROJECTS", [p["name"] for p in projects if p.get("type") == "web"])
    _block(lines, "WEB_PROJECTS", [p["name"] for p in projects if p.get("type") in ("webapp", "custom")])
    _block(lines, "CUSTOM_WEB_PROJECTS", [p["name"] for p in projects if p.get("type") == "custom"])
    _block(lines, "VERCEL_PROJECTS", [p["name"] for p in projects if p.get("vercel")])

    lines.append("# Port de chaque projet — source : projects.json.")
    for p in projects:
        lines.append(f"PROJECT_PORT_{p['name']} := {p.get('port') or ''}")
    lines.append("")

    lines.append("# Chemin de chaque projet (PROJECT_DIR_<nom>) — PROJECT_DIR = $(PROJECT_DIR_$(PROJECT)).")
    for p in projects:
        lines.append(f"PROJECT_DIR_{p['name']} := {project_path(p)}")
    lines.append("")

    return "\n".join(lines) + "\n"
