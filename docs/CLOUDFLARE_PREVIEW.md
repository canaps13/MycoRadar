# MycoRadar — preview Cloudflare unique (main)

Une seule application Cloudflare Workers est prévue : `mycoradar-preview`.
Aucun Worker ni preview distinct ne doit être créé pour les pull requests.
La preview représente le **dernier commit validé et fusionné dans main**, et non le travail local ou une branche Codex non fusionnée.

## Configuration du Worker
- Repo GitHub : `canaps13/MycoRadar` ; branche déclenchante : **main uniquement**.
- Root directory Cloudflare Workers Builds : `web`.
- Build command : `npm ci && npm run build`.
- Deploy command : `npx --yes wrangler@4 deploy`.
- Wrangler config : `web/wrangler.toml` (nom imposé `mycoradar-preview`).
- Désactiver la construction des branches non-production / previews de PR.
- Sur chaque push main réussi : déployer dans le **même** Worker.
- Le contenu web est exclusivement la sortie Vite `web/dist`.

## Limites actuelles
Cette étape ne déploie **que l'interface React statique**. L'API FastAPI et la base PostGIS ne tournent pas dans ce Worker. Le contrôle `/api/health` peut donc indiquer indisponible tant que l'API publique/proxy approprié n'est pas configuré. Ne pas maquiller cet état.

## Vérifications avant activation
1. Connecter la GitHub App Cloudflare au dépôt si elle ne l'est pas déjà.
2. Activer un token de build avec les seules permissions de déploiement requises.
3. Vérifier que le déclencheur a exactement `main` comme branche autorisée.
4. Lancer le premier build, consulter les logs et vérifier HTTP 200 + assets sur l'URL réelle du Worker.
5. Vérifier que les pushes sur une autre branche ne produisent aucun déploiement.

Cette configuration Git ne prouve pas à elle seule que Cloudflare est connecté ni que la publication a fonctionné.
