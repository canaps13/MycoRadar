# MycoRadar

Plateforme de favorabilité écologique et de conditions de fructification des
champignons, conçue pour la France puis d'autres pays. La Provence est le pilote.

Ce premier incrément (MR-001) fournit une API de santé et une page web connectée.
**Aucune source ingérée, carte ni prédiction scientifique disponible.** La santé
HTTP ne garantit pas la disponibilité des données ou d'une base de données.

## Démarrer en local

Prérequis : Git, Node.js **24.x**, npm et [uv](https://docs.astral.sh/uv/getting-started/installation/).
`uv sync` installe Python 3.12 si nécessaire. Aucune clé fournisseur, aucun compte
cloud et aucune base de données ne sont nécessaires pour MR-001.

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
$env:Path = (Resolve-Path .tools/uv).Path + ';' + $env:Path
```

Si npm rencontre `UNABLE_TO_VERIFY_LEAF_SIGNATURE` sur cette machine, utiliser
`$env:NODE_USE_SYSTEM_CA = '1'` (magasin Windows, vérification TLS conservée).

## Valider

Depuis la racine :

```sh
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
npm --prefix web test
npm --prefix web run format:check
npm --prefix web run build
git diff --check
```

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

## Organisation et limites

- `api/src/mycoradar` : service FastAPI ; `api/tests` : tests HTTP et OpenAPI.
- `web` : React, TypeScript et Vite ; tests de comportement avec Vitest.
- `.github/workflows/bootstrap.yml` : vérification du socle sous Linux et Windows.
- `docs/MR-001.md` : inventaire, décisions et preuves d'exécution.
- `AGENTS.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `CODEX_PROMPT.md` : instructions
  persistantes et suite du développement.

Les jobs Python, migrations, infrastructures et contrats partagés prendront leur
place lorsqu'ils auront une implémentation réelle. PostGIS/Compose et la gestion
de configuration relèvent de MR-003 ; la CI complète relève de MR-004 ; MapLibre
et le fond cartographique avec attribution de MR-008. Aucun calcul scientifique
n'est exécuté par le navigateur.

Un indice sur 100 n'est pas une probabilité. Aucun résultat ne valide
l'identification, la comestibilité ou l'autorisation de cueillette. Les futures
observations personnelles seront privées par défaut.
