# Entrée entièrement inventée pour le runner local

Aucune observation, prévision, localisation ou source biologique réelle.
`input/current.json` désigne par SHA-256 le JSON autonome sous `input/versions/`.
`runner.json` configure uniquement cet adaptateur de fichier local.

```powershell
$env:PYTHONPATH='api/src'
uv run --locked python scripts/check_queue_runner.py --config data/queue-runner/synthetic/runner.json
```

Le smoke lance deux processus CLI successifs et vérifie une seule ingestion
après redémarrage. Sa base et ses copies restent dans un répertoire temporaire
qui lui appartient. La CI monte cette entrée en lecture seule et coupe le réseau.
