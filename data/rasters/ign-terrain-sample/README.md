# Extrait numérique public RGE ALTI

IGN, RGE ALTI 2.0, couche `RGEALTI-MNT_PYR-ZIP_FXX_LAMB93_WMS`.
Licence [Ouverte 2.0](https://github.com/etalab/licence-ouverte/blob/master/LO.md).
URL source complète et attribution dans `manifest.json` ; collecte le
31 octobre 2026, date exacte de mise à jour des données inconnue.
Modifications : extrait WMS `normal` au format GeoTIFF, lecture de fenêtre
et normalisation hors ligne. Aucune caution du producteur n'est suggérée.

`source.tif` : 770 octets, 8 × 8 altitudes flottantes, NoData `-99999` déclaré,
64 valeurs lisibles. Le fichier garde son CRS incomplet : son nom EPSG:2154
ne prouve pas une équivalence à cette référence. Datum vertical non vérifié,
pas natif et rééchantillonnage serveur inconnus, pixel de sortie 1 m distinct
de la résolution effective inconnue. Âge et précision inconnus.

`normalized.json` est une sortie Windows gelée avec le moteur et ses empreintes.
Aucune couche scientifique ni aucun score admis à partir de cet extrait.
[Recette et preuves](../../../docs/MR-013.md#extension--relief-numérique-ign).
