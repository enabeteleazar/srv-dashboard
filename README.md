# srv-dashboard — gestion des projets de homebox

Outillage complet du serveur `/srv` : le Makefile, la couche Python `srvctl`, le dashboard web et l'API REST que Neron appelle. Ce dépôt est autonome — tout le code est ici, seules les données du serveur restent dehors.

- **`Makefile`** — les commandes historiques (`make list`, `make dev <projet>`, `make deploy <projet>`…). C'est lui qui fait le vrai travail ; le dashboard et l'API ne font que l'appeler.
- **`srvctl/`** — détection des nouveaux dossiers, type de projet, port libre, `.env`, `git init` + `gh repo create` (org NABET), `vercel link`, génération de `.projects.mk`, journal SQLite.
- **`main.py` / `api.py` / `services.py` / `auth.py` / `schemas.py`** — l'interface web et l'API `/api/v1`, avec `templates/` et `static/`.
- **`clients/`** — le client Python à déposer dans Neron.
- **`systemd/`** — l'unité qui fait tourner le dashboard en permanence.

## Comment ça s'installe

Le dépôt se clone dans `<racine>/dashboard`, et un lien symbolique met le Makefile à la racine pour garder l'habitude `cd /srv && make list` :

```
/srv/
├── Makefile -> dashboard/Makefile   lien symbolique
├── dashboard/                       ce dépôt
├── projects.json                    source de vérité (données, hors dépôt)
├── .env                             ports + DASHBOARD_API_TOKEN (jamais versionné)
├── .projects.mk .data/ .logs/       généré : listes Make, journal SQLite, logs
└── projects/ personal/ neron/       les projets, chacun avec son propre dépôt git
```

Sur une machine neuve :

```bash
sudo mkdir -p /srv && cd /srv
git clone git@github.com:NABET/srv-dashboard.git dashboard
ln -s dashboard/Makefile Makefile
pip install -r dashboard/requirements.txt --break-system-packages
make sync            # scanne projects/ personal/ neron/ et crée projects.json
make api-token       # jeton de l'API pour Neron
make dashboard       # ou l'unité systemd, voir plus bas
```

Ailleurs que dans `/srv`, une seule variable suffit — le Makefile et `srvctl` lisent la même : `SRV_ROOT=/opt/srv make list` (et `Environment=SRV_ROOT=/opt/srv` dans l'unité systemd).

Première installation sur un `/srv` déjà peuplé : `make sync` puis `python3 -m srvctl.cli import-env` récupère les ports déjà en service depuis le `.env` existant. Les champs de suivi (`status`, `priority`, `description`, `notes`) sont facultatifs dans `projects.json` : un fichier qui ne les contient pas reste valide, les projets démarrent en « actif / priorité normale ».

## Ajouter un projet

Trois chemins, tous équivalents — ils finissent au même endroit :

1. **Dashboard** : bouton « Nouveau projet » (nom, dossier, type, priorité, repo GitHub, Vercel).
2. **Neron / API** : `POST /api/v1/projects`.
3. **Ligne de commande** : déposer le dossier dans `/srv/projects/` puis `make sync`.

Dans les trois cas : type deviné (`static` sans `package.json`, `vite` si vite détecté, sinon `custom`), premier port libre attribué (plage 5180-5199, le port du dashboard est exclu), clés `<PROJET>_PORT` / `<PROJET>_TYPE` ajoutées dans `.env`, `.projects.mk` régénéré, puis `git init` + `gh repo create NABET/<nom>` et `vercel link` selon les options. Ensuite `make dev`, `make deploy`… fonctionnent immédiatement, sans toucher au Makefile.

Un projet au cycle de vie sur mesure (`wwdc26Bingo`, `oraneCoatch`) est détecté `custom`, mais demande toujours sa branche dédiée dans `dev-project` / `start-project` : l'automatisation ne peut pas deviner une commande de démarrage arbitraire.

## Dashboard

```bash
make dashboard                       # http://0.0.0.0:5199
DASHBOARD_PORT=5195 make dashboard
```

Quatre pages :

- **Projets** — compteurs (actifs, en ligne, déploiements et échecs sur 7 jours), graphique des actions par jour sur 14 jours (bleu = réussies, orange = échecs, avec infobulle et table de données dépliable), flux des dernières actions, et le tableau des projets avec recherche et filtres par statut / dossier.
- **Fiche projet** — actions groupées (service, build, git, Vercel — « Mettre en production » demande confirmation), journal du projet, historique des déploiements avec leurs URLs, commits récents, logs du service, et le bloc « Suivi » éditable : statut (actif / en pause / terminé / idée), priorité, description, notes.
- **Activité** — le journal complet, filtrable par projet et par résultat ; chaque ligne ouvre la sortie complète de la commande.
- **Déploiements** — tous les deploy preview/production avec l'URL Vercel retournée.

Détails d'usage : les actions longues (build, deploy) tournent en arrière-plan — la page reste utilisable et se rafraîchit toute seule à la fin. Un seul job à la fois par projet (une deuxième action sur le même projet est refusée). Thème clair/sombre suivant le système, avec bascule manuelle mémorisée dans le navigateur. Pas d'authentification sur l'interface web : l'accès est déjà limité par Tailscale.

Ce qui n'apparaît pas dans le journal : les commandes lancées directement en SSH (`make deploy duoLingo`). Seul ce qui passe par le dashboard ou l'API est tracé.

### Le faire tourner en permanence (systemd)

`make dashboard` tourne au premier plan et meurt avec la session SSH. L'unité fournie dans `systemd/srv-dashboard.service` le lance au démarrage de homebox et le relance en cas de plantage :

```bash
sudo cp /srv/dashboard/systemd/srv-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now srv-dashboard
systemctl status srv-dashboard
journalctl -u srv-dashboard -f      # les logs du dashboard
```

Arrêter le `make dashboard` lancé à la main avant, sinon le port 5199 est déjà pris.

Deux choix volontaires dans l'unité. `KillMode=process` : le dashboard lance les serveurs des projets (`npx serve`, `vite`) via `setsid`/`nohup`, et sans ça un `systemctl restart srv-dashboard` les tuerait tous — avec, seul le dashboard est redémarré, tes sites restent en ligne. Et le durcissement reste léger (`ProtectSystem=full`, `NoNewPrivileges`, pas de `ProtectHome`) parce que `git`, `gh`, `pnpm`, `npx` et `vercel` écrivent dans le HOME d'eleazar — un `ProtectHome` casserait les déploiements.

Le jeton n'est pas injecté dans l'environnement du service : il est relu dans `/srv/.env` à chaque appel, donc `make api-token ARGS=--rotate` prend effet sans redémarrer quoi que ce soit.

Changer le port : `sudo systemctl edit srv-dashboard` puis `[Service]` / `Environment=DASHBOARD_PORT=5195`.

## API pour Neron

Base : `http://127.0.0.1:5199/api/v1` depuis homebox. Documentation interactive sur `/docs`, schéma machine sur `/openapi.json`, résumé lisible sur la page « API & Neron » du dashboard.

**Jeton** — l'API exige un Bearer, l'interface web non :

```bash
make api-token                 # génère DASHBOARD_API_TOKEN dans /srv/.env et l'affiche
make api-token ARGS=--rotate   # en génère un nouveau
```

Tant qu'aucun jeton n'est configuré, l'API répond `503` (jamais ouverte par défaut). Le fichier `.env` est relu à chaque appel : une rotation ne demande pas de redémarrage. L'en-tête facultatif `X-Client: neron` est repris dans la colonne « source » du journal, ce qui distingue les actions de Neron de celles lancées à la main.

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/health` | ping — seul appel sans jeton |
| GET | `/summary` | compteurs + activité des 14 derniers jours |
| GET | `/projects` | liste + état live (port, git, vercel), filtres `status` et `root` |
| GET | `/projects/{nom}` | fiche complète : commits, déploiements, journal |
| POST | `/projects` | créer un projet |
| PATCH | `/projects/{nom}` | statut, priorité, description, notes |
| POST | `/projects/{nom}/actions` | start · stop · restart · dev · build · test · git-push · vercel-link · deploy · deploy-prod |
| GET | `/projects/{nom}/logs` | fin du log du service |
| GET | `/activity`, `/activity/{id}` | journal, et sortie complète d'une action |
| GET | `/deployments` | historique Vercel avec URLs |
| POST | `/sync` | scanner `/srv` et enregistrer les nouveaux dossiers |

`POST /actions` accepte `{"action": "deploy", "wait": false}` : la réponse est immédiate (`202`) avec une activité `running` à suivre via `/activity/{id}`, ou `wait: true` pour attendre la fin (`200`). Codes d'erreur utiles : `409` action déjà en cours sur ce projet, `400` projet non éligible Vercel, `404` projet inconnu, `422` action ou champ invalide.

**Client Python** — `clients/srv_dashboard_client.py` (dans ce dépôt), sans aucune dépendance (urllib), à déposer dans Neron :

```python
from srv_dashboard_client import SrvDashboardClient

srv = SrvDashboardClient("http://127.0.0.1:5199/api/v1", token=os.environ["DASHBOARD_API_TOKEN"])
srv.summary()                                 # {'total': 11, 'up': 3, ...}
srv.projects(status="active")
activity = srv.run_action("duoLingo", "deploy")
srv.wait_for(activity["id"])                  # sonde jusqu'à ok/error
srv.update_project("duoLingo", status="paused", notes="en attente des maquettes")
```

## Journal (SQLite)

`<racine>/.data/dashboard.db` (donc `/srv/.data/dashboard.db`), deux tables : `activity` (début, fin, projet, action, source, résultat, code de sortie, durée, sortie tronquée à 20 000 caractères) et `deployments` (projet, environnement, résultat, URL Vercel extraite de la sortie). Connexion par opération, `WAL` + `busy_timeout` + `foreign_keys` activés dès l'ouverture. Au démarrage du dashboard, une action restée `running` (processus tué en cours de route) est clôturée en erreur plutôt que de rester en suspens.

## Ce qui a été testé, et comment

123 vérifications automatiques dans un `/srv` factice, avec `gh` et `vercel` simulés : rendu des quatre pages, création de projet (web + API), suivi persistant dans `projects.json`, actions synchrones et asynchrones, refus des actions hors liste blanche et des actions concurrentes sur un même projet, extraction de l'URL Vercel, journal et filtres, authentification (503 sans jeton, 401 sans en-tête, 403 mauvais jeton), génération et rotation du jeton, et le client Python contre un vrai serveur uvicorn. Le rendu a été relu en capture d'écran en thème clair, sombre et sur mobile, et l'unité systemd passe `systemd-analyze verify`.

Une régression est explicitement couverte : `make start` lance le serveur d'un projet en arrière-plan, et le sous-shell qui le porte garde le tube de sortie ouvert tant que le serveur tourne. La sortie des commandes passe donc par un fichier temporaire et jamais par un tube — sinon l'action resterait « en cours » indéfiniment et le projet verrouillé.

En revanche, **aucun compte réel n'a été touché** : les vraies commandes `git init`, `gh repo create`, `vercel link` et `vercel deploy` n'ont jamais été exécutées depuis l'environnement de développement. C'est le premier `make sync` / premier deploy réel qui les éprouve ; le message affiché après chaque étape dit clairement si elle a réussi.
