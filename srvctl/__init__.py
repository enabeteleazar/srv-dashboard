"""srvctl — gestion automatisée des projets sous /srv.

Source de vérité : srvctl/projects.json, lu et écrit par srvctl.srvctl
(load_registry / save_registry — dict nom -> entrée). Types de projet :
web, webapp, custom. Ce paquet est utilisé à la fois par le Makefile (via
`python3 -m srvctl.cli generate-mk`) et par le dashboard FastAPI
(dashboard/main.py, services.py).
"""
