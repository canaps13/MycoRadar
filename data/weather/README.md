# Lecture météo manuelle bornée

`sample-request.json` choisit une station publique Météo-France (Marignane,
`13054001`) et un point de référence public approximatif dans Marseille
(`43.3, 5.4`, WGS84). Ce point d'essai ne décrit aucun lieu de cueillette ni
la géolocalisation d'un utilisateur. Aucun emplacement privé ne doit être
substitué à cette configuration sans l'autorisation spécifique du projet.

Le fichier `latest-2025-2026` est un nom fournisseur, pas une preuve de fraîcheur.
La fenêtre observée et la date de mise à jour du catalogue sont figées dans la
requête ; revoir cette dernière avant une nouvelle lecture. Pour désactiver
la prévision, omettre `forecast` ; son statut devient explicitement indisponible.
Le fournisseur de prévision sélectionné est MET Norway, pas une prévision
Météo-France ou une observation de station.

Depuis la racine, après revue des [droits et limites](../../docs/MR-011.md) :

```sh
uv run --locked python -m mycoradar.weather_job --request data/weather/sample-request.json --cache-dir .tools/weather-cache
```

Le package est situé sous `api/src` : définir `PYTHONPATH=api/src` pour cette
commande locale (l'image API le définit déjà). Monter une requête opérateur
et un cache accessible à l'utilisateur non root pour l'exécution en conteneur.
Le cache doit rester commun aux relances et hors Git ; ne pas le vider pour
contourner `Expires`, une limitation ou un refus fournisseur. La CLI émet
uniquement provenance, compteurs et états, sans séries ou mesures ponctuelles.

Le [reçu réel](../../docs/evidence/MR-011-sample.json) documente une lecture
manuelle ; les tests automatiques utilisent exclusivement des données inventées.
