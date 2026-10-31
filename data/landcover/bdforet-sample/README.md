# Extrait public IGN BD Forêt V2

Zone d'essai WGS84 longitude/latitude : `[5.55, 43.30, 5.57, 43.32]`, près
d'Aubagne. Ce périmètre public ne décrit aucune observation ou localisation
personnelle. Il est configuré ici, sans règle Provence dans le moteur.

Source : IGN, BD Forêt V2, couche WFS
`LANDCOVER.FORESTINVENTORY.V2:formation_vegetale`. Licence Ouverte 2.0 ;
URL de source, attribution, date de capture et empreintes dans `manifest.json`.
Le millésime précis n'est pas fourni par ce service : il reste inconnu.
La période de production du produit (2007–2018) ne date pas chaque objet.

`source.geojson.gz` conserve les octets GeoJSON de la réponse publique sous
compression gzip déterministe. Le manifeste vérifie séparément l'archive et
le contenu décompressé : 48 objets, 975 960 octets avant compression.
`normalized.geojson` est l'artefact obtenu sous le runtime Windows consigné
dans ses métadonnées : 45 objets découpés, huit catégories dont les landes,
aucune réparation de géométrie requise et 45 millésimes inconnus.

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
