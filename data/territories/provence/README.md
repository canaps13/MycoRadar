# Configuration pilote et extrait administratif

`manifest.json` sélectionne les départements 13, 83 et 84 et des pas projetés
de 1 000 et 2 000 m. Le moteur ignore ces noms/codes et accepte d'autres territoires.

`ign-adminexpress-source.geojson` est la réponse UTF-8 du WFS IGN pour ces trois
départements. Source : IGN, ADMIN EXPRESS COG CARTO, couche
`ADMINEXPRESS-COG-CARTO.LATEST:departement`. Licence :
[Licence Ouverte 2.0](https://github.com/etalab/licence-ouverte/blob/master/LO.md).
[Notice producteur](https://www.data.gouv.fr/datasets/admin-express-admin-express-cog-admin-express-cog-carto-admin-express-cog-carto-pe-admin-express-cog-carto-plus-pe).

L'URL de requête exacte, la date de collecte, le crédit et l'empreinte sont dans
le manifeste. Aucune édition annuelle ou date de publication du lot n'est
déduite du nom `LATEST`. Le fichier brut est conservé sans simplification ni
réparation de polygone. Les résultats dérivés doivent citer IGN et indiquer
leurs traitements et la date source inconnue, avec le lien de source.

Ces limites administratives ne sont pas un masque de forêt ou de terre admis.
Les deux masques sont nulls. Aucun score, présence ou autorisation d'accès aux
lieux n'est fourni. Voir [le contrat du job](../../../docs/grid-job.md).
