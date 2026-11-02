# Fixture entièrement synthétique — aucune observation réelle

`month.json` invente des compteurs mensuels ; noms, identifiants et dates sont
fictifs. Aucun point, taxon réel ou preuve de couverture du pilote. L'URL du
manifeste décrit un contrat d'entrée et ne doit pas être appelée pour ce test.

La réponse contient quinze lignes indexées fictives, quatorze avec mois connu.
Le lecteur regroupe décembre/janvier/février en hiver, puis mars–mai,
juin–août et septembre–novembre. Les compteurs exacts restent dans ce fixture
de test ; le reçu ne publie que `0_indexed`, `1_to_4_withheld`, `5_or_more`.
La classe « au moins cinq » n'est pas un seuil de validation scientifique
ni une garantie d'anonymat. Le pilote demeure bloqué dans tous les cas.

Depuis la racine :

```powershell
$env:PYTHONPATH='api/src'
uv run --locked python -m mycoradar.coverage_audit --manifest data/coverage-audit/synthetic/manifest.json
```

Deux exécutions sur les mêmes entrées produisent `expected.json`, à l'ordre
JSON près. Aucune requête réseau n'est effectuée. La CI exécute ce fixture
dans l'image API construite avec `--network none` et montage en lecture seule.
