SHELL := /bin/bash

# Racine du serveur. Surchargeable pour un déploiement ailleurs que /srv :
#   SRV_ROOT=/opt/srv make list      (srvctl lit la même variable)
ROOT ?= $(if $(SRV_ROOT),$(SRV_ROOT),/srv)

# srvctl vit désormais DANS dashboard/ (le dépôt est autonome), d'où le
# PYTHONPATH : le Makefile, lui, tourne depuis la racine du serveur.
SRVCTL := SRV_ROOT="$(ROOT)" PYTHONPATH="$(ROOT)/dashboard" python3 -m srvctl.cli

# PROJECTS, STATIC_PROJECTS, WEB_PROJECTS, CUSTOM_WEB_PROJECTS,
# VERCEL_PROJECTS et PROJECT_DIR_<nom> sont générés par srvctl à partir
# de /srv/projects.json (source de vérité) — voir .projects.mk.
# NE PLUS ÉDITER CES LISTES À LA MAIN : éditer projects.json puis lancer
# `make sync`. Le -include régénère automatiquement le fichier si
# projects.json a changé depuis la dernière génération.
-include .projects.mk

.projects.mk: projects.json
	@$(SRVCTL) generate-mk > .projects.mk

# Reste des WEB_PROJECTS : simple "vite preview" au démarrage (les
# projets à cycle de vie sur mesure listés dans CUSTOM_WEB_PROJECTS ont
# leur propre branche dans dev-project / start-project).
VITE_PREVIEW_PROJECTS := $(filter-out $(CUSTOM_WEB_PROJECTS),$(WEB_PROJECTS))

# Résolution du chemin physique d'un projet — PROJECT_DIR_<nom> est
# défini dans .projects.mk pour chaque projet connu.
PROJECT_DIR = $(PROJECT_DIR_$(PROJECT))

.DEFAULT_GOAL := help

.PHONY: help list _project-dir sync dashboard api-token \
	dev dev-all dev-project \
	start start-all start-project \
	stop stop-all stop-project \
	status status-all status-project \
	restart restart-all restart-project \
	build build-all build-project \
	test test-all test-project \
	git-status git-status-all git-status-project \
	git-push git-push-all git-push-project \
	vercel-link vercel-link-all vercel-link-project \
	deploy deploy-all deploy-project \
	deploy-prod deploy-prod-all deploy-prod-project \
	all $(PROJECTS)

help:
	@echo ""
	@echo "SRV PROJECT MANAGER"
	@echo ""
	@echo "Usage:"
	@echo "  make list"
	@echo "  make dev all"
	@echo "  make dev <project>"
	@echo "  make start all"
	@echo "  make start <project>"
	@echo "  make stop all"
	@echo "  make stop <project>"
	@echo "  make status all"
	@echo "  make status <project>"
	@echo "  make restart all"
	@echo "  make restart <project>"
	@echo "  make build all"
	@echo "  make build <project>"
	@echo "  make test all"
	@echo "  make test <project>"
	@echo "  make git-status all"
	@echo "  make git-status <project>"
	@echo "  make git-push all"
	@echo "  make git-push <project>"
	@echo "  make vercel-link all"
	@echo "  make vercel-link <project>"
	@echo "  make deploy all           (déploiement Vercel preview)"
	@echo "  make deploy <project>     (déploiement Vercel preview)"
	@echo "  make deploy-prod all      (mise en ligne Vercel production)"
	@echo "  make deploy-prod <project> (mise en ligne Vercel production)"
	@echo "  make sync                 (scanne /srv, enregistre les nouveaux projets)"
	@echo "  make dashboard            (lance le dashboard web sur DASHBOARD_PORT)"
	@echo "  make api-token            (jeton Bearer de l'API pour Neron)"
	@echo ""
	@echo "Projects:"
	@printf '  %s\n' $(PROJECTS)
	@echo ""
	@echo "Projects Vercel (deploy / deploy-prod / vercel-link) :"
	@printf '  %s\n' $(VERCEL_PROJECTS)
	@echo ""

# Résout et affiche le chemin d'un projet — utilisé en interne par les
# boucles shell (list, git-status-all) pour ne pas dupliquer la logique
# de PROJECT_DIR.
_project-dir:
	@echo "$(PROJECT_DIR)"

# Scanne projects/personal/neron, enregistre les nouveaux dossiers dans
# projects.json (type, port, git init + repo GitHub, vercel link), met
# à jour .env, puis régénère .projects.mk immédiatement (sans attendre
# le prochain appel à make). Options: make sync ARGS="--no-git --no-vercel".
sync:
	@$(SRVCTL) sync $(ARGS)
	@$(MAKE) --no-print-directory .projects.mk

# Lance le dashboard web (lecture + actions start/stop/deploy/...) sur
# http://0.0.0.0:$$DASHBOARD_PORT (5199 par défaut). Nécessite le
# venv/paquets listés dans requirements.txt (fastapi, uvicorn, ...).
dashboard:
	@echo "Dashboard sur http://0.0.0.0:$${DASHBOARD_PORT:-5199} (Ctrl+C pour arrêter)"
	@cd "$(ROOT)/dashboard" && SRV_ROOT="$(ROOT)" python3 -m uvicorn main:app --host 0.0.0.0 --port $${DASHBOARD_PORT:-5199}

# Jeton Bearer de l'API du dashboard (pour Neron) : écrit DASHBOARD_API_TOKEN
# dans /srv/.env. `make api-token ARGS=--rotate` en génère un nouveau.
api-token:
	@$(SRVCTL) api-token $(ARGS)

list:
	@echo ""
	@printf "%-14s %-6s %-8s %-8s %-45s\n" "PROJET" "PORT" "TYPE" "VERCEL" "CHEMIN"
	@printf "%-14s %-6s %-8s %-8s %-45s\n" "--------------" "------" "--------" "--------" "---------------------------------------------"
	@for project in $(PROJECTS); do \
		key=$$(echo "$$project" | tr '[:lower:].-' '[:upper:]__'); \
		port=$$(grep "^$${key}_PORT=" "$(ROOT)/.env" | cut -d= -f2); \
		type=$$(grep "^$${key}_TYPE=" "$(ROOT)/.env" | cut -d= -f2); \
		path=$$($(MAKE) --no-print-directory _project-dir PROJECT="$$project"); \
		vstatus="-"; \
		if printf '%s\n' $(VERCEL_PROJECTS) | grep -Fxq "$$project"; then \
			if [ -d "$$path/.vercel" ]; then vstatus="lie"; else vstatus="non-lie"; fi; \
		fi; \
		printf "%-14s %-6s %-8s %-8s %-45s\n" "$$project" "$${port:--}" "$${type:--}" "$$vstatus" "$$path"; \
	done
	@echo ""

dev:
	@if [ "$(word 2,$(MAKECMDGOALS))" = "all" ]; then \
		$(MAKE) --no-print-directory dev-all; \
	elif [ -n "$(PROJECT)" ]; then \
		$(MAKE) --no-print-directory dev-project PROJECT="$(PROJECT)"; \
	elif [ -n "$(word 2,$(MAKECMDGOALS))" ]; then \
		$(MAKE) --no-print-directory dev-project PROJECT="$(word 2,$(MAKECMDGOALS))"; \
	else \
		echo "Usage: make dev <project|all> | make dev PROJECT=<project>"; exit 1; \
	fi

dev-all:
	@mkdir -p "$(ROOT)/.logs"
	@echo ""
	@echo "=== DEV ALL ==="
	@echo ""
	@for project in $(PROJECTS); do \
		$(MAKE) --no-print-directory dev-project PROJECT="$$project" & \
	done; \
	wait

dev-project:
	@project="$(PROJECT)"; \
	key=$$(echo "$$project" | tr '[:lower:].-' '[:upper:]__'); \
	port=$$(grep "^$${key}_PORT=" "$(ROOT)/.env" | cut -d= -f2); \
	if [ -z "$$port" ]; then echo "ERROR: projet inconnu ou port absent: $$project"; exit 1; fi; \
	mkdir -p "$(ROOT)/.logs"; \
	echo "DEV: $$project → port $$port"; \
	if printf '%s\n' $(STATIC_PROJECTS) | grep -Fxq "$$project"; then \
		cd "$(PROJECT_DIR)" && setsid nohup npx serve . -l "$$port" --no-clipboard > "$(ROOT)/.logs/$$project.log" 2>&1 < /dev/null & \
	elif [ "$$project" = "wwdc26Bingo" ]; then \
		cd "$(PROJECT_DIR)" && setsid nohup env PORT="$$port" BASE_PATH=/ pnpm --filter @workspace/wwdc26-bingo run dev > "$(ROOT)/.logs/$$project.log" 2>&1 < /dev/null & \
	elif [ "$$project" = "oraneCoatch" ]; then \
		cd "$(PROJECT_DIR)" && setsid nohup pnpm run dev --host 0.0.0.0 --port "$$port" > "$(ROOT)/.logs/$$project.log" 2>&1 < /dev/null & \
	elif printf '%s\n' $(WEB_PROJECTS) | grep -Fxq "$$project"; then \
		cd "$(PROJECT_DIR)" && setsid nohup pnpm exec vite --host 0.0.0.0 --port "$$port" > "$(ROOT)/.logs/$$project.log" 2>&1 < /dev/null & \
	else \
		echo "ERROR: projet inconnu: $$project"; exit 1; \
	fi

start:
	@if [ "$(word 2,$(MAKECMDGOALS))" = "all" ]; then \
		$(MAKE) --no-print-directory start-all; \
	elif [ -n "$(PROJECT)" ]; then \
		$(MAKE) --no-print-directory start-project PROJECT="$(PROJECT)"; \
	elif [ -n "$(word 2,$(MAKECMDGOALS))" ]; then \
		$(MAKE) --no-print-directory start-project PROJECT="$(word 2,$(MAKECMDGOALS))"; \
	else \
		echo "Usage: make start <project|all> | make start PROJECT=<project>"; exit 1; \
	fi

start-all:
	@mkdir -p "$(ROOT)/.logs"
	@echo ""
	@echo "=== START ALL ==="
	@echo ""
	@for project in $(PROJECTS); do \
		$(MAKE) --no-print-directory start-project PROJECT="$$project" & \
	done; \
	wait

start-project:
	@project="$(PROJECT)"; \
	key=$$(echo "$$project" | tr '[:lower:].-' '[:upper:]__'); \
	port=$$(grep "^$${key}_PORT=" "$(ROOT)/.env" | cut -d= -f2); \
	if [ -z "$$port" ]; then echo "ERROR: projet inconnu ou port absent: $$project"; exit 1; fi; \
	mkdir -p "$(ROOT)/.logs"; \
	echo "START: $$project → port $$port"; \
	if printf '%s\n' $(STATIC_PROJECTS) | grep -Fxq "$$project"; then \
		cd "$(PROJECT_DIR)" && setsid nohup npx serve . -l "$$port" --no-clipboard > "$(ROOT)/.logs/$$project.log" 2>&1 < /dev/null & \
	elif [ "$$project" = "wwdc26Bingo" ]; then \
		cd "$(PROJECT_DIR)" && setsid nohup env PORT="$$port" BASE_PATH=/ pnpm --filter @workspace/wwdc26-bingo run serve > "$(ROOT)/.logs/$$project.log" 2>&1 < /dev/null & \
	elif [ "$$project" = "oraneCoatch" ]; then \
		cd "$(PROJECT_DIR)" && setsid nohup env PORT="$$port" pnpm run serve > "$(ROOT)/.logs/$$project.log" 2>&1 < /dev/null & \
	elif printf '%s\n' $(VITE_PREVIEW_PROJECTS) | grep -Fxq "$$project"; then \
		cd "$(PROJECT_DIR)" && setsid nohup pnpm exec vite preview --host 0.0.0.0 --port "$$port" > "$(ROOT)/.logs/$$project.log" 2>&1 < /dev/null & \
	else \
		echo "ERROR: projet inconnu: $$project"; exit 1; \
	fi

stop:
	@if [ "$(word 2,$(MAKECMDGOALS))" = "all" ]; then \
		$(MAKE) --no-print-directory stop-all; \
	elif [ -n "$(PROJECT)" ]; then \
		$(MAKE) --no-print-directory stop-project PROJECT="$(PROJECT)"; \
	elif [ -n "$(word 2,$(MAKECMDGOALS))" ]; then \
		$(MAKE) --no-print-directory stop-project PROJECT="$(word 2,$(MAKECMDGOALS))"; \
	else \
		echo "Usage: make stop <project|all> | make stop PROJECT=<project>"; exit 1; \
	fi

stop-all:
	@echo ""
	@echo "=== STOP ALL ==="
	@echo ""
	@for project in $(PROJECTS); do \
		$(MAKE) --no-print-directory stop-project PROJECT="$$project"; \
	done

stop-project:
	@project="$(PROJECT)"; \
	key=$$(echo "$$project" | tr '[:lower:].-' '[:upper:]__'); \
	port=$$(grep "^$${key}_PORT=" "$(ROOT)/.env" | cut -d= -f2); \
	if [ -z "$$port" ]; then echo "ERROR: projet inconnu ou port absent: $$project"; exit 1; fi; \
	echo "STOP: $$project → port $$port"; \
	fuser -k "$$port/tcp" 2>/dev/null || true

status:
	@if [ "$(word 2,$(MAKECMDGOALS))" = "all" ]; then \
		$(MAKE) --no-print-directory status-all; \
	elif [ -n "$(PROJECT)" ]; then \
		$(MAKE) --no-print-directory status-project PROJECT="$(PROJECT)"; \
	elif [ -n "$(word 2,$(MAKECMDGOALS))" ]; then \
		$(MAKE) --no-print-directory status-project PROJECT="$(word 2,$(MAKECMDGOALS))"; \
	else \
		echo "Usage: make status <project|all> | make status PROJECT=<project>"; exit 1; \
	fi

status-all:
	@echo ""
	@echo "=== STATUS ALL ==="
	@echo ""
	@printf "%-14s %-6s %-6s\n" "PROJET" "PORT" "ETAT"
	@printf "%-14s %-6s %-6s\n" "--------------" "------" "------"
	@up=0; down=0; err=0; \
	for project in $(PROJECTS); do \
		key=$$(echo "$$project" | tr '[:lower:].-' '[:upper:]__'); \
		port=$$(grep "^$${key}_PORT=" "$(ROOT)/.env" | cut -d= -f2); \
		if [ -z "$$port" ]; then \
			printf "%-14s %-6s %-6s\n" "$$project" "-" "ERREUR"; \
			err=$$((err+1)); \
		elif ss -ltn | grep -q ":$$port "; then \
			printf "%-14s %-6s %-6s\n" "$$project" "$$port" "UP"; \
			up=$$((up+1)); \
		else \
			printf "%-14s %-6s %-6s\n" "$$project" "$$port" "DOWN"; \
			down=$$((down+1)); \
		fi; \
	done; \
	echo ""; \
	echo "→ $$up up, $$down down, $$err erreur(s)"

status-project:
	@project="$(PROJECT)"; \
	key=$$(echo "$$project" | tr '[:lower:].-' '[:upper:]__'); \
	port=$$(grep "^$${key}_PORT=" "$(ROOT)/.env" | cut -d= -f2); \
	if [ -z "$$port" ]; then \
		echo "ERROR: projet inconnu ou port absent: $$project"; \
	elif ss -ltn | grep -q ":$$port "; then \
		echo "UP   $$project → $$port"; \
	else \
		echo "DOWN $$project → $$port"; \
	fi

restart:
	@if [ "$(word 2,$(MAKECMDGOALS))" = "all" ]; then \
		$(MAKE) --no-print-directory restart-all; \
	elif [ -n "$(PROJECT)" ]; then \
		$(MAKE) --no-print-directory restart-project PROJECT="$(PROJECT)"; \
	elif [ -n "$(word 2,$(MAKECMDGOALS))" ]; then \
		$(MAKE) --no-print-directory restart-project PROJECT="$(word 2,$(MAKECMDGOALS))"; \
	else \
		echo "Usage: make restart <project|all> | make restart PROJECT=<project>"; exit 1; \
	fi

restart-all:
	@$(MAKE) --no-print-directory stop-all
	@sleep 1
	@$(MAKE) --no-print-directory start-all

restart-project:
	@$(MAKE) --no-print-directory stop-project PROJECT="$(PROJECT)"
	@sleep 1
	@$(MAKE) --no-print-directory start-project PROJECT="$(PROJECT)"

test:
	@if [ "$(word 2,$(MAKECMDGOALS))" = "all" ]; then \
		$(MAKE) --no-print-directory test-all; \
	elif [ -n "$(PROJECT)" ]; then \
		$(MAKE) --no-print-directory test-project PROJECT="$(PROJECT)"; \
	elif [ -n "$(word 2,$(MAKECMDGOALS))" ]; then \
		$(MAKE) --no-print-directory test-project PROJECT="$(word 2,$(MAKECMDGOALS))"; \
	else \
		echo "Usage: make test <project|all> | make test PROJECT=<project>"; exit 1; \
	fi

test-all:
	@mkdir -p "$(ROOT)/.logs"
	@: > "$(ROOT)/.logs/test-results.tsv"
	@echo ""
	@echo "=== TEST ALL ==="
	@FAILED=0; \
	for project in $(PROJECTS); do \
		$(MAKE) --no-print-directory test-project PROJECT="$$project" || FAILED=$$((FAILED+1)); \
	done; \
	echo ""; \
	echo "=== RÉSULTATS TEST ==="; \
	printf "%-14s %-8s\n" "PROJET" "RESULTAT"; \
	printf "%-14s %-8s\n" "--------------" "--------"; \
	while IFS=$$'\t' read -r p r; do printf "%-14s %-8s\n" "$$p" "$$r"; done < "$(ROOT)/.logs/test-results.tsv"; \
	echo ""; \
	echo "TEST TERMINÉ — $$FAILED échec(s)"; \
	test "$$FAILED" -eq 0

test-project:
	@mkdir -p "$(ROOT)/.logs"; \
	project="$(PROJECT)"; \
	echo ""; \
	echo "=== TEST: $$project ==="; \
	if [ "$$project" = "wwdc26Bingo" ]; then \
		cd "$(PROJECT_DIR)" && CI=true PORT=5188 BASE_PATH=/ pnpm test; \
		if [ $$? -eq 0 ]; then printf "%s\tOK\n" "$$project" >> "$(ROOT)/.logs/test-results.tsv"; \
		else printf "%s\tECHEC\n" "$$project" >> "$(ROOT)/.logs/test-results.tsv"; exit 1; fi; \
	elif [ -f "$(PROJECT_DIR)/package.json" ]; then \
		cd "$(PROJECT_DIR)" || exit 1; \
		if node -e 'process.exit(require("./package.json").scripts?.test ? 0 : 1)' 2>/dev/null; then \
			CI=true pnpm test; \
			if [ $$? -eq 0 ]; then printf "%s\tOK\n" "$$project" >> "$(ROOT)/.logs/test-results.tsv"; \
			else printf "%s\tECHEC\n" "$$project" >> "$(ROOT)/.logs/test-results.tsv"; exit 1; fi; \
		else \
			echo "SKIP: aucun script test"; \
			printf "%s\tSKIP\n" "$$project" >> "$(ROOT)/.logs/test-results.tsv"; \
		fi; \
	else \
		echo "SKIP: projet statique sans package.json"; \
		printf "%s\tSKIP\n" "$$project" >> "$(ROOT)/.logs/test-results.tsv"; \
	fi

build:
	@if [ "$(word 2,$(MAKECMDGOALS))" = "all" ]; then \
		$(MAKE) --no-print-directory build-all; \
	elif [ -n "$(PROJECT)" ]; then \
		$(MAKE) --no-print-directory build-project PROJECT="$(PROJECT)"; \
	elif [ -n "$(word 2,$(MAKECMDGOALS))" ]; then \
		$(MAKE) --no-print-directory build-project PROJECT="$(word 2,$(MAKECMDGOALS))"; \
	else \
		echo "Usage: make build <project|all> | make build PROJECT=<project>"; exit 1; \
	fi

build-all:
	@mkdir -p "$(ROOT)/.logs"
	@: > "$(ROOT)/.logs/build-results.tsv"
	@echo ""
	@echo "=== BUILD ALL ==="
	@FAILED=0; \
	for project in $(PROJECTS); do \
		$(MAKE) --no-print-directory build-project PROJECT="$$project" || FAILED=$$((FAILED+1)); \
	done; \
	echo ""; \
	echo "=== RÉSULTATS BUILD ==="; \
	printf "%-14s %-8s\n" "PROJET" "RESULTAT"; \
	printf "%-14s %-8s\n" "--------------" "--------"; \
	while IFS=$$'\t' read -r p r; do printf "%-14s %-8s\n" "$$p" "$$r"; done < "$(ROOT)/.logs/build-results.tsv"; \
	echo ""; \
	echo "BUILD TERMINÉ — $$FAILED échec(s)"; \
	test "$$FAILED" -eq 0

build-project:
	@mkdir -p "$(ROOT)/.logs"; \
	project="$(PROJECT)"; \
	echo ""; \
	echo "=== BUILD: $$project ==="; \
	if [ "$$project" = "wwdc26Bingo" ]; then \
		cd "$(PROJECT_DIR)" && CI=true PORT=5188 BASE_PATH=/ pnpm build; \
		if [ $$? -eq 0 ]; then printf "%s\tOK\n" "$$project" >> "$(ROOT)/.logs/build-results.tsv"; \
		else printf "%s\tECHEC\n" "$$project" >> "$(ROOT)/.logs/build-results.tsv"; exit 1; fi; \
	elif [ -f "$(PROJECT_DIR)/package.json" ]; then \
		cd "$(PROJECT_DIR)" || exit 1; \
		if node -e 'process.exit(require("./package.json").scripts?.build ? 0 : 1)' 2>/dev/null; then \
			CI=true pnpm build; \
			if [ $$? -eq 0 ]; then printf "%s\tOK\n" "$$project" >> "$(ROOT)/.logs/build-results.tsv"; \
			else printf "%s\tECHEC\n" "$$project" >> "$(ROOT)/.logs/build-results.tsv"; exit 1; fi; \
		else \
			echo "SKIP: aucun script build"; \
			printf "%s\tSKIP\n" "$$project" >> "$(ROOT)/.logs/build-results.tsv"; \
		fi; \
	else \
		echo "SKIP: projet statique sans package.json"; \
		printf "%s\tSKIP\n" "$$project" >> "$(ROOT)/.logs/build-results.tsv"; \
	fi

git-status:
	@if [ "$(word 2,$(MAKECMDGOALS))" = "all" ]; then \
		$(MAKE) --no-print-directory git-status-all; \
	elif [ -n "$(PROJECT)" ]; then \
		$(MAKE) --no-print-directory git-status-project PROJECT="$(PROJECT)"; \
	elif [ -n "$(word 2,$(MAKECMDGOALS))" ]; then \
		$(MAKE) --no-print-directory git-status-project PROJECT="$(word 2,$(MAKECMDGOALS))"; \
	else \
		echo "Usage: make git-status <project|all> | make git-status PROJECT=<project>"; exit 1; \
	fi

git-status-all:
	@echo ""
	@echo "=== GIT STATUS ALL ==="
	@echo ""
	@printf "%-14s %-20s %-8s %-10s\n" "PROJET" "BRANCHE" "MODIFS" "ETAT"
	@printf "%-14s %-20s %-8s %-10s\n" "--------------" "--------------------" "--------" "----------"
	@for project in $(PROJECTS); do \
		dir=$$($(MAKE) --no-print-directory _project-dir PROJECT="$$project"); \
		if [ ! -d "$$dir/.git" ]; then \
			printf "%-14s %-20s %-8s %-10s\n" "$$project" "-" "-" "PAS-GIT"; \
			continue; \
		fi; \
		branch=$$(cd "$$dir" && git branch --show-current 2>/dev/null); \
		n=$$(cd "$$dir" && git status --porcelain 2>/dev/null | wc -l | tr -d ' '); \
		if [ "$$n" -eq 0 ]; then etat="propre"; else etat="modifie"; fi; \
		printf "%-14s %-20s %-8s %-10s\n" "$$project" "$${branch:-?}" "$$n" "$$etat"; \
	done
	@echo ""

git-status-project:
	@project="$(PROJECT)"; \
	echo ""; \
	echo "=== GIT STATUS: $$project ==="; \
	cd "$(PROJECT_DIR)" || exit 1; \
	git status --short --branch

git-push:
	@if [ "$(word 2,$(MAKECMDGOALS))" = "all" ]; then \
		$(MAKE) --no-print-directory git-push-all; \
	elif [ -n "$(PROJECT)" ]; then \
		$(MAKE) --no-print-directory git-push-project PROJECT="$(PROJECT)"; \
	elif [ -n "$(word 2,$(MAKECMDGOALS))" ]; then \
		$(MAKE) --no-print-directory git-push-project PROJECT="$(word 2,$(MAKECMDGOALS))"; \
	else \
		echo "Usage: make git-push <project|all> | make git-push PROJECT=<project>"; exit 1; \
	fi

git-push-all:
	@echo ""
	@echo "=== GIT PUSH ALL → branche courante ==="
	@echo ""
	@for project in $(PROJECTS); do \
		$(MAKE) --no-print-directory git-push-project PROJECT="$$project" || exit 1; \
	done

git-push-project:
	@project="$(PROJECT)"; \
	echo ""; \
	echo "=== GIT PUSH: $$project ==="; \
	cd "$(PROJECT_DIR)" || exit 1; \
	branch=$$(git branch --show-current); \
	if [ -z "$$branch" ]; then \
		echo "ERROR: aucune branche courante pour $$project"; \
		exit 1; \
	fi; \
	echo "→ origin/$$branch"; \
	git push -u origin "$$branch"

# --- Vercel : link + déploiements (preview / production) ---------------
#
# Prérequis : `npm i -g vercel` puis `vercel login` une fois sur homebox.
# `make vercel-link <project>` crée/rafraîchit le dossier .vercel/ du
# projet (à faire une fois par projet, ou après un changement de compte
# / d'org Vercel). `make deploy` fait un déploiement preview (URL de
# review), `make deploy-prod` fait la mise en ligne production.

vercel-link:
	@if [ "$(word 2,$(MAKECMDGOALS))" = "all" ]; then \
		$(MAKE) --no-print-directory vercel-link-all; \
	elif [ -n "$(PROJECT)" ]; then \
		$(MAKE) --no-print-directory vercel-link-project PROJECT="$(PROJECT)"; \
	elif [ -n "$(word 2,$(MAKECMDGOALS))" ]; then \
		$(MAKE) --no-print-directory vercel-link-project PROJECT="$(word 2,$(MAKECMDGOALS))"; \
	else \
		echo "Usage: make vercel-link <project|all> | make vercel-link PROJECT=<project>"; exit 1; \
	fi

vercel-link-all:
	@echo ""
	@echo "=== VERCEL LINK ALL ==="
	@FAILED=0; \
	for project in $(VERCEL_PROJECTS); do \
		$(MAKE) --no-print-directory vercel-link-project PROJECT="$$project" || FAILED=$$((FAILED+1)); \
	done; \
	echo ""; \
	echo "VERCEL LINK TERMINÉ — $$FAILED échec(s)"; \
	test "$$FAILED" -eq 0

vercel-link-project:
	@project="$(PROJECT)"; \
	if ! printf '%s\n' $(VERCEL_PROJECTS) | grep -Fxq "$$project"; then \
		echo "ERROR: $$project n'est pas dans VERCEL_PROJECTS"; exit 1; \
	fi; \
	if ! command -v vercel >/dev/null 2>&1; then \
		echo "ERROR: commande 'vercel' introuvable (npm i -g vercel)"; exit 1; \
	fi; \
	echo ""; \
	echo "=== VERCEL LINK: $$project ==="; \
	cd "$(PROJECT_DIR)" && vercel link --yes

deploy:
	@if [ "$(word 2,$(MAKECMDGOALS))" = "all" ]; then \
		$(MAKE) --no-print-directory deploy-all; \
	elif [ -n "$(PROJECT)" ]; then \
		$(MAKE) --no-print-directory deploy-project PROJECT="$(PROJECT)"; \
	elif [ -n "$(word 2,$(MAKECMDGOALS))" ]; then \
		$(MAKE) --no-print-directory deploy-project PROJECT="$(word 2,$(MAKECMDGOALS))"; \
	else \
		echo "Usage: make deploy <project|all> | make deploy PROJECT=<project>"; exit 1; \
	fi

deploy-all:
	@mkdir -p "$(ROOT)/.logs"
	@: > "$(ROOT)/.logs/deploy-results.tsv"
	@echo ""
	@echo "=== DEPLOY ALL (preview) ==="
	@FAILED=0; \
	for project in $(VERCEL_PROJECTS); do \
		$(MAKE) --no-print-directory deploy-project PROJECT="$$project" || FAILED=$$((FAILED+1)); \
	done; \
	echo ""; \
	echo "=== RÉSULTATS DEPLOY (preview) ==="; \
	printf "%-14s %-8s\n" "PROJET" "RESULTAT"; \
	printf "%-14s %-8s\n" "--------------" "--------"; \
	while IFS=$$'\t' read -r p r; do printf "%-14s %-8s\n" "$$p" "$$r"; done < "$(ROOT)/.logs/deploy-results.tsv"; \
	echo ""; \
	echo "DEPLOY TERMINÉ — $$FAILED échec(s)"; \
	test "$$FAILED" -eq 0

deploy-project:
	@mkdir -p "$(ROOT)/.logs"; \
	project="$(PROJECT)"; \
	if ! printf '%s\n' $(VERCEL_PROJECTS) | grep -Fxq "$$project"; then \
		echo "ERROR: $$project n'est pas dans VERCEL_PROJECTS"; \
		printf "%s\tECHEC\n" "$$project" >> "$(ROOT)/.logs/deploy-results.tsv"; exit 1; \
	fi; \
	if ! command -v vercel >/dev/null 2>&1; then \
		echo "ERROR: commande 'vercel' introuvable (npm i -g vercel)"; \
		printf "%s\tECHEC\n" "$$project" >> "$(ROOT)/.logs/deploy-results.tsv"; exit 1; \
	fi; \
	if [ ! -d "$(PROJECT_DIR)/.vercel" ]; then \
		echo "ERROR: $$project n'est pas lié à Vercel — lance d'abord: make vercel-link $$project"; \
		printf "%s\tECHEC\n" "$$project" >> "$(ROOT)/.logs/deploy-results.tsv"; exit 1; \
	fi; \
	echo ""; \
	echo "=== DEPLOY (preview): $$project ==="; \
	cd "$(PROJECT_DIR)" && vercel deploy --yes; \
	if [ $$? -eq 0 ]; then printf "%s\tOK\n" "$$project" >> "$(ROOT)/.logs/deploy-results.tsv"; \
	else printf "%s\tECHEC\n" "$$project" >> "$(ROOT)/.logs/deploy-results.tsv"; exit 1; fi

deploy-prod:
	@if [ "$(word 2,$(MAKECMDGOALS))" = "all" ]; then \
		$(MAKE) --no-print-directory deploy-prod-all; \
	elif [ -n "$(PROJECT)" ]; then \
		$(MAKE) --no-print-directory deploy-prod-project PROJECT="$(PROJECT)"; \
	elif [ -n "$(word 2,$(MAKECMDGOALS))" ]; then \
		$(MAKE) --no-print-directory deploy-prod-project PROJECT="$(word 2,$(MAKECMDGOALS))"; \
	else \
		echo "Usage: make deploy-prod <project|all> | make deploy-prod PROJECT=<project>"; exit 1; \
	fi

deploy-prod-all:
	@mkdir -p "$(ROOT)/.logs"
	@: > "$(ROOT)/.logs/deploy-prod-results.tsv"
	@echo ""
	@echo "=== DEPLOY-PROD ALL (mise en ligne) ==="
	@FAILED=0; \
	for project in $(VERCEL_PROJECTS); do \
		$(MAKE) --no-print-directory deploy-prod-project PROJECT="$$project" || FAILED=$$((FAILED+1)); \
	done; \
	echo ""; \
	echo "=== RÉSULTATS DEPLOY-PROD ==="; \
	printf "%-14s %-8s\n" "PROJET" "RESULTAT"; \
	printf "%-14s %-8s\n" "--------------" "--------"; \
	while IFS=$$'\t' read -r p r; do printf "%-14s %-8s\n" "$$p" "$$r"; done < "$(ROOT)/.logs/deploy-prod-results.tsv"; \
	echo ""; \
	echo "DEPLOY-PROD TERMINÉ — $$FAILED échec(s)"; \
	test "$$FAILED" -eq 0

deploy-prod-project:
	@mkdir -p "$(ROOT)/.logs"; \
	project="$(PROJECT)"; \
	if ! printf '%s\n' $(VERCEL_PROJECTS) | grep -Fxq "$$project"; then \
		echo "ERROR: $$project n'est pas dans VERCEL_PROJECTS"; \
		printf "%s\tECHEC\n" "$$project" >> "$(ROOT)/.logs/deploy-prod-results.tsv"; exit 1; \
	fi; \
	if ! command -v vercel >/dev/null 2>&1; then \
		echo "ERROR: commande 'vercel' introuvable (npm i -g vercel)"; \
		printf "%s\tECHEC\n" "$$project" >> "$(ROOT)/.logs/deploy-prod-results.tsv"; exit 1; \
	fi; \
	if [ ! -d "$(PROJECT_DIR)/.vercel" ]; then \
		echo "ERROR: $$project n'est pas lié à Vercel — lance d'abord: make vercel-link $$project"; \
		printf "%s\tECHEC\n" "$$project" >> "$(ROOT)/.logs/deploy-prod-results.tsv"; exit 1; \
	fi; \
	echo ""; \
	echo "=== DEPLOY-PROD (mise en ligne): $$project ==="; \
	cd "$(PROJECT_DIR)" && vercel deploy --prod --yes; \
	if [ $$? -eq 0 ]; then printf "%s\tOK\n" "$$project" >> "$(ROOT)/.logs/deploy-prod-results.tsv"; \
	else printf "%s\tECHEC\n" "$$project" >> "$(ROOT)/.logs/deploy-prod-results.tsv"; exit 1; fi

all:
	@:

$(PROJECTS):
	@:
