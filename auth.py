"""Authentification de l'API : un jeton Bearer, lu dans l'environnement
ou dans /srv/.env (clé DASHBOARD_API_TOKEN).

L'interface web reste sans authentification (accès déjà limité par
Tailscale) ; l'API, elle, peut déclencher un deploy-prod : elle exige le
jeton. Tant qu'aucun jeton n'est configuré, l'API répond 503 — jamais
« ouverte par défaut ».

Génération du jeton : `make api-token` (ou `python3 -m srvctl.cli api-token`).
"""
from __future__ import annotations

import os
import re
import secrets
import sys
from pathlib import Path
from typing import Optional

# srvctl vit à côté de ce fichier : on s'assure que le dossier du
# dépôt est sur sys.path quel que soit le cwd (uvicorn, make, cron…).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import Depends, Header, HTTPException, status  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # noqa: E402

from srvctl.registry import get_root  # noqa: E402

ENV_KEY = "DASHBOARD_API_TOKEN"
CLIENT_RE = re.compile(r"[^A-Za-z0-9_.-]")

bearer_scheme = HTTPBearer(auto_error=False, description="Jeton DASHBOARD_API_TOKEN")


def configured_token() -> Optional[str]:
    """Jeton courant : variable d'environnement d'abord, puis /srv/.env
    (relu à chaque appel, donc une rotation ne demande pas de redémarrage)."""
    token = os.environ.get(ENV_KEY)
    if token and token.strip():
        return token.strip()
    env_path = get_root() / ".env"
    if not env_path.exists():
        return None
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{ENV_KEY}="):
                value = line.split("=", 1)[1].strip().strip("\"'")
                return value or None
    except OSError:
        return None
    return None


def is_configured() -> bool:
    return configured_token() is not None


def require_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> str:
    expected = configured_token()
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API désactivée : aucun DASHBOARD_API_TOKEN configuré (lance `make api-token` sur homebox).",
        )
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Jeton manquant : en-tête `Authorization: Bearer <token>` attendu.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Jeton invalide.")
    return credentials.credentials


def client_name(x_client: Optional[str] = Header(default=None, alias="X-Client")) -> str:
    """Qui appelle — repris tel quel dans le journal d'activité (source).
    Neron envoie `X-Client: neron` ; sans en-tête, la source est « api »."""
    if not x_client:
        return "api"
    cleaned = CLIENT_RE.sub("", x_client)[:32]
    return cleaned or "api"
