"""Journal d'activité et historique des déploiements (SQLite).

Base : <SRV_ROOT>/.data/dashboard.db — créée automatiquement.
Une connexion par opération (le dashboard exécute les actions dans des
threads) ; WAL + busy_timeout pour que lecture et écriture concurrentes ne
se bloquent pas.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

from .registry import get_root

MAX_OUTPUT_CHARS = 20_000  # on garde la fin de la sortie (là où sont les erreurs)

SCHEMA = """
CREATE TABLE IF NOT EXISTS activity (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT    NOT NULL,
    finished_at  TEXT,
    project      TEXT,
    action       TEXT    NOT NULL,
    source       TEXT    NOT NULL,
    status       TEXT    NOT NULL CHECK (status IN ('running', 'ok', 'error')),
    exit_code    INTEGER,
    duration_ms  INTEGER,
    output       TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_activity_started ON activity (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_project ON activity (project, started_at DESC);

CREATE TABLE IF NOT EXISTS deployments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id  INTEGER REFERENCES activity (id) ON DELETE SET NULL,
    created_at   TEXT    NOT NULL,
    project      TEXT    NOT NULL,
    environment  TEXT    NOT NULL CHECK (environment IN ('preview', 'production')),
    status       TEXT    NOT NULL CHECK (status IN ('ok', 'error')),
    url          TEXT
);
CREATE INDEX IF NOT EXISTS idx_deploy_created ON deployments (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_deploy_project ON deployments (project, created_at DESC);
"""


def db_path() -> Path:
    return get_root() / ".data" / "dashboard.db"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def recover_stale() -> int:
    """Au démarrage du dashboard : une action encore 'running' ne peut plus
    se terminer (le processus qui la suivait est mort) -> on la clôt en erreur."""
    with connect() as conn:
        cur = conn.execute(
            "UPDATE activity SET status='error', finished_at=?, "
            "output = output || ? WHERE status='running'",
            (now_iso(), "\n[interrompu : le dashboard a redémarré pendant l'exécution]"),
        )
        return cur.rowcount


# --- activité -------------------------------------------------------------

def start_activity(project: Optional[str], action: str, source: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO activity (started_at, project, action, source, status) VALUES (?, ?, ?, ?, 'running')",
            (now_iso(), project, action, source),
        )
        return int(cur.lastrowid)


def finish_activity(activity_id: int, ok: bool, exit_code: Optional[int], output: str, duration_ms: int) -> None:
    if len(output) > MAX_OUTPUT_CHARS:
        output = "[… sortie tronquée …]\n" + output[-MAX_OUTPUT_CHARS:]
    with connect() as conn:
        conn.execute(
            "UPDATE activity SET status=?, finished_at=?, exit_code=?, output=?, duration_ms=? WHERE id=?",
            ("ok" if ok else "error", now_iso(), exit_code, output, duration_ms, activity_id),
        )


def _row(r: Optional[sqlite3.Row], with_output: bool = False) -> Optional[dict]:
    if r is None:
        return None
    d = dict(r)
    if not with_output:
        d.pop("output", None)
    return d


def get_activity(activity_id: int) -> Optional[dict]:
    with connect() as conn:
        r = conn.execute("SELECT * FROM activity WHERE id=?", (activity_id,)).fetchone()
    return _row(r, with_output=True)


def list_activity(
    project: Optional[str] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    clauses, params = [], []
    if project:
        clauses.append("project = ?")
        params.append(project)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if source:
        clauses.append("source = ?")
        params.append(source)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params += [max(1, min(int(limit), 500)), max(0, int(offset))]
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM activity {where} ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?", params
        ).fetchall()
    return [_row(r) for r in rows]


def running() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM activity WHERE status='running' ORDER BY started_at").fetchall()
    return [_row(r) for r in rows]


def latest_by_project() -> dict[str, dict]:
    """Dernière activité de chaque projet (une requête pour tout le tableau)."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT a.* FROM activity a
            JOIN (SELECT project, MAX(id) AS max_id FROM activity
                  WHERE project IS NOT NULL GROUP BY project) last
              ON a.id = last.max_id
            """
        ).fetchall()
    return {r["project"]: _row(r) for r in rows}


def daily_counts(days: int = 14) -> list[dict]:
    """Nombre d'actions terminées par jour (UTC) sur les N derniers jours,
    jours vides inclus — alimente le graphique de la vue d'ensemble."""
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT substr(started_at, 1, 10) AS day,
                   SUM(status = 'ok')    AS ok,
                   SUM(status = 'error') AS error
            FROM activity
            WHERE substr(started_at, 1, 10) >= ?
            GROUP BY day
            """,
            (start.isoformat(),),
        ).fetchall()
    by_day = {r["day"]: (int(r["ok"] or 0), int(r["error"] or 0)) for r in rows}
    out = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        ok, err = by_day.get(d, (0, 0))
        out.append({"date": d, "ok": ok, "error": err})
    return out


def count_since(days: int, status: Optional[str] = None) -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    q = "SELECT COUNT(*) FROM activity WHERE started_at >= ?"
    params: list = [since]
    if status:
        q += " AND status = ?"
        params.append(status)
    with connect() as conn:
        return int(conn.execute(q, params).fetchone()[0])


# --- déploiements ---------------------------------------------------------

def record_deployment(activity_id: Optional[int], project: str, environment: str, ok: bool, url: Optional[str]) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO deployments (activity_id, created_at, project, environment, status, url) VALUES (?, ?, ?, ?, ?, ?)",
            (activity_id, now_iso(), project, environment, "ok" if ok else "error", url),
        )
        return int(cur.lastrowid)


def list_deployments(
    project: Optional[str] = None,
    environment: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    clauses, params = [], []
    if project:
        clauses.append("project = ?")
        params.append(project)
    if environment:
        clauses.append("environment = ?")
        params.append(environment)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(int(limit), 500)))
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM deployments {where} ORDER BY created_at DESC, id DESC LIMIT ?", params
        ).fetchall()
    return [dict(r) for r in rows]


def deployments_since(days: int) -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with connect() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM deployments WHERE created_at >= ?", (since,)).fetchone()[0])


def last_production(project: str) -> Optional[dict]:
    with connect() as conn:
        r = conn.execute(
            "SELECT * FROM deployments WHERE project=? AND environment='production' AND status='ok' "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (project,),
        ).fetchone()
    return dict(r) if r else None
