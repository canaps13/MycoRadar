# MycoRadar — Roadmap produit et technique

**Version :** 1.1 — 29 octobre 2026  
**Statut initial :** à démarrer ; ne pas présenter les étapes comme réalisées sans preuve dans le dépôt.  
**Zone pilote :** Provence (Bouches-du-Rhône, Var, Vaucluse) ; **produit cible :** France entière, puis Europe/international.  
**Objectif :** fournir, par espèce et par territoire, une carte de favorabilité de l'habitat, une estimation des conditions de fructification actuelles et futures, l'incertitude, les facteurs explicatifs, la fraîcheur et la provenance des données.

## Priorité de livraison : un pilote vérifiable avant la couverture nationale

- **Tranche A, socle visible :** CI et un seul Worker pour `main`, retour API honnête, carte responsive d'un territoire pilote avec fond légal, métadonnées et couches réellement disponibles, sans score de fructification inventé. Voir [plan MVP](docs/MVP_DELIVERY.md).
- **Tranche B, pilote scientifique :** après audit de couverture, sélectionner **une** des quatre espèces candidates et une zone de Provence ; importer les observations et sources météo/forêt nécessaires en respectant les licences, puis établir une baseline explicable. Ne pas promettre quatre espèces simultanément si la couverture est insuffisante.
- **Tranche C, extension :** ne passer à quatre espèces et plusieurs territoires qu'après preuve d'un gain sur une validation indépendante. Une belle carte n'est pas une preuve de prédiction fiable.
- **Gate scientifique obligatoire avant MR-016/MR-017 :** suivre le [protocole d'évaluation](docs/SCIENTIFIC_VALIDATION.md) (échantillonnage, effort, doublons, précision, découpage spatial/temporal, baselines et critères d'échec). Interdire les scores 0–100 non justifiés scientifiquement.
- **Trois mesures distinctes :** `display_cell_size_m` (maille de rendu), `effective_resolution_m` (résolution démontrée par les données/modèle) et `location_uncertainty_m` (incertitude des observations). Elles ne doivent jamais être déduites l'une de l'autre.
- **Infrastructure :** la [note de décision d'hébergement](docs/DEPLOYMENT_DECISION.md) impose un budget, une stratégie API Python + PostGIS séparée et un plan de sécurité avant mise en ligne des endpoints de données. Aucune ressource payante ou donnée sensible n'est provisionnée implicitement.

## Règles de produit incontournables

- `score_habitat` (aptitude écologique relativement stable) et `score_fructification` (conditions temporelles) sont distincts. Un score 0–100 **n'est pas automatiquement une probabilité statistique**. N'afficher un pourcentage de probabilité qu'après calibration et validation indépendantes.
- Pas de promesse de localisation réelle à 10 m sur la base d'une grille graphique fine. Chaque mesure/score porte une résolution effective, la couverture et un niveau de confiance. Les microzones 50–100 m sont une **hypothèse expérimentale**.
- Une observation positive ne fournit pas automatiquement de vraies absences. Corriger l'effort d'observation, la géoprécision, le biais spatial et la fuite temporelle.
- Ne jamais présenter un score comme une confirmation d'identification ou de comestibilité. Protéger les espèces et localisations sensibles. Respecter réglementations et restrictions locales d'accès.
- Aucune donnée simulée n'est affichée en production comme une prévision réelle. Les démonstrations sont étiquetées « démonstration / données fictives ».
- L'architecture métier ignore les découpages administratifs français : territoires, providers, couches, espèces et calendriers sont configurables par pays/région.
- Une tâche à la fois, tests observés, preuve par commit/PR ; ne jamais annoncer un déploiement ou un résultat sans l'avoir constaté.

## Critères de succès V1 pilote

- Carte responsive, filtre espèce/date, clic sur cellule/secteur, couche explicative, horodatage, provenance, qualité des données, message explicite si indisponible.
- Quatre espèces pilotes : **Lactarius sanguifluus**, **Boletus aereus**, **Boletus edulis**, **Cantharellus cibarius**, sous réserve de couverture suffisante des données et vérification taxonomique.
- Pipeline météo vérifiant les sources **au moins chaque heure** et publication quotidienne (ou plus souvent lorsqu'il y a une donnée nouvelle) des résultats affectés. Les données sources peuvent être plus anciennes ; l'interface le signale.
- Ingestion reproductible d'au moins une source d'occurrences, une source météo, une source de couverture forestière et une source de terrain/sol, en provenance réelle et sous licence vérifiée.
- Tests unitaires, d'intégration, géospatiaux et CI verts ; observabilité, sécurité, documentation d'exploitation ; comparatif avec baseline et rapport de validation honnête.

## Architecture cible indicative (à ajuster après inspection du dépôt)

- **Web** : TypeScript, Next.js ou React/Vite selon l'existant, MapLibre GL JS, client géospatial léger ; revalidation de cache HTTP (ETag/TTL), pas d'inférence lourde dans le navigateur.
- **API** : Python 3.12+, FastAPI, Pydantic, contract OpenAPI ; servir résultats pré-calculés, métadonnées et géométries simplifiées.
- **Données** : PostgreSQL + PostGIS ; migrations Alembic ; fichiers de couches volumineuses et exports GeoParquet/COG dans stockage objet compatible S3 (Cloudflare R2 possible).
- **Pipelines** : workers Python (CLI et/ou conteneurs) avec tâches idempotentes, file d'événements, « watermark »/version des fournisseurs, retries bornés, ingestion incrémentale.
- **Orchestration** : Cloudflare Cron/Queues ou planificateur équivalent pour détecter/publier et répartir les tâches ; exécuteur conteneurisé pour imports, traitement raster, entraînement et recalcul lourds. Ne pas lancer le ML lourd dans un Worker HTTP.
- **Déploiement** : frontend Cloudflare si pratique, API Python sur service adapté, base PostGIS managée ou autohébergée ; environnements `local`, `staging`, `production` ; secrets hors Git.
- **Territoires** : entités `region`, `country`, `grid_cell`, `data_provider`, `layer_version`, `taxon`, `prediction_run`, `observation` ; CRS, unité, licence et incertitude stockés systématiquement.

### Actualisation : stratégie à respecter

1. **Toutes les heures**, un déclencheur léger vérifie versions/horodatages disponibles des sources météo et des observations. Gestion des quotas, journaux, retries et alertes.
2. Lorsqu'une source a réellement changé, importer seulement la plage concernée, valider et recalculer les régions/cellules affectées. Les mises à jour doivent être **idempotentes**.
3. **Chaque jour**, vérifier les lots absents et publier au plus tard une nouvelle version vérifiée des résultats concernés **si les données nécessaires sont disponibles**. Ne pas prétendre que la fraîcheur du fournisseur est meilleure qu'elle n'est.
4. Publier des snapshots **atomiques** (un `run_id`, `model_version`, `data_cutoff`, `computed_at`, `effective_resolution_m`, `coverage_status`). Garder le dernier résultat sain en cas d'échec, marquer `stale` et alerter.
5. Le frontend peut vérifier la nouvelle version toutes les heures, mais évite tout calcul scientifique lourd. ETag, cache par territoire/espèce/échéance, expiration et invalidation contrôlée.
6. Forêts, relief et sols : ingestion **sur nouvelle édition des sources**, pas une recopie quotidienne inutile ; entraînement ML périodique sur nouveaux jeux validés, pas à chaque visite.

## Phases et tâches séquentielles

Statuts autorisés : `TODO`, `IN_PROGRESS`, `BLOCKED`, `DONE`. **Une tâche est `DONE` seulement si son critère d'acceptation a été réellement vérifié.** Les tâches ci-dessous sont initialement `TODO`.

### P0 — Initialisation, gouvernance et preuves (prérequis)

| ID | Statut | Tâche | Critère de validation |
|---|---|---|---|
| MR-001 | DONE | Vérifier dépôt, branche par défaut, droits, CI, code existant et documents ; créer structure initiale adaptée (monorepo uniquement si pertinent) | API/web exécutables, 3 tests API, 6 tests React et 4 tests navigateur réussis ; CI Linux/Windows verte sur `359007e` ([exécution](https://github.com/canaps13/MycoRadar/actions/runs/40770178926), [PR #1](https://github.com/canaps13/MycoRadar/pull/1)) ; [inventaire et preuves](docs/MR-001.md). |
| MR-002 | DONE | Ajouter `AGENTS.md`, roadmap versionnée, ADR architecture et conventions PR | Guide, modèle de PR, ADR-005 et contrôle testable ; 23 tests Python réussis, CI Linux/Windows et conventions vertes sur `f718cd8` ([PR #2](https://github.com/canaps13/MycoRadar/pull/2), [preuves](docs/MR-002.md)). |
| MR-003 | DONE | Mettre en place environnement local : frontend, API santé, PostGIS via Compose, `.env.example`, migrations | Pile Compose saine, migration/rejeu/reprise testés, 34 tests Python locaux dont 3 PostGIS, 4 tests navigateur ; CI Compose et Bootstrap Linux/Windows vertes sur `ecff421` ([PR #3](https://github.com/canaps13/MycoRadar/pull/3), [preuves](docs/MR-003.md)). |
| MR-004 | DONE | Ajouter GitHub Actions CI (lint, format, types, unit tests, builds, `git diff --check`) | CI Linux/Windows et Compose/PostGIS vertes sur `e1d067a` ; lint/format/types, 32 tests Python, 6 React et 4 navigateur par OS, 3 intégrations PostGIS ; résumés testés distinguant les étapes non exécutées ([PR #4](https://github.com/canaps13/MycoRadar/pull/4), [preuves](docs/MR-004.md)). |
| MR-005 | DONE | Préparer gestion des licences, conformité, attribution et registre de fournisseurs | Registre de 11 produits/accès, droits/cache/redistribution/attribution/cadences et risques sourcés au 2026-10-29 ; procédure d'admission et 5 captures catalogue ; CI Linux/Windows, Compose/PostGIS et conventions vertes sur `c94b1e4` ([PR #7](https://github.com/canaps13/MycoRadar/pull/7), [preuves](docs/MR-005.md)). |
| MR-041 | DONE | Installer une preview Cloudflare unique sur `main`, sans previews de PR | 29/10/2026 : Worker unique `mycoradar-preview` sur `main`, Cloudflare Builds main-only avec chemins `web/*`, URL `https://mycoradar-preview.valentinlamede13.workers.dev` ; build `5ecf7466-aaf3-4645-93fe-34aca0ba1fe8` sur le commit `d8b3b93` réussi ; smoke HTTP confirme accueil et assets 200, `/api/health` 503 JSON ; previews secondaires désactivées. API FastAPI/PostGIS non déployées. |
| MR-043 | IN_PROGRESS | Clarifier les jalons MVP, l'architecture d'hébergement API et les gates de validation scientifique avant les scores | Plan MVP et critères d'acceptation documentés ; ADR d'hébergement avec budget/risques ; protocole d'évaluation avant MR-016 ; dépendances explicites, CI de documentation vérifiée |
| MR-049 | BLOCKED | Séparer les autorisations : jeton Workers Builds dédié MycoRadar, protections de branche main avec checks requis | Un jeton nouveau limité à MycoRadar remplace le jeton partagé, sans casser Plume ; branche main protégée contre les pushes/fusions sans checks ; nécessite droits admin GitHub et API Tokens Cloudflare non disponibles actuellement |

**Jalon M0 :** repo propre, stack exécutable, PR CI verte, décisions documentées.

### P1 — Fondations géospatiales et cartographie

| ID | Statut | Tâche | Critère de validation |
|---|---|---|---|
| MR-006 | DONE | Schéma PostGIS (pays/régions, grille, espèces, occurrences, versions de couches, runs) + Alembic | Migration 11 tables, contraintes SRID/type/2D et index, exemples SQL testés ; 83 tests Python locaux dont 51 PostGIS ; CI Linux/Windows et Compose/PostGIS vertes sur `95024da` ([PR #11](https://github.com/canaps13/MycoRadar/pull/11), [preuves](docs/MR-006.md)). |
| MR-007 | DONE | Grille géographique multi-résolution (`cell_id` stable), territoires pilotes config et masques de forêts | Job hors HTTP, grille EPSG:6933, contours IGN réels tracés, masques à couverture explicite ; 41 nouveaux tests, 73 tests unitaires Python et CI Linux/Windows/Compose vertes sur `8ffbeb8` ; masques réels indisponibles avant MR-012 ([PR #13](https://github.com/canaps13/MycoRadar/pull/13), [preuves](docs/MR-007.md)). |
| MR-008 | DONE | Carte MapLibre : cadrage Provence, fond cartographique légal, légende, zoom, sélection secteur | [PR #14](https://github.com/canaps13/MycoRadar/pull/14), code `52452b9` : 10 tests navigateur bureau/mobile, 8 React, 2 Worker et 2 packaging ; Bootstrap Linux/Windows, Compose/PostGIS et conventions verts ; contours IGN et fond Natural Earth attribués, sans score ; [preuves et captures](docs/MR-008.md), [reçu CI](docs/evidence/MR-008-ci.json). |
| MR-009 | DONE | API `/v1/regions`, `/v1/species`, `/v1/cells`, `/v1/metadata` paginée et documentée | [PR #15](https://github.com/canaps13/MycoRadar/pull/15), code `51a9cb9` : 88 tests Python dont 56 catalogue, 6 navigateur ; OpenAPI, pagination/version, bbox bornée, provenance IGN et erreurs typées ; Linux/Windows, Compose/PostGIS et conventions verts ; [preuves](docs/MR-009.md), [reçu CI](docs/evidence/MR-009-ci.json). |
| MR-044 | IN_PROGRESS | Livrer une tranche carte verticale Provence, pour une espèce pilote, sans résultat scientifique fictif | [PR #17](https://github.com/canaps13/MycoRadar/pull/17), code `738c497` : carte/API, date, provenance, états et paquet Docker vérifiés ; 148 tests Python, 51 PostGIS en CI et 16 navigateur ; Linux/Windows, Compose et conventions verts ([preuves et captures](docs/MR-044.md), [reçu CI](docs/evidence/MR-044-ci.json)). Admission d'une espèce réelle encore attendue de MR-010/MR-045 : sélecteur désactivé, aucun score ; une fixture synthétique ne clôture pas ce critère. |

**Jalon M1 :** carte et API connectées à de vrais territoires, sans prédiction fictive masquée.

### P2 — Collecte vérifiable des données publiques

| ID | Statut | Tâche | Critère de validation |
|---|---|---|---|
| MR-048 | TODO | Filtrer à l'ingestion les géolocalisations et taxons sensibles avant leur diffusion ou mise en cache | Tests prouvant l'absence de fuite dans API, tuiles, exports, journaux et URLs ; floutage des positions conservé ; règles de conservation et accès documentées |
| MR-010 | TODO | Adaptateur occurrences GBIF (éventuellement INPN/OpenObs) + mapping taxonomique | Import test sur échantillon réel, pagination/download, déduplication, licence, précision coordonnées et provenance |
| MR-045 | TODO | Audit de faisabilité d'une seule espèce pilote : abondance, biais spatiaux/temporels, effort d'échantillonnage et précision | Échantillon réel légal, tableau couverture par saison/région, distribution des incertitudes, doublons et non-détections ; espèce pilote justifiée ou statut BLOCKED faute de données suffisantes |
| MR-011 | TODO | Adaptateur météo historique et prévisions disponibles (Météo-France France, fallback configurable) | Historique + météo récente + prévision différenciés ; quotas/rate limits testés ; attribution |
| MR-012 | TODO | Couches forêts / landcover (IGN France, couches globales par extension) | Types de végétation et année du jeu source visibles ; géométries nettoyées |
| MR-013 | TODO | Couches sols, géologie, relief ; fallback SoilGrids (WCS/WebDAV ou fichiers si API indisponible), IGN/BRGM | Provenance/résolution/âge/valeurs manquantes gérés ; tests avec petits fixtures |
| MR-014 | TODO | Pipeline géospatial de jointure, features datées et tests qualité | Rejouable, idempotent, sans fuite d'information postérieure aux dates observées |
| MR-046 | TODO | Protocole d'évaluation indépendant préalablement aux baselines : espace, temps, effort et pseudo-absences | Découpage spatial bloqué et test chronologique gelés, contrôle anti-fuite, baselines naïves, métriques et seuils de non-publication écrits avant MR-016/MR-017 |

**Jalon M2 :** vraie base de données pilote traçable, robuste aux pannes fournisseurs.

### P3 — Moteur initial de favorabilité (sans ML opaque)

| ID | Statut | Tâche | Critère de validation |
|---|---|---|---|
| MR-015 | TODO | Catalogue taxonomique + règles écologiques par espèce sourcées | Quatre espèces, associations forestières documentées, seuils configurables, incertitudes explicites |
| MR-016 | TODO | Baseline habitat (règles explicables) + qualité des sources | `score_habitat` 0–100 qualifié d'indice, raisons et `data_quality` ; tests bornes/NA |
| MR-017 | TODO | Baseline fructification : cumuls de pluie, sécheresse antérieure, température, saisonnalité | `score_fructification` calculé seulement si couverture suffisante ; comparaison avec scenarios synthétiques |
| MR-047 | TODO | Backtesting des facteurs météo et des horizons de fructification avant publication prospective | Comparer observation, réanalyse et prévision sans mélange ; date d'émission et valid_at séparées ; résultats par horizon, contrôle saison/territoire et statut unavailable si qualité insuffisante |
| MR-018 | TODO | API `/v1/predictions`, versioning, fraîcheur, détails explicatifs | Modèle de réponse stable ; `computed_at`, `data_cutoff`, `status`, `confidence`, `effective_resolution_m` |
| MR-019 | TODO | Carte en couches habitat/fructification, fiche espèce, filtre date, comparaison secteurs | UX mobile validée ; information « score ≠ probabilité » visible ; états vides/stale |

**Jalon M3 :** V1 exploratoire exploitable, scores transparents et aucune précision inventée.

### P4 — Automatisation robuste et exploitation

| ID | Statut | Tâche | Critère de validation |
|---|---|---|---|
| MR-020 | TODO | Polling horaire, jobs d'ingestion idempotents, queues et gestion des quotas | Simulation nouvelles données/aucun changement/429/timeout ; aucune double ingestion |
| MR-021 | TODO | Recalcul incrémental région/espèce/échéance + snapshot atomique | Rejouer deux fois n'altère pas les résultats ; rollback vers dernière version saine |
| MR-022 | TODO | Publication quotidienne contrôlée, cache CDN/ETag, invalidation et tests d'horloge | Cas nouvelle donnée, données anciennes, retard fournisseur, échec pipeline ; timestamps visibles |
| MR-023 | TODO | Observabilité (logs structurés, métriques âge données, runs, alertes), sauvegardes et runbook | Échec injecté détecté ; procédure reprise documentée et testée |

**Jalon M4 :** publication autonome vérifiable et résiliente ; « actualisé » signifie précisément ce qui l'est.

### P5 — IA scientifique, calibration et évaluation indépendante

| ID | Statut | Tâche | Critère de validation |
|---|---|---|---|
| MR-024 | TODO | Nettoyage observations, qualité taxonomique et effort de prospection | Audit des coordonnées floutées, doublons, biais de collecte, données sensibles |
| MR-025 | TODO | Protocole train/test spatial et temporel ; pseudo-absences/biais d'échantillonnage | Protocole écrit avant évaluation ; zones et saisons test tenues à l'écart |
| MR-026 | TODO | Baselines statistiques + premier modèle (ex. GAM/MaxEnt/LightGBM) | Comparaison explicite aux règles et météo simple, courbes de qualité et intervalles |
| MR-027 | TODO | Calibration si possible, incertitude, explications et model cards | Pas d'affichage « probabilité % » sans calibration prouvée ; résultats par espèce/région |
| MR-028 | TODO | Validation terrain documentée, y compris sorties sans trouvaille, si protocole fiable | Protocole d'effort, biais, validation indépendante, rapport reproductible |
| MR-029 | TODO | Expérience pilote microzones 100 m puis 50 m uniquement si gain démontré | Comparaison à échelles plus grossières, étude d'incertitude, aucune extrapolation abusive |

**Jalon M5 :** premiers modèles comparés à des baselines, preuves publiques de performance et limites.

### P6 — Compte, contribution, confidentialité, conformité

| ID | Statut | Tâche | Critère de validation |
|---|---|---|---|
| MR-030 | TODO | Auth facultative, carnet de sorties géolocalisées privé, consentement et export | Contrôle d'accès testé, suppression/export, aucune fuite de coordonnées privées |
| MR-031 | TODO | Formulaire de trouvailles et non-trouvailles + effort de prospection | Données structurées, validation, qualité, distinction absence observée/non-détection |
| MR-032 | TODO | Protection localisations sensibles, sécurité des espèces, mentions identification | Fuzzing/agrégation selon sensibilité ; disclaimer de comestibilité explicite |
| MR-033 | TODO | Accessibilité et réglementation d'accès (si sources maintenues) | Sources officielles datées, état inconnu visible, pas de faux « accès autorisé » |

**Jalon M6 :** communauté contributive sans exposer les coins ni les données personnelles.

### P7 — Couverture France et international

| ID | Statut | Tâche | Critère de validation |
|---|---|---|---|
| MR-034 | TODO | Déployer régions métropolitaines progressivement après validation pilote | Coûts, quotas, performance, qualité région par région ; états « insuffisant » |
| MR-035 | TODO | Provider registry multi-pays, taxonomie et calendriers locaux | Ajouter un pays sans modifier le moteur métier ; fuseaux et langues gérés |
| MR-036 | TODO | Localisation multilingue, conformité pays, politique cartographie | Une région hors France opérationnelle en staging, licence et restrictions documentées |
| MR-037 | TODO | Industrialiser tuiles vectorielles/raster et pré-calcul à grande échelle | Benchmarks temps de réponse/coût/stockage et stratégie de partition prouvés |

**Jalon M7 :** France entière puis extension pays par pays, sans refonte de l'architecture.

### P8 — Fonctions différenciantes / premium (après preuve de qualité)

| ID | Statut | Tâche | Critère de validation |
|---|---|---|---|
| MR-038 | TODO | Comparateur de forêts et classement contextualisé | Comparabilité sourcée, explications et niveaux de confiance |
| MR-039 | TODO | Alertes de changements de conditions, abonnements opt-in | Notifications bornées, unsubscribe, anti-spam, pas de fausse assurance |
| MR-040 | TODO | API partenaires / chercheurs, tableaux de bord biodiversité | Contrôles de confidentialité/licence, quotas et audit d'utilisation |

### Correctif transversal de livraison — sécurité de preview

| ID | Statut | Tâche | Critère de validation |
|---|---|---|---|
| MR-042 | DONE | Durcir la preview Cloudflare unique de main : API indisponible explicite, pas de previews secondaires, tests Worker et vérification HTTP post-déploiement | PR #8 fusionnée au commit `d8b3b93` ; tests worker (2), Bootstrap Linux/Windows, Compose/PostGIS et conventions verts ; Worker API 503 sans backend, preview_urls=false ; commande Cloudflare `npx --yes wrangler@4 deploy && node scripts/smoke-preview.mjs` exécutée avec succès sur le build `5ecf7466-aaf3-4645-93fe-34aca0ba1fe8` et URL HTTP testée. Token dédié et protection de main non effectués : MR-049 BLOCKED. |

La rotation vers un jeton Cloudflare dédié et la protection GitHub de main demandent des permissions d'administration distinctes ; elles ne sont pas réputées réalisées.

## Modèle minimal de résultat prévisionnel

```json
{
  "cell_id": "pilot:cell-identifier",
  "taxon_id": "taxon-identifier",
  "valid_at": "2026-10-29T12:00:00Z",
  "habitat_score": 72,
  "fructification_score": null,
  "score_semantics": "relative_favorability_index_not_probability",
  "confidence": "low",
  "coverage_status": "partial",
  "effective_resolution_m": 250,
  "computed_at": "2026-10-28T05:12:00Z",
  "data_cutoff": "2026-10-27T00:00:00Z",
  "model_version": "baseline-0.1.0",
  "run_id": "example-not-real",
  "status": "illustrative_example",
  "factors": [],
  "sources": []
}
```

Ce JSON est un **exemple de contrat**, pas une prédiction ni un jeu de données réel.

## Protocoles pour chaque PR

1. Vérifier branche et remote ; `git fetch --all --prune` avant toute modification ; dépôt propre ou branche indépendante sans écraser du travail non commité.
2. Choisir **la première tâche `TODO` dont les dépendances sont satisfaites**, sans entreprendre plusieurs phases dans une seule PR ; branche `feat/MR-XXX-description`.
3. Implémenter verticalement une tranche fonctionnelle testable (code, tests, docs et migrations si requises).
4. Exécuter tests et CI (pas seulement « écrire des tests »), `git diff --check`, scan secrets/dépendances pertinent ; publier résultats réels et limites.
5. Ouvrir PR avec ID tâche, objectif, risques, tests observés, captures si UI, critères de recette et plan de rollback. Ne pas merger si les checks requis manquent, échouent ou si la protection bloque.
6. Mettre la tâche à `DONE` **après validation réelle**, avec SHA/PR ou lien vers preuve ; sinon `IN_PROGRESS` ou `BLOCKED`. Synchroniser la roadmap dans la PR.
7. Pas de déploiement production, secrets, frais cloud ni écriture dans un autre dépôt sans autorisation distincte.

## Sources à auditer avant intégration

- GBIF occurrence API : https://techdocs.gbif.org/en/openapi/v1/occurrence
- Météo-France (catalogue) : https://www.data.gouv.fr/organizations/meteo-france/dataservices
- IGN : https://geoservices.ign.fr/
- INPN / OpenObs : https://openobs.mnhn.fr/
- Copernicus Climate Data Store : https://cds.climate.copernicus.eu/
- SoilGrids (privilégier accès fichier/WCS ; API REST signalée comme indisponible) : https://docs.isric.org/globaldata/soilgrids/
- Données géologiques : https://www.brgm.fr/

**Obligation :** revalider à la date d'intégration l'accès, les droits de réutilisation commerciale, l'obligation d'attribution, les limites d'API, la résolution et la fraîcheur de chaque fournisseur. Ne jamais coder de promesse de disponibilité sur ces seuls liens.
