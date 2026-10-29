# Contrat de stockage géospatial — MR-006

Migration : `0001_postgis` → `0002_geospatial_foundation`. Aucun seed de pays,
grille, taxon, observation ou run. Le schéma est mondial ; aucune contrainte
ne réserve le produit à la France ou à la Provence.

## Tables et relations

| Table | Identité, relations et rôle |
|---|---|
| `countries` | Code de deux lettres majuscules, nom ; validation de l'appartenance à un référentiel pays à faire à l'import |
| `regions` | ID stable, pays, nom, fuseau, emprise MultiPolygon ; désactivée par défaut ; validité du nom de fuseau à contrôler par le futur service |
| `cells` | ID stable, système de grille versionné, pas nominal en mètres, fraction terrestre nullable, emprise MultiPolygon ; génération à MR-007 |
| `cell_regions` | Couple cellule/région unique, liens multiples pour frontières ; intersections réelles à valider en MR-007 |
| `taxa` | ID, nom scientifique, autorité facultative, clé GBIF positive/unique facultative, statut unresolved par défaut ; réconciliation taxonomique à venir |
| `data_providers` | ID, nom, URL du fournisseur, sans pays imposé |
| `source_datasets` | Produit lié au fournisseur, URL de notice, politique d'ingestion JSON objet |
| `source_versions` | Produit, version fournisseur, URL du lot, SHA-256, dates, licence/URL/crédit, CRS d'origine, résolution effective nullable, couverture, état de validation, métadonnées et transformations |
| `occurrences` | Taxon et version source obligatoires, ID du record source, Point, intervalle de date facultatif, date verbatim, incertitude nullable, vérification et visibilité |
| `prediction_runs` | ID, version du modèle, état, début/fin et cutoff nullable ; aucun score ni sortie scientifique créée |
| `prediction_run_inputs` | Couple run/version source unique pour retrouver les lots contributeurs |

Les clés étrangères refusent la suppression d'une source encore référencée.
Les uniques `(dataset_id, version, checksum_sha256)` et
`(source_version_id, source_record_id)` empêchent le rejeu identique d'un même
lot/record. Un contenu modifié sous la même version fournisseur peut être
représenté par une autre empreinte. Cela ne résout pas les doublons d'observations
entre versions/fournisseurs : cette décision revient à l'ingestion MR-010.

## Géométries et valeurs inconnues

- Canonique EPSG:4326, 2D, types contrôlés par contraintes, emprises bornées aux
  longitudes [-180, 180] et latitudes [-90, 90], non vides et valides.
  Le SRID absent/0 et un SRID différent sont rejetés. Il faut transformer un
  CRS **connu**, pas simplement renommer son SRID avec `ST_SetSRID`.
- `cells.resolution_m` décrit la grille de stockage, pas la taille graphique.
  `display_cell_size_m` sera porté par le rendu/contrat de carte à MR-007/MR-008,
  sans le déduire d'une résolution effective ou d'une incertitude d'observation.
  `source_versions.effective_resolution_m` et
  `occurrences.location_uncertainty_m` sont des mesures indépendantes, nullables.
- Normaliser un polygone en MultiPolygon explicitement lors de l'ingestion.
  Les découpages à l'antiméridien et la validité des intersections restent à
  MR-007 ; aucune correction silencieuse ni `ST_MakeValid` automatique.
- `location_uncertainty_m=NULL` signifie inconnue, jamais zéro implicite.
  `land_fraction=NULL` signifie non calculée. Les résolutions sont positives
  et finies ; l'incertitude est non négative et finie ; NaN/Infinity rejetés.
- `event_start`/`event_end` sont toutes deux absentes ou forment un intervalle
  inclusif ordonné. Une date exacte utilise deux dates égales ; une précision
  au mois/année utilise l'intervalle correspondant, avec valeur verbatim si connue.
  Ne pas inventer un premier jour pour le présenter comme la date observée.
- Dates de publication source et résolution effective peuvent être inconnues.
  `fetched_at` est obligatoire et doit être fourni par le collecteur, sans défaut
  qui inventerait une date de collecte. `data_cutoff` n'est pas la date du calcul.

Les versions commencent en `pending`, couverture `unavailable`. `validated`
exige une licence, son URL et un crédit non vides, mais ne vérifie pas leur
authenticité ni l'autorisation légale. Les adaptateurs devront appliquer la
revue des droits et conserver les données brutes immuables référencées par
l'URL/empreinte, le CRS, les unités, les transformations et indicateurs qualité
dans les métadonnées. Le schéma n'est pas un moteur de conformité.

Les runs sont queued/running/succeeded/failed ; les contraintes contrôlent
la cohérence des dates avec l'état. Un run réussi n'est pas une publication
atomique, une prévision validée ni une preuve de présence. Les tables de features,
scores, snapshots et leurs règles de publication appartiennent aux tâches suivantes.

## Confidentialité et index

Les occurrences commencent en `private`, vérification `unverified`. `restricted`
permet de distinguer une diffusion restreinte. Aucun endpoint ne les expose ici.
La colonne n'est pas une politique RLS : les futurs services devront imposer
authentification, autorisations et masquage avant toute diffusion publique.
Ne pas exporter les géométries privées/sensibles parce qu'une licence est ouverte.
La tâche MR-048 impose aussi le filtrage des données sensibles avant diffusion
ou mise en cache ; cette migration ne valide pas ce jalon.

Index GiST sur les géométries des régions, cellules et occurrences ; index
pays/région, cellule/région inverse, fournisseur/produit, version/run et
taxon/date. Les clés uniques fournissent aussi les index produit/version et
version/record. Pas de partitionnement ou affirmation de performance sans mesures.

[Exemples SQL en lecture seule](sql/MR-006-examples.sql) : sélection spatiale,
filtrage explicite de visibilité et chaîne de provenance. Les trois requêtes
sont exécutées dans les tests sur fixtures synthétiques ; elles ne publient
aucune observation réelle ni prédiction.

## Migration, validation et retour arrière

Le service Compose `migrate` applique `alembic upgrade head` avant l'API.
`/ready` compare à la tête Alembic, désormais `0002_geospatial_foundation`.
Une ancienne base restée à `0001_postgis` n'est donc pas ready avec ce code.
La migration est transactionnelle sous PostgreSQL et ne modifie aucune ancienne
table métier puisqu'il n'en existait pas. Aucun appel HTTP n'exécute de migration.

Les tests PostGIS exigent `MYCORADAR_TEST_DATABASE=1` et un nom commençant par
`mycoradar_test`. Ils incluent le downgrade des tables : ne pas les pointer
vers une base applicative. Les fixtures de données sont annulées par transaction.
La CI Compose utilise une base isolée et exécute ces tests sans les simuler.

Le downgrade `0002` → `0001` **supprime les 11 tables et leurs données**.
Ne pas l'exécuter sur une base utilisée sans sauvegarde vérifiée et approbation
spécifique. Le test de retour conserve PostGIS et une table témoin indépendante.
Pour retirer le code après usage réel, privilégier un revert en gardant le schéma,
puis préparer une migration corrective autorisée ; ne pas effacer les données
pour remettre un ancien binaire en service. L'ancien code peut refuser `/ready`
si sa révision attendue diffère : prévoir la coordination code/schéma.

Références techniques consultées :
[PostGIS, validation et contraintes géométriques](https://postgis.net/docs/postgis-en.html),
[Alembic, opérations SQL](https://alembic.sqlalchemy.org/en/latest/ops.html),
[Alembic, SQL hors ligne et transactions](https://alembic.sqlalchemy.org/en/latest/offline.html).
