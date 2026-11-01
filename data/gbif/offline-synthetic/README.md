# Fixture de rejeu GBIF entièrement inventée

Ces fichiers ne proviennent pas d'une collecte GBIF. Nom scientifique,
identifiants, dates, coordonnées, personnes et localités sont inventés pour
tester le transport hors ligne. Les déclarations de licence simulent les
métadonnées d'un fournisseur ; elles ne constituent pas l'admission d'un lot réel.
Les marqueurs `PRIVATE_*` servent à détecter une divulgation accidentelle.

`snapshot.json` décrit cinq réponses JSON ordonnées avec leur SHA-256 :
rapprochement taxonomique, métadonnées initiales, deux pages et métadonnées finales.
Les URL décrivent la requête attendue et ne sont jamais appelées pendant le rejeu.
Ne pas traiter les identifiants factices comme un jeu GBIF réel.

```powershell
$env:PYTHONPATH='api/src'
uv run --locked python -m mycoradar.gbif_job --snapshot data/gbif/offline-synthetic/snapshot.json
```

Résultat attendu : trois lignes traitées, zéro point diffusé, `partial`,
`capture_kind=synthetic`, capture fictive du 4 janvier 2026 conservée.
Ce fixture n'alimente ni carte ni score et n'atteste aucune présence réelle.
Pour de vrais snapshots : stockage privé hors Git, revue préalable des droits
de copie et des restrictions de localisation ; voir [MR-010](../../../docs/MR-010.md).
