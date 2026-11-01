# Plans MR-046 : aucun jeu scientifique gelé

- `pilot-plan.json` : brouillon opérateur vide. Espèce/territoire, preuves,
  taille des blocs, distances et seuils restent `null` ; aucune affectation
  réelle. Le contrôleur doit le bloquer. Ce fichier ne permet pas de publier
  un modèle ni de commencer une sélection de modèle.
- `synthetic.json` : quatre enregistrements entièrement inventés, métadonnées
  de dépendances et dates fictives, justificatifs factices. Les nombres
  (distances, effectifs, fraction de surface et gain) servent uniquement aux
  tests de code ; **ce ne sont pas des seuils recommandés pour MycoRadar**.
- `synthetic-leakage.json` : variante inventée avec groupe partagé entre
  développement et test, et feature acquise trop tard. Le contrôle doit échouer.

Aucune coordonnée, valeur cible, espèce ou occurrence réelle. Une empreinte
factice n'est pas une preuve scientifique. Le statut structurel du cas positif
reste accompagné de `publication_allowed:false`,
`model_training_authorized:false` et `scientific_validation:not_performed`.

```powershell
$env:PYTHONPATH='api/src'
uv run --locked python scripts/check_evaluation_protocol.py --input data/evaluation
uv run --locked python -m mycoradar.evaluation_protocol --manifest data/evaluation/pilot-plan.json
```

Le smoke réussit si les trois cas se comportent comme prévu. La seconde commande
retourne volontairement 2 et un reçu agrégé `blocked`. Les manifestes opérateur
réels restent privés, hors Git, par exemple sous `.tools/evaluation-private/`.
Un hash ou pseudonyme ne rend pas une localisation anonyme ; la publication
éventuelle d'un reçu doit encore être revue.
