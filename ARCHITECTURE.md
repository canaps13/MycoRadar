# MycoRadar — Architecture de référence et décisions

**Statut :** proposition révisable après inspection du code existant. Ne pas réécrire un dépôt déjà structuré pour coller artificiellement à ce document.

**État du socle :** FastAPI/Pydantic expose la santé HTTP et, avec MR-003,
la disponibilité de PostGIS et des migrations. React/TypeScript/Vite affiche
une page reliée à la santé HTTP. Les ADR-001 à ADR-004 restent les règles du
développement à venir ; les pipelines, scores, features, MapLibre, cache
et orchestration décrits ci-dessous ne sont pas encore implémentés.

MR-006 ajoute le schéma géographique et de provenance par migration Alembic,
sans données de référence préchargées ni tables de scores/features. Voir ADR-006
et [le contrat de stockage](docs/database-schema.md).

## ADR-001 — Calcul côté serveur, présentation côté client

**Décision :** modèles et traitements géospatiaux côté backend ; le frontend cartographie, filtre et compare des résultats pré-calculés. Une revalidation horaire dans le navigateur n'exécute pas l'inférence sur toutes les cellules.

**Pourquoi :** modèles cohérents et versionnés ; coûts contrôlés ; protection des accès fournisseurs ; cache partageable ; calcul unique au lieu de répétition par utilisateur ; audit possible.

## ADR-002 — Distinction écologique et temporelle

Créer deux notions indépendantes :

- `habitat_favorability`: aptitude relativement stable d'une cellule pour l'espèce (arbres, sol, altitude, climat, exposition et couverture disponibles).
- `fruiting_conditions`: opportunité temporelle de fructification (pluie, humidité/indicateur de sécheresse, température, saison, éventuellement prévisions).

Ne pas multiplier naïvement deux scores en prétendant obtenir une probabilité. Calibration et évaluation indépendante avant prédictions probabilistes chiffrées.

## ADR-003 — Versionnage et traçabilité de données

Pour toute donnée/champ : origine, licence, date d'observation, date de publication, date de collecte, CRS, résolution/uncertainty, version/empreinte, géométrie d'origine, transformations, indicateurs de qualité.

Pour toute prédiction : modèle, version, jeux sources, run, timestamp calcul/publication, échéance, maille réelle, qualité, explication, statut (`fresh`, `stale`, `partial`, `unavailable`).

## ADR-004 — Cadence hybride, pas de recalcul mondial chaque heure

- Cron horaire : **polling léger** version/horodatage et mise en file des changements.
- Job métier : validation, ingestion par tranche et recalcul **incrémental**.
- Quotidien : contrôle de complétude, reprise des échecs, nouveau snapshot si pertinent.
- Frontend : cache et revalidation **au maximum par heure** si ouvert, plus revalidation à l'interaction ; si source non renouvelée, afficher l'âge réel.
- Données statiques : mise à jour sur édition, pas chaque nuit.
- Prévisions : stockage de l'heure d'émission et de l'horizon, et invalidation de la sortie quand les prévisions changent.
- Modèles ML : entraînement périodique hors requêtes utilisateurs ; publication contrôlée après comparaison et validation.

Ne pas utiliser un Worker Cloudflare comme serveur de calcul raster/ML massif ; utiliser un exécuteur Python dédié aux tâches lourdes.

## Stack proposée

### ADR-005 — Socle retenu pour MR-001

**Statut :** adopté par la PR #1, fusionnée le 29 octobre 2026
([preuve](https://github.com/canaps13/MycoRadar/pull/1)).

**Contexte :** le dépôt initial ne contenait que les quatre documents de cadrage.
Une API indépendante et une page légère suffisent pour le premier incrément.

**Décision :** monorepo `api/` (Python 3.12, FastAPI, Pydantic) et `web/`
(Node 24, React, TypeScript, Vite). Dépendances verrouillées avec uv et npm.
Le frontend interroge `/api/health` ; le proxy Vite local retire `/api` avant de
transmettre à `/health`. Cette route vérifie la vie du service HTTP, sans vérifier
une base ni la disponibilité de données scientifiques. Aucun endpoint de score
n'est publié. Les états du frontend sont explicitement distincts de la santé API.

**Conséquences :** conserver les services existants ; ajouter la base et ses
migrations dans MR-003/MR-006, la cartographie dans MR-008 et les calculs uniquement
côté backend. Le proxy Vite n'est pas une configuration de déploiement production.
Pas de rendu serveur Next.js, service worker ou infrastructure cloud sans besoin
observé. Une évolution durable devra préciser contexte, décision, conséquences
et preuve dans une nouvelle ADR numérotée, sans effacer l'historique existant.

### Cible pour les tâches suivantes

MR-003 ajoute Compose pour le développement, une migration PostGIS initiale et
`/ready`. La migration vérifie l'extension de manière idempotente ; son retour
à `base` retire le marqueur de révision et conserve PostGIS, qui peut préexister.
Les migrations ne sont jamais lancées par une requête HTTP : Compose les exécute
dans un service dédié avant l'API. Le schéma métier et ses contraintes restent
à MR-006. La disponibilité technique ne vaut ni couverture ni fraîcheur des données.

```text
web/       TypeScript + React (Next ou Vite selon existant) + MapLibre
api/       Python + FastAPI + Pydantic + OpenAPI
workers/   Python ETL + features + calcul de scores + outillage ML
infra/     Compose dev, migrations, CI, IaC minimal si possible
schemas/   Contrats JSON / OpenAPI partagés
```

Dépendances recommandées : PostgreSQL/PostGIS et Alembic ; Pytest ; Ruff ; mypy ou pyright ; Vitest et Playwright pour les tests web ; Docker Compose local ; déploiements de staging reproductibles. **Ne pas multiplier les services sans besoin avéré.**

## Endpoints cibles

### Publication géographique MR-009 — Catalogue pré-calculé

L'API géographique initiale lit au démarrage un catalogue pré-calculé, typé,
borné et vérifié par SHA-256. Elle ne dépend pas d'une ingestion PostGIS en ligne et ne recopie pas
le job MR-007 ; les migrations MR-006 sont conservées séparément. La même publication et les mêmes métadonnées
seront conservées lorsqu'un adaptateur de persistance sera nécessaire ; ce choix
ne remplace pas PostGIS comme cible de stockage. Aucun calcul scientifique en
requête. Voir le [contrat, limites et exploitation](docs/MR-009.md).

Les routes `/v1/regions`, `/v1/species`, `/v1/cells`, `/v1/metadata` sont ajoutées
par MR-009 ; l'absence de publication de taxonomie/grille est explicite. Les
endpoints de prédiction ci-dessous restent des cibles, sans score publié.

- `GET /health`, `GET /ready`
- `GET /v1/regions?country=FR`
- `GET /v1/species?region_id=...`
- `GET /v1/predictions?bbox=...&taxon_id=...&valid_at=...&layer=habitat|fruiting`
- `GET /v1/cells/{cell_id}/explanation?taxon_id=...&valid_at=...`
- `GET /v1/data-status` : âge, source, heure de calcul et zones couvertes

Gestion pagination/limit et bounding box afin d'éviter requêtes incontrôlées. Prévoir un rendu par tuiles sur grande zone ; ne pas renvoyer toutes les cellules de France dans une réponse JSON.

## PostGIS — schéma conceptuel

- `regions(id, country_code, name, geometry, timezone, enabled)`
- `cells(id, grid_system, resolution_m, geometry, region_id, land_fraction)`
- `taxa(id, scientific_name, authority, gbif_taxon_key, status)`
- `source_datasets(id, provider, product, licence, attribution, spatial_resolution_m, ingestion_policy)`
- `source_versions(id, dataset_id, source_published_at, fetched_at, checksum, status)`
- `occurrences(id, taxon_id, event_date, geometry, location_uncertainty_m, source_version_id, verification_status, visibility)`
- `features(cell_id, feature_date, feature_version, measurements, quality)`
- `prediction_runs(id, model_version, started_at, completed_at, input_versions, status)`
- `predictions(cell_id, taxon_id, valid_at, habitat_score, fruiting_score, confidence, coverage, run_id, explanation)`

Recommandation d'index : GiST sur geometries, composites `cell_id + taxon_id + valid_at + run_id`, partitionnement selon volume après mesure.

## ADR-006 — Schéma géospatial et provenance (MR-006)

**Décision :** conserver SQLAlchemy/Alembic et des migrations SQL PostGIS
explicites, sans ajouter d'ORM géospatial ni générer des tables à l'import HTTP.
`0002_geospatial_foundation` ajoute pays/régions, cellules, relations cellule/région,
taxons, fournisseurs, produits, versions de sources, occurrences, runs et entrées
de runs. Aucune géométrie ou observation réelle n'est insérée par la migration.

Les géométries canoniques sont en EPSG:4326, 2D, non vides et valides ; régions
et cellules sont des MultiPolygon, occurrences des Point. Des contraintes
explicites remplacent les typmods pour rejeter aussi le SRID 0 : un typmod 4326
peut attribuer ce SRID à une entrée inconnue sans reprojection. Les adaptateurs
devront connaître le CRS initial, conserver le brut et tracer la transformation.

Les cellules existent indépendamment des régions et s'y rattachent par une
relation multiple, permettant les frontières sans dupliquer l'identifiant de
grille. `resolution_m` est le pas nominal de grille, distinct de la résolution
effective des sources ou des futurs résultats. Cette dernière peut rester nulle.

La provenance est portée par des clés étrangères sans suppression en cascade,
une empreinte SHA-256, les dates de source/collecte et les versions liées à un
run. Les occurrences sont privées et non vérifiées par défaut. Les données
inconnues restent nulles, les sources commencent en attente, les régions désactivées.
Les règles de droits et de diffusion devront être appliquées par les adaptateurs
et API ; ces états SQL ne constituent pas un contrôle d'accès utilisateur.

**Conséquences :** validation des géométries au chargement, index GiST et index
de jointure, aucun calcul scientifique en requête HTTP. Le downgrade retire les
11 tables métier et leurs données, conserve PostGIS et refuse les dépendances
externes au lieu d'utiliser CASCADE. Son exécution réelle hors base de test
requiert l'approbation spécifique prévue par AGENTS.md. Les tests utilisent
uniquement une base isolée explicitement activée. Voir
[contrat, limites et exemples SQL](docs/database-schema.md),
[preuves MR-006](docs/MR-006.md).

## Sécurité, confidentialité, environnement

[ADR-008](docs/adr/008-occurrence-privacy.md) définit la frontière de prépublication
MR-048 : politique revue et expirante, refus par défaut, conservation du floutage,
cinq sorties contrôlées et diagnostics sans données privées. Les futurs adaptateurs
d'occurrences et caches doivent l'intégrer ; aucun serveur d'occurrences n'est
publié par cette unité.

- Pas de clé d'API côté navigateur ; `.env.example`, vrais secrets hors contrôle de version.
- Aucune coordonnée personnelle de cueillette rendue publique par défaut ; position vague ou agrégée pour espèces sensibles.
- Limitation des appels API, validation de bbox, authentification des opérations admin, RBAC des comptes.
- Règles RGPD adaptées : finalité, conservation minimale, export/suppression, consentement de géolocalisation.
- Afficher qu'aucun score ne valide une identification ou la comestibilité.
- Les réglementations de cueillette, de propriété et de feu de forêt varient : ne pas afficher « autorisé » sans source officielle vérifiée et datée.

## Scénarios techniques de test prioritaires

1. Fournisseur météo répond `429`, puis reprend : backoff, pas de spam, conservation dernier snapshot.
2. Fournisseur publie le même lot deux fois : idempotence et absence de doublons.
3. Nouveau lot incomplet : pas de publication partielle silencieuse ; statut `partial` ou conservation du dernier sain.
4. Coordonnées observation imprécises/floutées : ne pas attribuer à tort à une cellule 50 m.
5. Passage de minuit et fuseaux horaires de France / autres pays : date d'observation distincte de date de calcul.
6. Absence de météo pertinente : `fruiting_score = null`, pas de score inventé.
7. Regression ML : baseline conserve sa place si nouveau modèle moins performant hors échantillon.
8. L'utilisateur ouvre un grand bbox : pagination/tiles, limites et performance surveillées.

## Indicateurs d'exploitation

- âge des dernières données publiées et âge par source
- taux de jobs réussis / retentatives / rejoués, temps de publication
- couverture de cellules effectivement modélisées et ratio « données insuffisantes »
- latence p95 de l'API et erreurs par endpoint
- coût par région/espèce et par lot de calcul
- performance ML *par espèce et par région*, avec dates de validation et incertitude

## ADR-007 — Job de grille et masques (MR-007)

Le support de grille est généré hors HTTP par un job Python borné, avec IDs
globaux EPSG:6933, inputs publics versionnés, masques à couverture explicite et
publication atomique sans écrasement. Il ne calcule aucun score et n'active
aucune ingestion forestière réelle. Les groupes de dépendances isolent ce calcul
du runtime HTTP. Voir la [décision](docs/adr/007-grid-job.md), le
[contrat](docs/grid-job.md) et les [preuves](docs/MR-007.md).

MR-012 ajoute un job de normalisation de couches polygonales publiques :
empreintes, découpage égale-aire, catégories et millésimes explicitement inconnus
si absents. Il ne déduit pas d'absence de forêt ni de masque MR-007 à partir des
zones non cartographiées. `infra/api.Dockerfile` offre une cible explicite
`geo-job` avec le groupe géographique existant ; sa cible par défaut `api`
conserve Uvicorn sans ces dépendances lourdes. Aucun calcul géographique en
requête HTTP. [Contrat et limites](docs/MR-012.md).
