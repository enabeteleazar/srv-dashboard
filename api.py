"""API REST du dashboard — /api/v1.

Pensée pour Neron : tout ce que l'interface web sait faire est ici, en
JSON, derrière un jeton Bearer. La documentation interactive est sur
/docs, le schéma machine sur /openapi.json.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

import services
from auth import client_name, require_token
from schemas import (
    ActionIn,
    ActivityDetailOut,
    ActivityOut,
    DeploymentOut,
    HealthOut,
    LogsOut,
    ProjectCreateIn,
    ProjectDetailOut,
    ProjectOut,
    ProjectUpdateIn,
    SummaryOut,
)
from srvctl import journal

API_VERSION = "1.0.0"

router = APIRouter(prefix="/api/v1", tags=["srv"])
secured = APIRouter(prefix="/api/v1", tags=["srv"], dependencies=[Depends(require_token)])


def _host(request: Request) -> Optional[str]:
    return request.url.hostname


def _handle(exc: services.ServiceError) -> HTTPException:
    return HTTPException(exc.status_code, detail=exc.message)


@router.get("/health", response_model=HealthOut, summary="Ping (sans jeton)")
def health() -> dict:
    from auth import is_configured
    from srvctl.registry import get_root

    return {
        "status": "ok",
        "service": "srv-dashboard",
        "version": API_VERSION,
        "root": str(get_root()),
        "auth_configured": is_configured(),
    }


@secured.get("/summary", response_model=SummaryOut, summary="Chiffres clés (KPI + activité 14 jours)")
def get_summary(days: int = Query(14, ge=1, le=90)) -> dict:
    return services.summary(days=days)


@secured.get("/projects", response_model=list[ProjectOut], summary="Liste des projets et de leur état")
def list_projects(
    request: Request,
    status_: Optional[str] = Query(None, alias="status", description="active | paused | done | idea"),
    root: Optional[str] = Query(None, description="projects | personal | neron"),
) -> list[dict]:
    return services.list_projects(status=status_, root=root, host=_host(request))


@secured.get("/projects/{name}", response_model=ProjectDetailOut, summary="Fiche complète d'un projet")
def get_project(name: str, request: Request) -> dict:
    try:
        return services.get_project(name, host=_host(request))
    except services.ServiceError as exc:
        raise _handle(exc) from exc


@secured.post(
    "/projects", response_model=ProjectDetailOut, status_code=status.HTTP_201_CREATED,
    summary="Créer un projet (dossier + git/GitHub + Vercel + port + .env)",
)
def create_project(payload: ProjectCreateIn, source: str = Depends(client_name)) -> dict:
    try:
        return services.create_project(**payload.model_dump(), source=source)
    except services.ServiceError as exc:
        raise _handle(exc) from exc


@secured.patch("/projects/{name}", response_model=ProjectDetailOut, summary="Modifier statut / priorité / description / notes")
def update_project(name: str, payload: ProjectUpdateIn) -> dict:
    changes = payload.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Aucun champ à modifier.")
    try:
        return services.update_project(name, changes)
    except services.ServiceError as exc:
        raise _handle(exc) from exc


@secured.post(
    "/projects/{name}/actions", response_model=ActivityDetailOut,
    summary="Lancer une action (start/stop/build/deploy/…)",
    responses={202: {"description": "Action lancée en arrière-plan"}},
)
def run_action(name: str, payload: ActionIn, response: Response, source: str = Depends(client_name)) -> dict:
    try:
        activity = services.run_action(name, payload.action, source=source, wait=payload.wait)
    except services.ServiceError as exc:
        raise _handle(exc) from exc
    if activity and activity.get("status") == "running":
        response.status_code = status.HTTP_202_ACCEPTED
    elif activity and activity.get("status") == "error":
        response.status_code = status.HTTP_200_OK
    return activity


@secured.get("/projects/{name}/logs", response_model=LogsOut, summary="Fin du log du service (start/dev)")
def get_logs(name: str, lines: int = Query(200, ge=1, le=2000)) -> dict:
    try:
        content = services.read_logs(name, lines=lines)
    except services.ServiceError as exc:
        raise _handle(exc) from exc
    return {"project": name, "lines": lines, "content": content}


@secured.get("/activity", response_model=list[ActivityOut], summary="Journal d'activité")
def list_activity(
    project: Optional[str] = None,
    status_: Optional[str] = Query(None, alias="status", description="running | ok | error"),
    source: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    return journal.list_activity(project=project, status=status_, source=source, limit=limit, offset=offset)


@secured.get("/activity/{activity_id}", response_model=ActivityDetailOut, summary="Une activité + sa sortie complète")
def get_activity(activity_id: int) -> dict:
    activity = journal.get_activity(activity_id)
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Activité {activity_id} inconnue.")
    return activity


@secured.get("/deployments", response_model=list[DeploymentOut], summary="Historique des déploiements Vercel")
def list_deployments(
    project: Optional[str] = None,
    environment: Optional[str] = Query(None, description="preview | production"),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    return journal.list_deployments(project=project, environment=environment, limit=limit)


@secured.post("/sync", response_model=ActivityDetailOut, summary="Scanner /srv et enregistrer les nouveaux projets")
def sync(source: str = Depends(client_name)) -> dict:
    return services.sync(source=source, wait=True)
