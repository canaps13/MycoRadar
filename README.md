# MycoRadar

Plateforme de favorabilité écologique et de conditions de fructification des
champignons, conçue pour la France puis d'autres pays. La Provence est le pilote.

Le socle fournit une API de santé, une page web connectée et un environnement
PostGIS local avec migrations versionnées.
**Aucune source ingérée, carte ni prédiction scientifique disponible.** La santé
HTTP ne garantit pas la disponibilité des données ou d'une base de données.

## Démarrer avec Docker Compose (MR-003)

Prérequis : Docker Engine/Desktop en mode conteneurs Linux et Compose v2 ou
ultérieur. L'image PostGIS retenue est publiée en `linux/amd64` ; les machines
ARM nécessitent l'émulation Docker. Images de base et PostGIS sont épinglés par
digest. Aucun compte fournisseur ou service cloud n'est nécessaire.

Copier `.env.example` vers `.env` **uniquement si `.env` n'existe pas**, puis
adapter les ports ou le mot de passe local. Le mot de passe d'exemple est public,
réservé à cet environnement de développement. Ne pas l'utiliser en production.

```sh
docker compose up --build --wait --wait-timeout 180
```

Sans créer de `.env`, l'exemple peut être utilisé explicitement :

```sh
docker compose --env-file .env.example up --build --wait --wait-timeout 180
```

| Service | Adresse locale par défaut |
|---|---|
| Web | <http://127.0.0.1:15173> |
| API / documentation | <http://127.0.0.1:18000/docs> |
| Santé HTTP | <http://127.0.0.1:18000/health> |
| Disponibilité PostGIS et migrations | <http://127.0.0.1:18000/ready> |
| PostgreSQL | `127.0.0.1:55432` |

Les ports sont publiés uniquement sur la boucle locale. Compose attend PostGIS,
exécute `alembic upgrade head` une fois, attend sa réussite puis lance l'API et
le web. La migration initiale active PostGIS ; `0002_geospatial_foundation`
ajoute les tables géographiques et la provenance, sans charger de données.
Les données persistent dans le volume du projet `mycoradar-local`.
Voir le [contrat du schéma et ses limites](docs/database-schema.md).

`/health` reste disponible sans base. `/ready` renvoie HTTP 200 si PostGIS est
accessible et les migrations sont à jour, sinon HTTP 503 sans détail de connexion.
**Ni l'un ni l'autre ne certifie la disponibilité de prévisions scientifiques.**
La page continue donc d'afficher « Prévisions indisponibles ».

```sh
docker compose ps -a
docker compose logs --tail 100
docker compose run --rm migrate
docker compose stop
docker compose start
```

Ajouter `--env-file .env.example` à ces commandes si l'on n'utilise pas `.env`.
`stop` conserve conteneurs et volume. Ne pas utiliser de nettoyage global ni
supprimer le volume pour corriger un démarrage. Un changement de mot de passe
dans `.env` ne change pas le mot de passe d'une base déjà initialisée : conserver
la configuration compatible ou réaliser une rotation explicite adaptée.

Pour reconstruire le code après modification : relancer `up --build --wait`.
Les images API/web servent le développement local, sans configuration de
production ni promesse de déploiement. Le build web est réalisé dans l'image ;
l'aperçu Vite dans le conteneur utilise
un proxy interne vers `api:8000`, sans transmettre les identifiants PostgreSQL
au navigateur.

### Certificat d'un proxy local

Si un build échoue avec `UnknownIssuer` ou `UNABLE_TO_VERIFY_LEAF_SIGNATURE`,
utiliser un bundle CA PEM **déjà approuvé par votre environnement**. Le conserver
hors Git, par exemple dans `.tools/build-ca.pem`, puis, sous PowerShell :

```powershell
$env:BUILD_CA_FILE = (Resolve-Path .tools/build-ca.pem).Path
docker compose --env-file .env.example -f compose.yaml -f infra/compose.build-ca.yaml up --build --wait --wait-timeout 180
```

Cette surcharge transmet le certificat via un secret BuildKit éphémère, sans le
copier dans les images. TLS reste vérifié. Ne pas ajouter le certificat au dépôt
ni désactiver la vérification TLS. Sans proxy nécessitant ce certificat, la
commande Compose standard suffit.

## Démarrer les processus sans conteneur

Prérequis : Git, Node.js **24.x**, npm et [uv](https://docs.astral.sh/uv/getting-started/installation/).
`uv sync` installe Python 3.12 si nécessaire. Aucune clé fournisseur, aucun compte
cloud et aucune base ne sont nécessaires pour `/health` ou la page initiale.
Pour `/ready`, démarrer le service `db` avec Compose et appliquer les migrations.

Depuis la racine du dépôt :

```sh
uv sync --locked
npm --prefix web ci
```

Terminal 1, depuis la racine :

```sh
uv run --locked uvicorn mycoradar.main:app --app-dir api/src --host 127.0.0.1 --port 8000
```

Terminal 2, depuis la racine :

```sh
npm --prefix web run dev
```

Ouvrir <http://127.0.0.1:5173>. L'indicateur en bas de page vérifie l'API réelle.
L'API expose <http://127.0.0.1:8000/health>, la documentation interactive
<http://127.0.0.1:8000/docs> et le contrat <http://127.0.0.1:8000/openapi.json>.
Le proxy Vite `/api` retire ce préfixe avant de transmettre à l'API locale.
Le contrôle de santé expire après cinq secondes si le service ne répond pas.

Les variables `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` sont lues
côté serveur depuis l'environnement ou `.env`. Le moteur SQL n'ouvre une
connexion qu'à son utilisation. Les mots de passe ne sont pas journalisés et
les URL sont construites sans concaténation de secrets.

Sous PowerShell, utiliser `npm.cmd` si la politique d'exécution bloque `npm.ps1`.
Dans l'environnement préparé lors de MR-001, uv est disponible via
`.\.tools\uv\uv.exe` (non versionné) : remplacer `uv` par ce chemin si nécessaire.
Le Python téléchargé est sous `.tools/python` et l'environnement sous `.venv`.
Ne pas versionner ces répertoires. En cas d'erreur de certificat uv, utiliser
`uv --system-certs ...` pour le magasin Windows, sans désactiver TLS.
Pour conserver également le cache et la découverte de Python dans le projet,
initialiser ces variables dans les terminaux PowerShell utilisés :

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.tools/cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path (Get-Location) '.tools/python'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) '.tools/browsers'
$env:Path = (Resolve-Path .tools/uv).Path + ';' + $env:Path
```

Si npm rencontre `UNABLE_TO_VERIFY_LEAF_SIGNATURE` sur cette machine, utiliser
`$env:NODE_USE_SYSTEM_CA = '1'` (magasin Windows, vérification TLS conservée).

## Valider

Depuis la racine :

```sh
uv run --locked pytest -m "not integration"
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
npm --prefix web test
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web run format:check
npm --prefix web run build
git diff --check
```

La CI `Bootstrap` exécute ces contrôles et les tests navigateur sous Linux et
Windows. Ruff et ESLint contrôlent le code Python et TypeScript/React ; mypy et
`typecheck` vérifient les types séparément du build. TypeScript est limité à la
série 6.0, compatible avec la plage acceptée par typescript-eslint.
`Local environment` construit Compose et exécute les tests PostGIS sur une base
isolée. Les tests d'intégration sont exclus du job unitaire, pas déclarés réussis.
Chaque job de validation produit un tableau des résultats réels dans le résumé
Actions, même après un échec : réussi, échoué, annulé ou non exécuté.
Les contrôles restent bloquants ; aucun `continue-on-error` n'est utilisé.

Vérifier la pile Compose réellement démarrée :

```sh
uv run --locked python scripts/check_local_stack.py
```

Pour tester le navigateur sur cette pile, définir `PLAYWRIGHT_BASE_URL` avec
l'adresse du web (PowerShell : `$env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:15173'`),
puis `npm --prefix web run test:e2e`. Playwright utilise alors les services
existants. Supprimer cette variable pour revenir au test avec serveurs temporaires.

Les tests PostGIS sont explicitement activés par `MYCORADAR_TEST_DATABASE=1`
et exigent une base isolée dont le nom commence par `mycoradar_test`. Configurer
les variables `PG*` pour cette base, puis :

```sh
uv run --locked pytest -m integration
```

Sans cette activation, les tests d'intégration sont marqués **skipped**, jamais
présentés comme réussis. Ils vérifient PostGIS réel, le rejeu de migration et le
retour de version, en conservant l'extension PostGIS et ses données. La CI dédiée
construit la pile dans une base de test isolée et exécute ces contrôles.

Tests navigateur (les ports 8000 et 4173 doivent être libres ; Playwright lance
et arrête lui-même l'API et l'aperçu du build) :

```sh
npm --prefix web exec -- playwright install chromium
npm --prefix web run test:e2e
```

Construire le web avant ces tests. uv doit être dans le `PATH`. Les tests
vérifient le proxy réel, le service inaccessible et l'absence de débordement
horizontal sur ordinateur et mobile. Les captures sont dans `web/test-results`.

Le build produit `web/dist`. `npm --prefix web run preview` le sert sur
<http://127.0.0.1:4173> avec le même proxy local ; garder l'API démarrée.
Il s'agit d'un aperçu local, pas d'un déploiement de production.

## Preview Cloudflare sur main

Une seule application Workers, `mycoradar-preview`, sert le frontend statique :
https://mycoradar-preview.valentinlamede13.workers.dev/
Les builds ne sont déclenchés que par `main`, pas par les PR.
L'API Python/PostGIS n'est **pas hébergée dans ce Worker** : les requêtes
`/api/*` doivent répondre HTTP 503 et JSON `backend_not_deployed` au lieu
de renvoyer trompeusement la page HTML de la SPA.

Le déploiement devra être suivi d'un smoke test HTTP de l'accueil, des fichiers
Vite et du statut API : `node scripts/smoke-preview.mjs` depuis `web/`.
La procédure est décrite dans [CLOUDFLARE_PREVIEW](docs/CLOUDFLARE_PREVIEW.md).

## Organisation et limites

Avant toute intégration de données : consulter le
[registre des fournisseurs, licences, cadences et risques](docs/data-providers.md)
et la [procédure d'admission, de provenance et d'attribution](docs/data-policy.md).
Ce registre prépare les adaptateurs futurs ; aucune source n'est encore activée.


Pour contribuer : [workflow Git et conventions de PR](CONTRIBUTING.md).

- `api/src/mycoradar` : service FastAPI ; `api/tests` : tests HTTP et OpenAPI.
- `web` : React, TypeScript et Vite ; tests de comportement avec Vitest.
- `compose.yaml`, `infra/`, `alembic.ini`, `api/migrations` : environnement local
  et migrations PostGIS du socle géographique et de provenance.
- `.github/workflows/bootstrap.yml` : vérification du socle sous Linux et Windows ;
  `local-environment.yml` : pile Compose, migrations, PostGIS et navigateur réels.
- `docs/MR-001.md` : inventaire, décisions et preuves d'exécution.
- `AGENTS.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `CODEX_PROMPT.md` : instructions
  persistantes et suite du développement.

Les jobs Python et contrats partagés prendront leur place lorsqu'ils auront une
implémentation réelle. MapLibre et le fond cartographique avec attribution
relèvent de MR-008. Aucun calcul scientifique
n'est exécuté par le navigateur.

Un indice sur 100 n'est pas une probabilité. Aucun résultat ne valide
l'identification, la comestibilité ou l'autorisation de cueillette. Les futures
observations personnelles seront privées par défaut.
