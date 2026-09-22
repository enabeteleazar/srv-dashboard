from __future__ import annotations

import argparse
import secrets
import sys

from . import makegen
from .discovery import detect_type, next_free_port, root_path, scan_dirs
from .gitgh import init_git_and_github_repo
from .models import ProjectEntry
from .registry import get_root, load_registry, save_registry
from .status import git_status, port_is_up
from .vercel import is_linked, link as vercel_link


def env_key(name: str) -> str:
    """Reproduit exactement `tr '[:lower:].-' '[:upper:]__'` du Makefile :
    lettres -> majuscules, '.' et '-' -> '_', le reste inchangé."""
    out = []
    for c in name:
        if c.isalpha():
            out.append(c.upper())
        elif c in ".-":
            out.append("_")
        else:
            out.append(c)
    return "".join(out)


def _sync_env(added: list[ProjectEntry]) -> None:
    """Ajoute <KEY>_PORT / <KEY>_TYPE dans /srv/.env pour les projets
    fraîchement ajoutés — n'écrase jamais une clé déjà présente."""
    if not added:
        return
    env_path = get_root() / ".env"
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    to_add = []
    for entry in added:
        key = env_key(entry.name)
        if f"{key}_PORT=" not in existing:
            to_add.append(f"{key}_PORT={entry.port}")
        if f"{key}_TYPE=" not in existing:
            to_add.append(f"{key}_TYPE={entry.type}")
    if not to_add:
        return
    with env_path.open("a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write("\n".join(to_add) + "\n")


def _write_mk() -> None:
    (get_root() / ".projects.mk").write_text(makegen.generate(), encoding="utf-8")


def cmd_sync(args: argparse.Namespace) -> None:
    reg = load_registry()
    added: list[ProjectEntry] = []
    for root in ("projects", "personal", "neron"):
        for dirname in scan_dirs(root):
            if reg.get(dirname):
                continue
            project_dir = root_path(root) / dirname
            ptype = detect_type(project_dir)
            port = next_free_port(reg.used_ports())
            entry = ProjectEntry(name=dirname, root=root, type=ptype, port=port, vercel=(root == "projects"))
            reg.upsert(entry)
            added.append(entry)
            print(f"+ {dirname}: type={ptype} port={port} root={root} vercel={entry.vercel}")

    if not added:
        print("Rien de nouveau à synchroniser.")
        _write_mk()
        return

    save_registry(reg)
    _sync_env(added)
    _write_mk()

    registry_changed = False
    for entry in added:
        project_dir = root_path(entry.root) / entry.name
        if not args.no_git:
            res = init_git_and_github_repo(project_dir, entry.name, visibility=args.visibility)
            print(f"  git/github {entry.name}: {res}")
            if res.get("github_repo"):
                entry.github_repo = res["github_repo"]
                reg.upsert(entry)
                registry_changed = True
        if entry.vercel and not args.no_vercel:
            res = vercel_link(project_dir)
            print(f"  vercel {entry.name}: {res}")
    if registry_changed:
        save_registry(reg)


def cmd_add(args: argparse.Namespace) -> None:
    reg = load_registry()
    if reg.get(args.name):
        print(f"'{args.name}' est déjà enregistré (voir projects.json).")
        return
    project_dir = root_path(args.root) / args.name
    if not project_dir.exists():
        print(f"ERREUR: {project_dir} n'existe pas — crée le dossier d'abord.")
        sys.exit(1)
    ptype = args.type or detect_type(project_dir)
    port = args.port or next_free_port(reg.used_ports())
    vercel = args.vercel if args.vercel is not None else (args.root == "projects")
    entry = ProjectEntry(name=args.name, root=args.root, type=ptype, port=port, vercel=vercel)
    reg.upsert(entry)
    save_registry(reg)
    _sync_env([entry])
    _write_mk()
    print(f"+ {entry.name}: type={ptype} port={port} root={args.root} vercel={vercel}")

    if not args.no_git:
        res = init_git_and_github_repo(project_dir, entry.name, visibility=args.visibility)
        print(f"  git/github: {res}")
        if res.get("github_repo"):
            entry.github_repo = res["github_repo"]
            reg.upsert(entry)
            save_registry(reg)
    if entry.vercel and not args.no_vercel:
        res = vercel_link(project_dir)
        print(f"  vercel: {res}")


def cmd_list(args: argparse.Namespace) -> None:
    reg = load_registry()
    print(f"{'PROJET':<14} {'ROOT':<10} {'TYPE':<8} {'PORT':<6} {'VERCEL':<7} {'GITHUB'}")
    print("-" * 70)
    for p in reg.projects:
        print(
            f"{p.name:<14} {p.root:<10} {p.type:<8} "
            f"{str(p.port or '-'):<6} {('oui' if p.vercel else '-'):<7} {p.github_repo or '-'}"
        )


def cmd_status(args: argparse.Namespace) -> None:
    reg = load_registry()
    print(f"{'PROJET':<14} {'PORT':<6} {'ETAT':<6} {'GIT':<10} {'VERCEL'}")
    print("-" * 60)
    for p in reg.projects:
        project_dir = root_path(p.root) / p.name
        up = port_is_up(p.port) if p.port else False
        gs = git_status(project_dir)
        git_str = "pas-git" if not gs.get("tracked") else ("modifie" if gs.get("dirty") else "propre")
        vercel_str = "-" if not p.vercel else ("lie" if is_linked(project_dir) else "non-lie")
        print(f"{p.name:<14} {str(p.port or '-'):<6} {('UP' if up else 'DOWN'):<6} {git_str:<10} {vercel_str}")


def cmd_generate_mk(args: argparse.Namespace) -> None:
    sys.stdout.write(makegen.generate())


def cmd_import_env(args: argparse.Namespace) -> None:
    """Back-fill port/type dans projects.json depuis un .env existant —
    utile juste après avoir posé le fichier projects.json fourni en
    exemple, pour récupérer les ports déjà en service."""
    reg = load_registry()
    env_path = get_root() / ".env"
    if not env_path.exists():
        print("Pas de .env trouvé, rien à importer.")
        return
    env: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    changed = False
    for p in reg.projects:
        key = env_key(p.name)
        port_val = env.get(f"{key}_PORT")
        type_val = env.get(f"{key}_TYPE")
        if port_val and not p.port:
            p.port = int(port_val)
            changed = True
            print(f"  {p.name}: port importé depuis .env = {p.port}")
        if type_val and type_val != p.type:
            print(f"  {p.name}: type projects.json='{p.type}' vs .env='{type_val}' (laissé tel quel, à vérifier à la main)")
    if changed:
        save_registry(reg)
        _write_mk()
        print("projects.json et .projects.mk mis à jour.")
    else:
        print("Rien à importer.")


API_TOKEN_KEY = "DASHBOARD_API_TOKEN"


def cmd_api_token(args: argparse.Namespace) -> None:
    """Génère (ou affiche) le jeton Bearer de l'API du dashboard, stocké
    dans /srv/.env sous DASHBOARD_API_TOKEN — c'est ce que Neron envoie
    dans l'en-tête Authorization."""
    env_path = get_root() / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    existing = None
    for line in lines:
        if line.strip().startswith(f"{API_TOKEN_KEY}="):
            existing = line.split("=", 1)[1].strip().strip("\"'") or None

    if existing and not args.rotate:
        print(f"{API_TOKEN_KEY} déjà défini dans {env_path} :")
        print(existing)
        print("\n(`--rotate` pour en générer un nouveau — Neron devra être mis à jour.)")
        return

    token = secrets.token_urlsafe(32)
    if existing:
        lines = [
            f"{API_TOKEN_KEY}={token}" if line.strip().startswith(f"{API_TOKEN_KEY}=") else line
            for line in lines
        ]
    else:
        lines.append(f"{API_TOKEN_KEY}={token}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        env_path.chmod(0o600)
    except OSError:
        pass
    print(f"{'Nouveau jeton' if existing else 'Jeton'} écrit dans {env_path} :")
    print(token)
    print("\nÀ donner à Neron, par exemple :")
    print(f'  curl -H "Authorization: Bearer {token}" -H "X-Client: neron" \\')
    print("       http://127.0.0.1:5199/api/v1/projects")
    print("\nRedémarre le dashboard si tu le lances avec une variable d'environnement figée.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="srvctl", description="Gestion automatisée des projets sous /srv")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="Scanne projects/personal/neron et enregistre les nouveaux projets")
    p_sync.add_argument("--no-git", action="store_true", help="Ne pas faire git init / gh repo create")
    p_sync.add_argument("--no-vercel", action="store_true", help="Ne pas faire vercel link")
    p_sync.add_argument("--visibility", choices=["public", "private"], default="public")
    p_sync.set_defaults(func=cmd_sync)

    p_add = sub.add_parser("add", help="Ajoute explicitement un projet déjà présent sur disque")
    p_add.add_argument("name")
    p_add.add_argument("--root", choices=["projects", "personal", "neron"], default="projects")
    p_add.add_argument("--type", choices=["static", "vite", "custom"], default=None)
    p_add.add_argument("--port", type=int, default=None)
    p_add.add_argument(
        "--vercel", dest="vercel", action="store_true", default=None,
        help="Force l'inclusion dans VERCEL_PROJECTS (par défaut : oui si --root=projects)",
    )
    p_add.add_argument(
        "--exclude-vercel", dest="vercel", action="store_false",
        help="Force l'exclusion de VERCEL_PROJECTS même si --root=projects",
    )
    p_add.add_argument("--no-git", action="store_true", help="Ne pas faire git init / gh repo create")
    p_add.add_argument("--no-vercel", dest="no_vercel", action="store_true", help="Ne pas lancer vercel link maintenant")
    p_add.add_argument("--visibility", choices=["public", "private"], default="public")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="Liste les projets connus (projects.json)")
    p_list.set_defaults(func=cmd_list)

    p_status = sub.add_parser("status", help="Statut live (port up/down, git, vercel)")
    p_status.set_defaults(func=cmd_status)

    p_mk = sub.add_parser("generate-mk", help="Génère .projects.mk sur stdout")
    p_mk.set_defaults(func=cmd_generate_mk)

    p_import = sub.add_parser("import-env", help="Back-fill port/type dans projects.json depuis .env")
    p_import.set_defaults(func=cmd_import_env)

    p_token = sub.add_parser("api-token", help="Génère/affiche le jeton Bearer de l'API (DASHBOARD_API_TOKEN)")
    p_token.add_argument("--rotate", action="store_true", help="Remplace le jeton existant par un nouveau")
    p_token.set_defaults(func=cmd_api_token)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
