# ADR-010 — Objets immuables et tête de snapshot privée

Statut : tranche MR-021 en revue, sans publication de données scientifiques.

La file MR-020 coordonne les travaux mais ne publie pas un ensemble cohérent de
résultats par cible. Les lecteurs et modèles scientifiques ne sont pas encore
intégrés/admis. Le mécanisme peut néanmoins être éprouvé sur des artefacts
précalculés inventés, sans service distant ni activation cloud.

Décision : conserver des objets JSON et des descripteurs complets nommés par
SHA-256 dans un répertoire privé d'un seul hôte. Remplacer atomiquement une
tête après validation complète, sous verrou SQLite technique et précondition
sur la tête attendue. Le `run_id` est l'empreinte du descripteur ; les cibles
inchangées restent référencées. Une réexécution identique ne réécrit pas la tête.

Le verrou ne stocke pas les résultats et ne remplace pas PostGIS. Les imports
HTTP, l'inférence et les calculs scientifiques ne se font pas sous ce verrou.
Un objet orphelin après un crash est acceptable ; un pointeur vers un ensemble
incomplet ne l'est pas. Le retour arrière est une nouvelle bascule contrôlée,
sans suppression de l'historique ni écrasement d'objet.

Conséquences : bibliothèques standard/Pydantic existantes, API Docker légère,
test de concurrence entre deux processus avec réseau coupé. Aucun store S3/R2,
API publique, timer ou modèle n'est déployé. La durabilité matérielle,
l'exploitation multi-hôte, le calcul incrémental réel et l'admission de
publication restent distincts. Tous les reçus restent non publiables et sans
validation scientifique.

Voir [contrat, limites et preuves MR-021](../MR-021.md).
