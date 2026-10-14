from __future__ import annotations

import argparse
import secrets
import sys

from . import makegen
from .discovery import (
    DEFAULT_PORT_RANGE,
    NERON_PORT_RANGE,
    detect_type,
    next_free_port,
    normalize_project_name,
    scan_dirs,
)
from .gitgh import detect_git_remote, init_git_and_github_repo
from .srvctl import (
    PROJECT_TYPES,
    get_root,
    load_registry,
    make_entry,
    project_path,
    root_path,
    save_registry,
    start_command,
)
from .status import git_status, port_is_up
from .vercel import is_linked, link as vercel_link

# Anciennes valeurs de type (projects.json d'avant la migration, clés *_TYPE du .env).
LEGACY_TYPES = {"static": "web", "vite": "webapp"}


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


def _sync_env(projects: list[dict]) -> None:
    """Synchronise les variables PORT/TYPE depuis projects.json.

    Les autres variables de .env sont conservées.
    """
    env_path = get_root() / ".env"

    existing_lines = (
        env_path.read_text(encoding="utf-8").splitlines()
        if env_path.exists()
        else []
    )

    canonical_keys = set()
    for entry in projects:
        key = env_key(entry["name"])
        canonical_keys.add(f"{key}_PORT")
        canonical_keys.add(f"{key}_TYPE")

    # Anciennes appellations de projets à supprimer uniquement
    # pour leurs variables PORT/TYPE.
    legacy_names = {
        "CANSTACK",
        "MYFIRSTEVALUATION",
        "MELTING_POTES",
        "PATISS_ORANE",
        "PORTFOLIO_NABET",
        "ORANE_COATCH_THERAPEUTIQUE",
        "WWDC26_BINGO",
        "AREMACASSO",
        "ORANECATCH",
    }

    legacy_keys = {
        f"{name}_{suffix}"
        for name in legacy_names
        for suffix in ("PORT", "TYPE")
    }

    output = []

    for line in existing_lines:
        stripped = line.strip()

        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()

            # Les variables projet canoniques sont régénérées.
            if key in canonical_keys:
                continue

            # Suppression des anciens PORT/TYPE connus.
            if key in legacy_keys:
                continue

        output.append(line)

    while output and not output[-1].strip():
        output.pop()

    if output:
        output.append("")

    output.append("# Projet        Port   Type")
    output.append("")

    for entry in projects:
        key = env_key(entry["name"])
        output.append(f"{key}_PORT={entry.get('port') or ''}")
        output.append(f"{key}_TYPE={entry['type']}")
        output.append("")

    env_path.write_text(
        "\n".join(output).rstrip() + "\n",
        encoding="utf-8",
    )


def _write_mk() -> None:
    (get_root() / ".projects.mk").write_text(makegen.generate(), encoding="utf-8")


def _used_ports(reg: dict) -> set[int]:
    return {int(p["port"]) for p in reg.values() if p.get("port")}


def _start_for(ptype: str, port: int) -> str:
    """Commande de démarrage par défaut ; vide pour un projet custom, dont la
    commande est à renseigner à la main dans projects.json (champ `start`)."""
    return "" if ptype == "custom" else start_command(ptype, port)


def cmd_sync(args: argparse.Namespace) -> None:
    """Synchronise les dossiers physiques vers le registre.

    Sync est strictement non destructif :
    - ne supprime aucun projet du registre ;
    - ne supprime, ne déplace et ne modifie aucun dossier ;
    - ne crée, ne renomme et ne modifie aucun dépôt GitHub ;
    - détecte automatiquement type, port et remote GitHub des nouveaux projets ;
    - met à jour uniquement les métadonnées détectables (root, vercel, remote) ;
    - conserve type, port, start, status, priority, description et notes ;
    - ignore les doublons de nom normalisé.
    """
    reg = load_registry()
    added: list[dict] = []
    updated: list[dict] = []

    existing_by_normalized = {
        normalize_project_name(name): entry
        for name, entry in reg.items()
    }

    for root in ("projects", "personal"):
        for dirname in scan_dirs(root):
            normalized = normalize_project_name(dirname)
            project_dir = root_path(root) / dirname

            existing = existing_by_normalized.get(normalized)

            if existing is not None:
                changes: list[str] = []

                detected_github = None
                if not args.no_git:
                    detected_github = detect_git_remote(project_dir)

                if existing.get("root") != root:
                    existing["root"] = root
                    changes.append(f"root={root}")

                detected_vercel = root == "projects"
                if existing.get("vercel") != detected_vercel:
                    existing["vercel"] = detected_vercel
                    existing["vercel_enabled"] = detected_vercel
                    changes.append(f"vercel={detected_vercel}")

                if not args.no_git and existing.get("github_repo") != detected_github:
                    old_github = existing.get("github_repo") or "-"
                    new_github = detected_github or "-"
                    existing["github_repo"] = detected_github
                    existing["git"] = bool(detected_github)
                    changes.append(f"github={old_github} -> {new_github}")

                if changes:
                    updated.append(existing)
                    print(f"~ {dirname}: " + ", ".join(changes))
                else:
                    print(f"= {dirname}: déjà synchronisé")

                continue

            ptype = detect_type(project_dir)

            port_range = NERON_PORT_RANGE if root == "neron" else DEFAULT_PORT_RANGE
            port = next_free_port(_used_ports(reg), port_range)

            github_repo = None
            if not args.no_git:
                github_repo = detect_git_remote(project_dir)

            entry = make_entry(
                dirname, root, ptype, port, _start_for(ptype, port),
                vercel=(root == "projects"),
                visibility="public",
                github_repo=github_repo,
                git=bool(github_repo),
            )

            reg[dirname] = entry
            added.append(entry)
            existing_by_normalized[normalized] = entry

            print(
                f"+ {dirname}: "
                f"type={ptype} "
                f"port={port} "
                f"root={root} "
                f"vercel={entry['vercel']} "
                f"github={github_repo or '-'}"
            )
            if ptype == "custom":
                print(f"  ! {dirname}: type custom — renseigne le champ `start` dans projects.json")

    changed = bool(added or updated)

    if changed:
        save_registry(reg)
        _sync_env(list(reg.values()))
        _write_mk()

        print()
        if added:
            print(f"{len(added)} projet(s) ajouté(s).")
        if updated:
            print(f"{len(updated)} projet(s) mis à jour.")
        print("Aucun dossier ni dépôt GitHub modifié.")
    else:
        _sync_env(list(reg.values()))
        _write_mk()
        print("Rien de nouveau à synchroniser.")


def cmd_add(args: argparse.Namespace) -> None:
    reg = load_registry()
    if args.name in reg:
        print(f"'{args.name}' est déjà enregistré (voir projects.json).")
        return
    project_dir = root_path(args.root) / args.name
    if not project_dir.exists():
        print(f"ERREUR: {project_dir} n'existe pas — crée le dossier d'abord.")
        sys.exit(1)
    ptype = args.type or detect_type(project_dir)
    port_range = NERON_PORT_RANGE if args.root == "neron" else DEFAULT_PORT_RANGE
    port = args.port or next_free_port(_used_ports(reg), port_range)
    vercel = args.vercel if args.vercel is not None else (args.root == "projects")
    entry = make_entry(
        args.name, args.root, ptype, port, _start_for(ptype, port),
        vercel=vercel, visibility=args.visibility,
    )
    reg[args.name] = entry
    save_registry(reg)
    _sync_env(list(reg.values()))
    _write_mk()
    print(f"+ {entry['name']}: type={ptype} port={port} root={args.root} vercel={vercel}")
    if ptype == "custom":
        print("  ! type custom — renseigne le champ `start` dans projects.json")

    if not args.no_git:
        res = init_git_and_github_repo(project_dir, entry["name"], visibility=args.visibility)
        print(f"  git/github: {res}")
        if res.get("github_repo"):
            entry["github_repo"] = res["github_repo"]
            entry["git"] = True
            save_registry(reg)
    if entry["vercel"] and not args.no_vercel:
        res = vercel_link(project_dir)
        print(f"  vercel: {res}")


def cmd_list(args: argparse.Namespace) -> None:
    reg = load_registry()
    print(f"{'PROJET':<14} {'ROOT':<10} {'TYPE':<8} {'PORT':<6} {'VERCEL':<7} {'GITHUB'}")
    print("-" * 70)
    for p in reg.values():
        print(
            f"{p['name']:<14} {p.get('root', '-'):<10} {p['type']:<8} "
            f"{str(p.get('port') or '-'):<6} {('oui' if p.get('vercel') else '-'):<7} {p.get('github_repo') or '-'}"
        )


def cmd_status(args: argparse.Namespace) -> None:
    reg = load_registry()
    print(f"{'PROJET':<14} {'PORT':<6} {'ETAT':<6} {'GIT':<10} {'VERCEL'}")
    print("-" * 60)
    for p in reg.values():
        project_dir = project_path(p)
        port = p.get("port")
        up = port_is_up(port) if port else False
        gs = git_status(project_dir)
        git_str = "pas-git" if not gs.get("tracked") else ("modifie" if gs.get("dirty") else "propre")
        vercel_str = "-" if not p.get("vercel") else ("lie" if is_linked(project_dir) else "non-lie")
        print(f"{p['name']:<14} {str(port or '-'):<6} {('UP' if up else 'DOWN'):<6} {git_str:<10} {vercel_str}")


def cmd_generate_mk(args: argparse.Namespace) -> None:
    sys.stdout.write(makegen.generate())


def cmd_import_env(args: argparse.Namespace) -> None:
    """Back-fill du port dans le registre depuis un .env existant —
    utile pour récupérer les ports déjà en service."""
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
    for p in reg.values():
        key = env_key(p["name"])
        port_val = env.get(f"{key}_PORT")
        type_val = env.get(f"{key}_TYPE")
        if port_val and not p.get("port"):
            p["port"] = int(port_val)
            changed = True
            print(f"  {p['name']}: port importé depuis .env = {p['port']}")
        if type_val:
            type_val = LEGACY_TYPES.get(type_val, type_val)
            if type_val != p["type"]:
                print(f"  {p['name']}: type registre='{p['type']}' vs .env='{type_val}' (laissé tel quel, à vérifier à la main)")
    if changed:
        save_registry(reg)
        _write_mk()
        print("Registre et .projects.mk mis à jour.")
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

    p_sync = sub.add_parser("sync", help="Scanne projects/personal et enregistre les nouveaux projets")
    p_sync.add_argument("--no-git", action="store_true", help="Ne pas faire git init / gh repo create")
    p_sync.add_argument("--no-vercel", action="store_true", help="Ne pas faire vercel link")
    p_sync.add_argument("--visibility", choices=["public", "private"], default="public")
    p_sync.set_defaults(func=cmd_sync)

    p_add = sub.add_parser("add", help="Ajoute explicitement un projet déjà présent sur disque")
    p_add.add_argument("name")
    p_add.add_argument("--root", choices=["projects", "personal", "neron"], default="projects")
    p_add.add_argument("--type", choices=list(PROJECT_TYPES), default=None)
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

    p_list = sub.add_parser("list", help="Liste les projets connus (registre)")
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
