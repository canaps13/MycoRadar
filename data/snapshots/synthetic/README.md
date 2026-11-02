# Fixture de snapshots entièrement inventée

Les régions, taxon, version de modèle et versions de source sont fictifs.
`payload.json` reste indisponible avec scores nuls. Ce n'est ni une observation,
ni un calcul scientifique, ni un résultat publiable.

`batch.json` décrit deux cibles. `delta.json` change seulement la version d'une
entrée de la cible nord ; le payload reste le même, sans recalcul biologique.
Le smoke vérifie que ce changement de dépendance est tracé et que la cible sud
est conservée, puis revient au premier snapshot. Aucune modification du fixture.

```powershell
$env:PYTHONPATH='api/src'
uv run --locked python scripts/check_snapshots.py --input data/snapshots/synthetic
```
