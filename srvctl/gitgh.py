from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

GITHUB_ORG = "NABET"


def has_git(project_dir: Path) -> bool:
    return (project_dir / ".git").exists()


def gh_available() -> bool:
    return shutil.which("gh") is not None


def init_git_and_github_repo(project_dir: Path, name: str, visibility: str = "public") -> dict:
    """Initialise git localement puis crée + pousse un repo GitHub sous
    l'org NABET, si ce n'est pas déjà fait. Idempotent : si .git existe
    déjà, ne touche à rien (ne recrée pas le repo, ne force rien)."""
    if has_git(project_dir):
        return {"skipped": True, "reason": ".git déjà présent"}

    result: dict = {}
    try:
        subprocess.run(["git", "init"], cwd=project_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "add", "-A"], cwd=project_dir, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", f"feat({name}): initialisation du projet"],
            cwd=project_dir, check=True, capture_output=True, text=True,
        )
        result["git_init"] = True
    except subprocess.CalledProcessError as exc:
        result["error"] = f"git init a échoué: {exc.stderr.strip() if exc.stderr else exc}"
        return result

    if not gh_available():
        result["error"] = "gh introuvable — dépôt local créé, repo GitHub NON créé (npm/brew install gh puis gh auth login)"
        return result

    repo_slug = f"{GITHUB_ORG}/{name}"
    vis_flag = "--public" if visibility == "public" else "--private"
    try:
        subprocess.run(
            ["gh", "repo", "create", repo_slug, vis_flag, "--source=.", "--remote=origin", "--push"],
            cwd=project_dir, check=True, capture_output=True, text=True,
        )
        result["github_repo"] = repo_slug
    except subprocess.CalledProcessError as exc:
        result["error"] = f"gh repo create a échoué: {exc.stderr.strip() if exc.stderr else exc}"
    return result
