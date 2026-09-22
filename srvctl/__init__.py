"""srvctl — gestion automatisée des projets sous /srv.

Source de vérité : /srv/projects.json (voir srvctl.models.Registry).
Ce paquet est utilisé à la fois par le Makefile (via `python3 -m
srvctl.cli generate-mk`) et par le dashboard FastAPI (dashboard/main.py).
"""
