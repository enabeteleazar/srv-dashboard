from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Registry


def get_root() -> Path:
    """Racine /srv — surchargeable via SRV_ROOT (utile pour les tests)."""
    return Path(os.environ.get("SRV_ROOT", "/srv"))


def registry_path() -> Path:
    return get_root() / "projects.json"


def load_registry() -> Registry:
    p = registry_path()
    if not p.exists():
        return Registry(projects=[])
    data = json.loads(p.read_text(encoding="utf-8"))
    return Registry.model_validate(data)


def save_registry(reg: Registry) -> None:
    p = registry_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(reg.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(p)
