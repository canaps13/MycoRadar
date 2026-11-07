# Fixture MR-024 entièrement inventé

Les coordonnées, identifiants, dates, taxon et provenance sont fictifs.
Ils ne décrivent aucune occurrence réelle et ne sont pas affichés sur la carte.
Le SHA fournisseur `aaaa…` est une déclaration de test, pas une capture GBIF.

Sept lignes : deux copies identiques de `synthetic:a`, un `b` coïncident au même
jour/point, un `c` généralisé avec intervalle et précision inconnue, deux `d`
contradictoires, un `e` invalide à coordonnées incomplètes. Tous les lieux sont
privés, la sensibilité reste inconnue et la source n'autorise pas la publication.

Résultat attendu : trois représentantes pour l'audit, une copie identique,
trois lignes écartées par identité (deux contradictoires et une invalide),
une candidate de coïncidence à deux lignes, zéro ligne diffusée. Ces nombres
valident seulement le moteur technique ; aucun effort, biais ou gain de modèle
n'est mesuré par ce fixture. Voir le [contrat](../../../docs/MR-024.md).
