"""Schémas d'entrée/sortie de l'API /api/v1 (Pydantic v2).

Ils servent aussi de documentation : FastAPI les publie dans l'OpenAPI
exposé sur /openapi.json, que Neron peut lire pour se câbler tout seul.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

ActionName = Literal[
    "start", "stop", "restart", "dev", "build", "test",
    "git-push", "vercel-link", "deploy", "deploy-prod",
]
RootName = Literal["projects", "personal", "neron"]
ProjectType = Literal["static", "vite", "custom"]
ProjectStatus = Literal["active", "paused", "done", "idea"]
Priority = Literal["low", "normal", "high"]


class GitOut(BaseModel):
    tracked: bool
    branch: Optional[str] = None
    dirty: bool = False
    changes: int = 0


class ActivityOut(BaseModel):
    id: int
    project: Optional[str] = None
    action: str
    source: str
    status: Literal["running", "ok", "error"]
    started_at: str
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    exit_code: Optional[int] = None


class ActivityDetailOut(ActivityOut):
    output: str = ""


class DeploymentOut(BaseModel):
    id: int
    activity_id: Optional[int] = None
    project: str
    environment: Literal["preview", "production"]
    status: Literal["ok", "error"]
    url: Optional[str] = None
    created_at: str


class CommitOut(BaseModel):
    hash: str
    short: str
    author: str
    date: str
    subject: str


class ProjectOut(BaseModel):
    name: str
    root: RootName
    type: ProjectType
    port: Optional[int] = None
    status: ProjectStatus
    priority: Priority
    description: str = ""
    notes: str = ""
    vercel_enabled: bool
    vercel_linked: Optional[bool] = None
    github_repo: Optional[str] = None
    github_url: Optional[str] = None
    path: str
    exists: bool
    up: bool = Field(description="Le port du projet répond (service en ligne)")
    url: Optional[str] = None
    running: bool = Field(description="Une action est en cours d'exécution sur ce projet")
    git: GitOut
    has_log: bool
    last_activity: Optional[ActivityOut] = None


class ProjectDetailOut(ProjectOut):
    commits: list[CommitOut] = []
    deployments: list[DeploymentOut] = []
    activity: list[ActivityOut] = []
    last_production: Optional[DeploymentOut] = None


class ProjectCreateIn(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$", examples=["monNouveauSite"])
    root: RootName = "projects"
    type: ProjectType = "static"
    git: bool = Field(default=True, description="git init + gh repo create sous l'org NABET")
    vercel: bool = Field(default=False, description="vercel link tout de suite")
    visibility: Literal["public", "private"] = "public"
    description: str = ""
    status: ProjectStatus = "active"
    priority: Priority = "normal"


class ProjectUpdateIn(BaseModel):
    status: Optional[ProjectStatus] = None
    priority: Optional[Priority] = None
    description: Optional[str] = None
    notes: Optional[str] = None


class ActionIn(BaseModel):
    action: ActionName
    wait: bool = Field(
        default=False,
        description="true : la réponse attend la fin de l'action (peut durer plusieurs minutes pour un build/deploy). "
                    "false : réponse immédiate avec une activité 'running' à sonder via /activity/{id}.",
    )


class StatusCountsOut(BaseModel):
    active: int = 0
    paused: int = 0
    done: int = 0
    idea: int = 0


class DayCountOut(BaseModel):
    date: str
    ok: int
    error: int


class SummaryOut(BaseModel):
    total: int
    up: int
    down: int
    running: int
    vercel: int
    by_status: StatusCountsOut
    deploys_7d: int
    failures_7d: int
    actions_7d: int
    activity_daily: list[DayCountOut]


class LogsOut(BaseModel):
    project: str
    lines: int
    content: str


class HealthOut(BaseModel):
    status: Literal["ok"]
    service: str = "srv-dashboard"
    version: str
    root: str
    auth_configured: bool
