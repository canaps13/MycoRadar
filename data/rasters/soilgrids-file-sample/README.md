# Repli fichier SoilGrids, contrôlé hors ligne

Source : ISRIC — World Soil Information, SoilGrids 2.0,
`phh2o_0-5cm_mean`, fichier `tileSG-008-047_2-2.tif` du serveur public WebDAV.
Poggio et al. (2021), SOIL 7, 217–240, https://doi.org/10.5194/soil-7-217-2021.
Licence [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), confirmée
sur la [fiche du produit](https://isric.org/explore/soilgrids).

`source.tif` conserve le fichier natif complet de 323 071 octets, sans conversion
ni rééchantillonnage : 600 colonnes × 268 lignes, entiers 16 bits, blocs de six
lignes, `NoData=-32768`. Le manifeste choisit seulement une fenêtre 8 × 8 à la
colonne 268 et ligne 119, toutes deux indexées à zéro. Elle contient 56 valeurs
et huit NoData déclarés. Aucune exclusion opérateur n'est nécessaire pour ce lot.
La conversion explicite pH × 0,1 est appliquée une seule fois. Le résultat reste
une prédiction moyenne 0–5 cm, sans quantiles d'incertitude ni mesure locale.

`checksum.sha256.txt` conserve les sommes de contrôle publiées dans le même
répertoire ISRIC ; celle du fichier téléchargé concorde. `source.vrt.gz`
conserve les octets de l'index mosaïque sous compression gzip `mtime=0`.
Cet index est une **métadonnée**, lue comme XML pour vérifier le rattachement de
la tuile et le calcul de fenêtre. Le job raster n'ouvre jamais ce VRT ; il lit
uniquement le GeoTIFF local autonome et conserve son rejet des VRT et du réseau.
Le serveur annonce REST suspendu ; aucun basculement ou polling automatique
n'est activé. Ce lot démontre une voie de repli en fichier.

Le [reçu de source](../../../docs/evidence/MR-013-file-sources.json) donne les
URL exactes, dates de capture, empreintes, en-têtes et transformations.
L'en-tête `Last-Modified` de 2020 date le fichier HTTP, sans établir l'année
d'acquisition, la publication scientifique ou la fin des données. Ces champs
restent inconnus, tout comme la résolution effective ; le pas nominal est 250 m.
Pas de position privée, compte, import massif ou ressource cloud.

Les métadonnées CRS restent explicites : le WKT natif conserve un datum nommé
`unknown`, sans autorité EPSG. L'index mosaïque omet des paramètres explicités
dans le WCS. Avec le moteur consigné, le CRS fichier est jugé équivalent à celui
du VRT, mais pas à celui du WCS. Aucun réétiquetage ni transformation entre ces
CRS n'est réalisé. Le rattachement par l'index et les affines numériquement égales
permet une comparaison par indices ; il ne valide pas indépendamment la
géolocalisation au sol et n'admet pas ce lot aux jointures scientifiques.

Dans cette fenêtre précise, les huit NoData natifs correspondent aux huit zéros
de la [capture WCS gelée](../soilgrids-sample/README.md), et les 56 autres entiers
sont identiques. Les résultats normalisés sont donc identiques, avec des raisons
de manque distinctes : NoData déclaré pour le fichier, exclusion opérateur pour
le WCS. Ce constat ne définit aucune règle universelle « zéro = NoData » et ne
réécrit pas les métadonnées absentes du WCS. Les captures ont des dates distinctes.

Rejeu sans réseau depuis la racine, dans un nouveau fichier de sortie :

```powershell
$env:PYTHONPATH = 'api/src'
uv run --locked --group geo python -m mycoradar.raster_job --manifest data/rasters/soilgrids-file-sample/manifest.json --output .tools/mr013-native-soil.json
```

`normalized.json` est le résultat Windows gelé, avec versions des moteurs et
empreinte du code. Un rejeu identique préserve la sortie existante ; un autre
contenu refuse de l'écraser. Une autre plateforme peut avoir un autre `job_id`.
L'artefact reste `partial`, sans couche publique, pH local validé ou score.
Voir les [preuves et limites de MR-013](../../../docs/MR-013.md).
