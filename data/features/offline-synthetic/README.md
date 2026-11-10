# Jointure synthétique MR-014

Ce manifeste est entièrement inventé : cellule, polygones, valeurs, identifiants,
dates, empreinte de source et URL `example.invalid`. Il ne décrit ni station,
ni observation de champignon, ni zone écologique réelle. Les nombres n'ont pas
de signification scientifique. Les métadonnées de licence exercent le contrat ;
elles ne constituent pas une preuve de droits sur un fournisseur réel.

Le premier support couvre un quart de la cellule avec la valeur 2, le second
trois quarts avec la valeur 6. Le résultat surfacique attendu est 5. Une seconde
couche a une acquisition postérieure au cutoff ; elle est indisponible. Une
troisième a une valeur manquante sur trois quarts de la cellule ; sa moyenne
reste nulle au lieu de renormaliser sur le seul quart connu.

Le smoke exécute deux processus CLI et vérifie identité des octets et du mtime,
trois lignes, valeur 5, refus temporel et refus de couverture. Aucun appel aux
URL n'est nécessaire ou autorisé par cette recette.

```powershell
$env:PYTHONPATH='api/src'
uv run --locked python scripts/check_feature_job.py --manifest data/features/offline-synthetic/manifest.json
```
