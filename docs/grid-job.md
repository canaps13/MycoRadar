# Grille et masques — job backend MR-007

Le job Python construit un support géographique, sans inférence ni score. Il
lit des polygones publics versionnés et écrit un artefact GeoJSON. Il n'est
importé ni appelé par les routes HTTP FastAPI ou le frontend. Aucune écriture
PostGIS n'est effectuée ; la persistance pourra utiliser le schéma MR-006.

## Exécution depuis la racine

```sh
uv run --locked --no-dev --group geo python -m api.src.mycoradar.grid_job --manifest data/territories/provence/manifest.json --output .tools/grid-pilot.geojson
```

Le groupe `geo` contient Shapely, pyproj et NumPy. `dev` l'inclut pour exécuter
les tests en CI ; l'image API construite avec `--no-dev` ne l'installe pas.
La machine exécutant le job doit conserver le réseau PROJ désactivé
(`PROJ_NETWORK=OFF`). Une transformation indisponible ou nécessitant une grille
manquante échoue ; aucun téléchargement caché ni transformation « ballpark ».

Rejouer vers le même fichier accepte seulement un résultat identique et ne le
réécrit pas. Pour un nouvel input ou moteur, choisir une nouvelle sortie.
La publication utilise un fichier temporaire synchronisé puis un lien dur
atomique, sur le même système de fichiers. Si les liens durs ne sont pas
disponibles, le job échoue au lieu de publier un fichier partiel. Aucun écrasement.
Le calcul est refait lors d'une relance ; la détection incrémentale des éditions
et l'orchestration de lots seront traitées dans les tâches de pipelines.

## Identité et géométrie

- Grille mondiale **EPSG:6933**, égale-aire, origine projetée `(0,0)`, ID
  `epsg6933-v1:<pas_m>:<colonne>:<ligne>`. Les indices sont des planchers signés,
  indépendants du territoire et des masques. Changer ces conventions exige une
  nouvelle version de grille.
- Le pas est une distance **dans la projection**, pas une longueur au sol
  uniforme. Les résolutions multiples entières d'un même pas partagent leurs
  limites ; des pas arbitraires ne forment pas nécessairement une hiérarchie.
- L'emprise complète de la cellule reste canonique. `region_area_m2` est son
  intersection avec le territoire. Une cellule frontalière a le même `cell_id`
  dans plusieurs territoires ; les Features représentent les **associations**
  cellule/territoire et utilisent un ID composé distinct.
- Sortie en MultiPolygon EPSG:4326, ordre longitude/latitude ; surfaces et
  intersections calculées en EPSG:6933. Les cellules en bord de domaine sont
  tronquées au domaine mondial, et leur surface réelle est enregistrée.
- Domaine v1 : latitudes -86° à 86°. Les polygones traversant l'antiméridien
  doivent être explicitement coupés en composants ; un composant de largeur
  supérieure à 180° est rejeté. Les régions polaires demandent une autre version
  de grille. Le moteur ne contient aucune condition de pays.
- `resolution_m` est le pas nominal de stockage. `display_cell_size_m`,
  `effective_resolution_m` et `location_uncertainty_m` restent nulls ici. Ce
  support géographique n'établit aucune résolution effective de prédiction.
  Les pas inférieurs à 250 m demandent le flag expérimental explicite.

## Masques et couverture

Un masque contient deux références : `positive` (polygones de terre/forêt) et
`coverage` (zone où la présence **et l'absence** sont connues). Un masque absent
ne vaut jamais une géométrie vide. Une FeatureCollection positive vide avec une
couverture connue peut représenter zéro ; un simple extrait d'occurrences ne
peut pas devenir une couverture d'absences.

| État | Résultat |
|---|---|
| Couverture terrestre complète, aucune terre | Cellule marine exclue |
| Terre/forêt manquante ou hors couverture | Fraction null, `unavailable` |
| Couverture recouvrant seulement une partie de cellule | Fraction null, `partial` |
| Terre et forêt complètement couvertes | Fractions calculées sur la surface complète de cellule ; forêt intersectée avec terre |

Une forêt connue mais sans masque terrestre suffisant ne produit pas une
fraction fiable. Les polygones positifs hors de leur couverture sont rejetés.
Les trous, îles, limites partagées et surfaces partielles sont conservés.
Le seuil numérique d'intersection est `1e-6 m²`, sans lien avec la précision source.

## Contrat des entrées et traçabilité

Le manifeste déclare territoires, fuseaux, résolutions, limites de travail,
sources et sélecteurs de propriétés. Chaque fichier a une empreinte SHA-256,
un CRS identifié 2D et une provenance publique (fournisseur, URL, licence,
crédit, version, collecte et publication connue ou explicitement inconnue).
Le CRS du manifeste doit correspondre au membre `crs` historique s'il existe.
Sans ce membre, seul l'ordre WGS84 standard est accepté. Un conteneur GeoJSON
projeté local exige donc la déclaration historique explicite du CRS.

Les licences actuellement acceptées sont LO 2.0, CC0 1.0 et CC BY 4.0.
Ce contrôle syntaxique ne remplace pas l'audit produit/lot du
[registre](data-providers.md) et de la [procédure d'admission](data-policy.md).
Un nouveau régime de licence exige une revue avant extension de cette liste.
Les inputs privés sont refusés ; cela ne constitue pas un contrôle de sensibilité
automatique ni une réalisation de MR-048. N'y introduire aucune observation privée.

L'artefact inclut le manifeste validé, toutes les références de sources, les
versions GEOS/PROJ/Shapely/pyproj, le runtime et l'empreinte des deux modules.
`job_id` est l'empreinte de ces inputs et paramètres. Il change avec un nouveau
lot/moteur ; le `cell_id` garde l'identité de la même emprise de grille.
La reproductibilité binaire est testée **dans un même environnement**, sans
promesse d'octets identiques entre versions de bibliothèques ou systèmes.

Les limites sont vérifiées avant la boucle de cellules : au plus 100 000
candidats configurables, budget global partagé entre territoires et résolutions,
20 Mo par couche, 200 000 sommets bruts par couche et 250 000 pour une opération
de densification. Les chemins restent dans le dossier du manifeste. Les
géométries invalides, non finies, vides hors masque positif, ou 3D sont rejetées,
sans réparation automatique. Les segments sont densifiés avant reprojection
(pas maximal source 1 km en projeté, 0,01° en géographique) ; ce paramètre
numérique n'est pas une résolution effective annoncée.

## Configuration pilote

[Le manifeste](../data/territories/provence/manifest.json) contient Bouches-du-Rhône,
Var et Vaucluse, pas une région dessinée approximativement. Les contours sont
un extrait public IGN ADMIN EXPRESS COG CARTO gelé et contrôlé par empreinte.
La date d'édition de `LATEST` n'a pas été fournie : elle reste inconnue ; la
collecte ne la remplace pas. Les crédits et l'URL source sont conservés.

Les masques réels terre/forêt restent absents, donc `unavailable`. Leur admission
et l'ingestion forestière relèvent de MR-012. Les tests de masquage utilisent
des polygones **synthétiques explicitement étiquetés**. Aucun de ces tests ne
prouve une couverture forestière réelle du pilote.

Domaine EPSG:6933 vérifié avec `pyproj.CRS.from_epsg(6933).area_of_use` dans
la base PROJ installée. Références consultées :
[transformations pyproj](https://pyproj4.github.io/pyproj/stable/api/transformer.html),
[transformations Shapely](https://shapely.readthedocs.io/en/stable/reference/shapely.transform.html),
[groupes uv](https://docs.astral.sh/uv/concepts/projects/dependencies/).
