# MR-015 — Catalogue interne de noms candidats

Compilation réelle de métadonnées taxonomiques et de faits bibliographiques,
sans occurrences, localisations ou scores. Les huit JSON sous `taxonomy/` sont
des réponses GBIF capturées le 1er novembre 2026. Leurs URL, dates UTC et SHA-256
sont dans `catalog.json` ; les tests ne les rafraîchissent jamais.

Attribution : GBIF Secretariat (2023), **GBIF Backbone Taxonomy**,
[10.15468/39omei](https://doi.org/10.15468/39omei), consulté le 1er novembre 2026 ;
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Réponses conservées
telles que lues ; sélection de quatre noms et compilation par MycoRadar.
Le registre déclare publication le 28 août 2023 et modification le 17 novembre
2023 : la collecte de 2026 ne les remplace pas. Les clés ne sont pas des IDs COL XR.

Les articles cités ne sont pas copiés : ni corps, image, séquence, localisation
ou tableau expérimental. La licence de texte connue ou inconnue est conservée,
sans admission pour entraînement. Les hôtes sont ceux rapportés dans les études,
sans réattribution des spécimens anciens ni liste exhaustive. Les seuils pH et
altitude restent `null` ; tous les calculs et toutes les admissions sont désactivés.

```powershell
$env:PYTHONPATH='api/src'
uv run --locked python scripts/check_species_catalog.py --manifest data/species/catalog.json
```

[Contrat, sources et limites](../../docs/MR-015.md). Les fixtures inventées de
tests unitaires restent dans `api/tests/test_species_ecology.py`.
