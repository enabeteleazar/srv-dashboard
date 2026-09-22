from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

RootName = Literal["projects", "personal", "neron"]
ProjectType = Literal["static", "vite", "custom"]
# Suivi de projet (édité depuis le dashboard ou l'API) — n'influence pas le Makefile.
ProjectStatus = Literal["active", "paused", "done", "idea"]
Priority = Literal["low", "normal", "high"]


class ProjectEntry(BaseModel):
    name: str
    root: RootName
    type: ProjectType
    port: Optional[int] = None
    # Doit apparaître dans VERCEL_PROJECTS (make deploy / deploy-prod / vercel-link).
    vercel: bool = False
    github_repo: Optional[str] = None  # ex: "NABET/duoLingo"
    # Champs de suivi — valeurs par défaut pour rester compatible avec un
    # projects.json existant qui ne les contient pas encore.
    status: ProjectStatus = "active"
    priority: Priority = "normal"
    description: str = ""
    notes: str = ""


class Registry(BaseModel):
    projects: list[ProjectEntry] = Field(default_factory=list)

    def get(self, name: str) -> Optional[ProjectEntry]:
        return next((p for p in self.projects if p.name == name), None)

    def upsert(self, entry: ProjectEntry) -> None:
        for i, p in enumerate(self.projects):
            if p.name == entry.name:
                self.projects[i] = entry
                return
        self.projects.append(entry)

    def used_ports(self) -> set[int]:
        return {p.port for p in self.projects if p.port}
