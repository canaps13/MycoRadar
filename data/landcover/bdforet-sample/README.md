# Extrait public IGN BD Forêt V2

Zone d'essai WGS84 longitude/latitude : `[5.55, 43.30, 5.57, 43.32]`, près
d'Aubagne. Ce périmètre public ne décrit aucune observation ou localisation
personnelle. Il est configuré ici, sans règle Provence dans le moteur.

Source : IGN, BD Forêt V2, couche WFS
`LANDCOVER.FORESTINVENTORY.V2:formation_vegetale`. Licence Ouverte 2.0 ;
URL de source, attribution, date de capture et empreintes dans `manifest.json`.
Le service ne fournit pas le millésime. Une comparaison indépendante rattache
les 48 objets au paquet départemental IGN d'édition `2014-04-01`, dont la
métadonnée de généalogie indique `PVA_2008,`. Le manifeste retient donc **2008**
comme année des photographies sources (`acquisition`), distincte de l'édition,
de la rédaction des métadonnées et de la capture WFS en 2026. La période globale
2007–2018 ne date pas chaque objet. Cette attribution est limitée à cet extrait
vérifié ; le moteur ne déduit aucune année d'un code départemental.

`source.geojson.gz` conserve les octets GeoJSON de la réponse publique sous
compression gzip déterministe. Le manifeste vérifie séparément l'archive et
le contenu décompressé : 48 objets, 975 960 octets avant compression.
`normalized.geojson` est l'artefact obtenu sous le runtime Windows consigné
dans ses métadonnées : 45 objets découpés, huit catégories dont les landes,
aucune réparation de géométrie requise et 45 années sources documentées (2008).

`department-metadata.xml` conserve les octets de la métadonnée IGN du paquet.
`reference-lambert93.geojson.gz` conserve uniquement les 48 objets correspondants
du Shapefile départemental, en coordonnées Lambert93 d'origine et avec les cinq
attributs d'origine. Extraction avec py7zr 1.1.4 et pyshp 3.1.6, tri par `ID`,
JSON UTF-8 à clés triées et séparateurs compacts, newline LF finale, puis gzip
`mtime=0`. Ni simplification ni arrondi. Aucun nouvel outil n'est ajouté à l'API.

Le [reçu de millésime](../../../docs/evidence/MR-012-vintage.json) donne l'URL
officielle, l'empreinte et les 50 495 458 octets du paquet, les empreintes des
membres, de la métadonnée et de l'extrait dérivé. Le paquet intégral (20 410
objets) et les PDF ne sont pas redistribués dans Git. Les données et métadonnées
IGN sont utilisées sous LO 2.0, d'après le catalogue actuel ; la notice historique
à droits réservés n'est citée que comme corroboration, jamais comme preuve unique.

Les tests rejouent sans réseau le rapprochement : mêmes 48 identifiants, cinq
attributs identiques et mêmes nombres de sommets. La distance de Hausdorff après
reprojection du WFS vers Lambert93 reste inférieure à 0,001 m. Cette tolérance
compare des sérialisations de coordonnées ; elle ne mesure aucune précision au
sol ni résolution effective. Rejouer :

```powershell
uv run --locked pytest api/tests/test_landcover_job.py -q
```

La réponse brute étant archivée, le traitement peut être rejoué **sans réseau**.
Depuis la racine, sous PowerShell :

```powershell
$env:PYTHONPATH = 'api/src'
uv run --locked --group geo python -m mycoradar.landcover_job --manifest data/landcover/bdforet-sample/manifest.json --output .tools/landcover-local.geojson
```

Un rejeu identique réutilise le fichier ; un contenu différent ne l'écrase pas.
Les versions des moteurs, la plateforme et le code participent au `job_id`.
Un résultat Linux peut donc avoir un identifiant différent de l'artefact Windows.
Voir le [contrat, les droits et les limites](../../../docs/MR-012.md).

Cet extrait cartographique ne prouve ni le couvert actuel, ni un habitat de
champignon, ni un droit d'accès. Il n'active pas le masque forestier MR-007
et n'alimente pas une route API.
