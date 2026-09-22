"""Client Python de l'API du dashboard /srv — à déposer dans Neron.

Zéro dépendance (urllib de la bibliothèque standard), donc utilisable tel
quel depuis n'importe quel module neronOS sans toucher aux requirements.

    import os
    from srv_dashboard_client import SrvDashboardClient

    srv = SrvDashboardClient(
        "http://127.0.0.1:5199/api/v1",
        token=os.environ["DASHBOARD_API_TOKEN"],
    )

    srv.summary()                          # {'total': 11, 'up': 3, ...}
    srv.projects(status="active")          # liste de projets
    srv.project("duoLingo")                # fiche complète
    act = srv.run_action("duoLingo", "deploy")   # lancé en arrière-plan
    srv.wait_for(act["id"])                      # attend la fin, renvoie l'activité
    srv.update_project("duoLingo", status="paused", notes="en attente du design")

Le jeton se génère sur homebox avec `make api-token`.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

__all__ = ["SrvDashboardClient", "SrvDashboardError"]

ACTIONS = (
    "start", "stop", "restart", "dev", "build", "test",
    "git-push", "vercel-link", "deploy", "deploy-prod",
)


class SrvDashboardError(RuntimeError):
    """Erreur renvoyée par l'API (statut HTTP + détail) ou erreur réseau."""

    def __init__(self, message: str, status: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class SrvDashboardClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:5199/api/v1",
        token: Optional[str] = None,
        client_name: str = "neron",
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.client_name = client_name
        self.timeout = timeout

    # --- transport --------------------------------------------------------

    def _request(self, method: str, path: str, params: Optional[dict] = None, body: Optional[dict] = None,
                 timeout: Optional[float] = None) -> Any:
        url = self.base_url + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)

        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json", "X-Client": self.client_name}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            detail = raw
            try:
                parsed = json.loads(raw)
                detail = parsed.get("detail", raw)
            except json.JSONDecodeError:
                parsed = None
            raise SrvDashboardError(f"{exc.code} — {detail}", status=exc.code, payload=parsed) from exc
        except urllib.error.URLError as exc:
            raise SrvDashboardError(f"dashboard injoignable ({exc.reason})") from exc
        return json.loads(raw) if raw else None

    # --- lecture ----------------------------------------------------------

    def health(self) -> dict:
        """Ping — le seul appel qui ne demande pas de jeton."""
        return self._request("GET", "/health")

    def summary(self, days: int = 14) -> dict:
        return self._request("GET", "/summary", params={"days": days})

    def projects(self, status: Optional[str] = None, root: Optional[str] = None) -> list[dict]:
        return self._request("GET", "/projects", params={"status": status, "root": root})

    def project(self, name: str) -> dict:
        return self._request("GET", f"/projects/{urllib.parse.quote(name)}")

    def logs(self, name: str, lines: int = 200) -> str:
        return self._request("GET", f"/projects/{urllib.parse.quote(name)}/logs", params={"lines": lines})["content"]

    def activity(self, project: Optional[str] = None, status: Optional[str] = None,
                 source: Optional[str] = None, limit: int = 50) -> list[dict]:
        return self._request(
            "GET", "/activity", params={"project": project, "status": status, "source": source, "limit": limit}
        )

    def get_activity(self, activity_id: int) -> dict:
        return self._request("GET", f"/activity/{int(activity_id)}")

    def deployments(self, project: Optional[str] = None, environment: Optional[str] = None,
                    limit: int = 50) -> list[dict]:
        return self._request(
            "GET", "/deployments", params={"project": project, "environment": environment, "limit": limit}
        )

    # --- écriture ---------------------------------------------------------

    def run_action(self, name: str, action: str, wait: bool = False, timeout: Optional[float] = None) -> dict:
        """Lance une action. wait=False (défaut) renvoie tout de suite une
        activité 'running' à suivre avec wait_for()."""
        if action not in ACTIONS:
            raise ValueError(f"action inconnue : {action} (attendu : {', '.join(ACTIONS)})")
        return self._request(
            "POST", f"/projects/{urllib.parse.quote(name)}/actions",
            body={"action": action, "wait": wait},
            timeout=timeout if timeout is not None else (600.0 if wait else self.timeout),
        )

    def wait_for(self, activity_id: int, poll: float = 2.0, timeout: float = 900.0) -> dict:
        """Sonde une activité jusqu'à ce qu'elle soit terminée (ok/error)."""
        deadline = time.monotonic() + timeout
        while True:
            activity = self.get_activity(activity_id)
            if activity.get("status") != "running":
                return activity
            if time.monotonic() >= deadline:
                raise SrvDashboardError(f"activité {activity_id} toujours en cours après {timeout:.0f}s")
            time.sleep(poll)

    def create_project(self, name: str, root: str = "projects", type: str = "static", git: bool = True,
                       vercel: bool = False, visibility: str = "public", description: str = "",
                       status: str = "active", priority: str = "normal") -> dict:
        return self._request(
            "POST", "/projects",
            body={
                "name": name, "root": root, "type": type, "git": git, "vercel": vercel,
                "visibility": visibility, "description": description, "status": status, "priority": priority,
            },
            timeout=600.0,
        )

    def update_project(self, name: str, **changes: Any) -> dict:
        """Champs acceptés : status, priority, description, notes."""
        allowed = {"status", "priority", "description", "notes"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"champ non modifiable : {', '.join(sorted(unknown))}")
        return self._request("PATCH", f"/projects/{urllib.parse.quote(name)}", body=changes)

    def sync(self) -> dict:
        return self._request("POST", "/sync", timeout=600.0)
