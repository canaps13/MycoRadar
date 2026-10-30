# ADR-007 — Grille égale-aire et artefacts hors requêtes HTTP

**MR-007, 29 octobre 2026.** Le pilote nécessite des identifiants de cellules
réutilisables, des surfaces cohérentes et un état honnête des masques manquants.
Le schéma MR-006 est livré séparément ; cette tranche ne dépend pas de sa fusion
et ne doit pas déclencher d'inférence ou de traitement lourd dans FastAPI.

**Décision :** moteur Python Shapely/pyproj dans un groupe `geo`, job CLI
indépendant, snapshot administratif réel en configuration, artefacts versionnés
et atomiques. La grille EPSG:6933 utilise une origine globale et des indices
entiers, sans identifiant administratif dans son `cell_id`. Les cellules sont
des supports complets ; les surfaces d'intersection régionale restent distinctes.
Les intersections de masques sont faites dans la projection égale-aire et non
en degrés, sous des budgets explicites avant allocation des candidats.

**Conséquences :** les pas projetés ne sont pas des distances au sol constantes.
Les régions polaires et polygones non coupés à l'antiméridien sont hors du
contrat v1. La taille de rendu, la résolution effective et l'incertitude d'une
observation ne sont pas déduites de cette grille. Sans couverture connue d'un
masque, la fraction reste null ; la forêt réelle sera admise dans MR-012.
Les opérations sont rejouables, mais un rejeu refait le calcul ; l'orchestration
incrémentale et la persistance SQL viendront dans les tranches de pipelines.

Le manifeste, le code, le runtime et les versions des moteurs déterminent
`job_id`. Une nouvelle sortie est nécessaire si ces inputs changent ; aucune
écriture frontend, API publique, migration ou ressource cloud ajoutée.
[Contrat détaillé](../grid-job.md), [preuves](../MR-007.md).
