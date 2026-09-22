"""Dashboard /srv — interface web.

Lancement : `make dashboard` (uvicorn main:app depuis /srv/dashboard).
L'API JSON pour Neron vit dans api.py, la logique commune dans services.py.
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

# srvctl vit à côté de ce fichier : on s'assure que le dossier du
# dépôt est sur sys.path quel que soit le cwd (uvicorn, make, cron…).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, Form, Request  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402

import services  # noqa: E402
from api import API_VERSION, router as public_router, secured as secured_router  # noqa: E402
from auth import ENV_KEY, is_configured  # noqa: E402
from srvctl import journal  # noqa: E402
from srvctl.registry import load_registry  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    journal.init_db()
    stale = journal.recover_stale()
    if stale:
        print(f"[dashboard] {stale} action(s) interrompue(s) au redémarrage, marquée(s) en erreur.")
    yield


app = FastAPI(
    title="srv dashboard API",
    version=API_VERSION,
    summary="Pilotage des projets hébergés sous /srv (homebox) — conçue pour être appelée par Neron.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app.include_router(public_router)
app.include_router(secured_router)


# --- filtres d'affichage --------------------------------------------------

def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fmt_datetime(value: Optional[str]) -> str:
    dt = _parse(value)
    return dt.astimezone().strftime("%d/%m/%Y %H:%M") if dt else "—"


def fmt_time(value: Optional[str]) -> str:
    dt = _parse(value)
    return dt.astimezone().strftime("%H:%M") if dt else "—"


def fmt_ago(value: Optional[str]) -> str:
    dt = _parse(value)
    if not dt:
        return "—"
    seconds = int((datetime.now(timezone.utc) - dt).total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return "à l'instant"
    if seconds < 3600:
        return f"il y a {seconds // 60} min"
    if seconds < 86400:
        hours = seconds // 3600
        return f"il y a {hours} h"
    days = seconds // 86400
    if days == 1:
        return "hier"
    if days < 30:
        return f"il y a {days} j"
    return fmt_datetime(value)


def fmt_duration(ms: Optional[int]) -> str:
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms} ms"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f} s".replace(".", ",")
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes} min {rest:02d} s"


templates.env.filters["dt"] = fmt_datetime
templates.env.filters["time"] = fmt_time
templates.env.filters["ago"] = fmt_ago
templates.env.filters["dur"] = fmt_duration


# --- helpers --------------------------------------------------------------

def render(request: Request, template: str, nav: str, **context):
    params = request.query_params
    base = {
        "nav": nav,
        "flash": params.get("msg"),
        "flash_kind": params.get("kind", "ok"),
        "api_configured": is_configured(),
        "actions": services.ACTIONS,
        "roots": services.ROOTS,
        "types": services.TYPES,
        "statuses": services.STATUSES,
        "priorities": services.PRIORITIES,
        "status_labels": services.STATUS_LABELS,
        "priority_labels": services.PRIORITY_LABELS,
    }
    base.update(context)
    return templates.TemplateResponse(request, template, base)


def back(url: str, message: str, kind: str = "ok") -> RedirectResponse:
    sep = "&" if "?" in url else "?"
    return RedirectResponse(f"{url}{sep}msg={quote(message)}&kind={kind}", status_code=303)


# --- pages ----------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def overview(request: Request):
    projects = services.list_projects(host=request.url.hostname)
    return render(
        request, "overview.html", nav="overview",
        projects=projects,
        summary=services.summary(),
        activity=journal.list_activity(limit=8),
    )


@app.get("/projects/{name}", response_class=HTMLResponse, include_in_schema=False)
def project_page(request: Request, name: str):
    try:
        project = services.get_project(name, host=request.url.hostname)
    except services.ServiceError as exc:
        return back("/", exc.message, "error")
    return render(
        request, "project.html", nav="overview", project=project,
        logs=services.read_logs(name, lines=200),
    )


@app.get("/activity", response_class=HTMLResponse, include_in_schema=False)
def activity_page(request: Request, project: Optional[str] = None, status: Optional[str] = None):
    return render(
        request, "activity.html", nav="activity",
        entries=journal.list_activity(project=project, status=status, limit=200),
        all_projects=[p.name for p in load_registry().projects],
        selected_project=project, selected_status=status,
    )


@app.get("/activity/{activity_id}", response_class=HTMLResponse, include_in_schema=False)
def activity_detail_page(request: Request, activity_id: int):
    entry = journal.get_activity(activity_id)
    if entry is None:
        return back("/activity", f"Activité {activity_id} inconnue", "error")
    return render(request, "activity_detail.html", nav="activity", entry=entry)


@app.get("/deployments", response_class=HTMLResponse, include_in_schema=False)
def deployments_page(request: Request, project: Optional[str] = None, environment: Optional[str] = None):
    return render(
        request, "deployments.html", nav="deployments",
        deployments=journal.list_deployments(project=project, environment=environment, limit=200),
        selected_project=project, selected_environment=environment,
    )


@app.get("/api", response_class=HTMLResponse, include_in_schema=False)
def api_page(request: Request):
    base_url = str(request.base_url).rstrip("/")
    return render(
        request, "api.html", nav="api",
        base_url=base_url, api_base=f"{base_url}/api/v1",
        env_key=ENV_KEY, api_version=API_VERSION,
    )


# --- actions (formulaires) ------------------------------------------------

@app.post("/projects/{name}/action", include_in_schema=False)
def action_form(name: str, action: str = Form(...)):
    try:
        services.run_action(name, action, source="dashboard")
    except services.ServiceError as exc:
        return back(f"/projects/{quote(name)}", exc.message, "error")
    label = services.ACTIONS[action]["label"]
    return back(f"/projects/{quote(name)}", f"{label} : lancé sur {name}")


@app.post("/projects/{name}/meta", include_in_schema=False)
def meta_form(
    name: str,
    status: str = Form(...),
    priority: str = Form(...),
    description: str = Form(""),
    notes: str = Form(""),
):
    try:
        services.update_project(
            name, {"status": status, "priority": priority, "description": description, "notes": notes}
        )
    except services.ServiceError as exc:
        return back(f"/projects/{quote(name)}", exc.message, "error")
    return back(f"/projects/{quote(name)}", "Suivi mis à jour")


@app.post("/projects/new", include_in_schema=False)
def create_form(
    name: str = Form(...),
    root: str = Form("projects"),
    type: str = Form("static"),
    description: str = Form(""),
    priority: str = Form("normal"),
    visibility: str = Form("public"),
    git: Optional[str] = Form(None),
    vercel: Optional[str] = Form(None),
):
    try:
        services.create_project(
            name=name, root=root, type=type, description=description, priority=priority,
            visibility=visibility, git=bool(git), vercel=bool(vercel), source="dashboard",
        )
    except services.ServiceError as exc:
        return back("/", exc.message, "error")
    return back(f"/projects/{quote(name.strip())}", f"{name.strip()} créé")


@app.post("/sync", include_in_schema=False)
def sync_form():
    activity = services.sync(source="dashboard", wait=True)
    ok = activity.get("status") == "ok"
    return back("/", "Sync terminé" if ok else "Sync en échec — voir le journal", "ok" if ok else "error")


# --- petites routes de service -------------------------------------------

@app.get("/ui/state", include_in_schema=False)
def ui_state():
    """Sondée par la page toutes les quelques secondes : dès qu'une action
    se termine, la page se recharge d'elle-même."""
    running = journal.running()
    return JSONResponse(
        {
            "running": [
                {"id": r["id"], "project": r["project"], "action": r["action"], "started_at": r["started_at"]}
                for r in running
            ],
            "count": len(running),
        }
    )


@app.get("/logs/{name}", response_class=PlainTextResponse, include_in_schema=False)
def logs_plain(name: str, lines: int = 300):
    try:
        content = services.read_logs(name, lines=lines)
    except services.ServiceError as exc:
        return PlainTextResponse(exc.message, status_code=exc.status_code)
    return PlainTextResponse(content or f"Pas de log pour « {name} » — le projet n'a peut-être jamais été démarré.")
