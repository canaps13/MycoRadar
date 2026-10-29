# MycoRadar — preview Cloudflare unique (main)

Une seule application Cloudflare Workers est prévue : `mycoradar-preview`.
Aucun Worker ni preview distinct ne doit être créé pour les pull requests.
La preview représente le **dernier commit validé et fusionné dans main**, et non le travail local ou une branche Codex non fusionnée.

## Configuration du Worker
- Repo GitHub : `canaps13/MycoRadar` ; branche déclenchante : **main uniquement**.
- Root directory Cloudflare Workers Builds : `web`.
- Build command : `npm ci && npm run build`.
- Deploy command : `npx --yes wrangler@4 deploy && node scripts/smoke-preview.mjs`.
- Wrangler config : `web/wrangler.toml` (nom imposé `mycoradar-preview`).
- Désactiver la construction des branches non-production / previews de PR.
- Sur chaque push main réussi : déployer dans le **même** Worker.
- Le contenu web est la sortie Vite `web/dist`, servie par un Worker minimal pour isoler `/api/*`.

## Limites actuelles
Cette étape ne déploie **que l'interface React statique**. L'API FastAPI et la base PostGIS ne tournent pas dans ce Worker. La route `/api/*` répond volontairement JSON 503 avec la raison `backend_not_deployed`, tant qu'une API FastAPI réelle et sécurisée n'est pas déployée. Ne pas maquiller cet état.

## Vérifications avant activation
1. Connecter la GitHub App Cloudflare au dépôt si elle ne l'est pas déjà.
2. Activer un token de build avec les seules permissions de déploiement requises.
3. Vérifier que le déclencheur a exactement `main` comme branche autorisée.
4. Lancer le premier build, consulter les logs et vérifier HTTP 200 + assets sur l'URL réelle du Worker.
5. Vérifier que les pushes sur une autre branche ne produisent aucun déploiement.

Cette configuration Git ne prouve pas à elle seule que Cloudflare est connecté ni que la publication a fonctionné.


## Déploiement initial et durcissement MR-042

Le premier build Workers Builds de `main` (commit `324831e`) a réussi le
29 octobre 2026 : Vite compilé, trois fichiers statiques uploadés, Worker
déployé. Ce succès ne prouvait pas à lui seul une vérification HTTP externe.

MR-042 ajoute `preview_urls = false` dans Wrangler ; la configuration
Workers Builds conserve `previews_enabled = false`. Le script de recette
`node scripts/smoke-preview.mjs` valide HTTP 200 pour l'accueil et ses assets,
et HTTP 503 JSON pour l'API absente. Pour activer cette vérification après
publication, configurer le *deploy command* de Workers Builds ainsi :
`npx --yes wrangler@4 deploy && node scripts/smoke-preview.mjs`.

La clé Cloudflare utilisée pour les builds porte actuellement le nom
`plume build token`. Elle doit être remplacée par un jeton MycoRadar dédié,
à privilèges minimaux, avant de révoquer quoi que ce soit côté Plume.
Les protections GitHub de `main` requièrent des droits d'administration
non disponibles avec la connexion GitHub actuelle.
