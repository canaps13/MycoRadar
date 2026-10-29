# Décision d'hébergement à préparer — API MycoRadar

Statut : **ADR ouverte, choix de fournisseur non effectué**. Ce document établit des critères d'acceptation, pas une autorisation de provisioning ni un devis.

## Composants et séparation
- **Un seul Worker public `mycoradar-preview`** pour React/Vite, déployé uniquement depuis `main`. Pas de Worker de PR.
- Le Worker ne peut pas exécuter tel quel le service FastAPI/PostGIS/les jobs Python lourds. Tant qu'aucun backend réel n'est déployé, `/api/*` retourne JSON 503, sans réponse SPA trompeuse.
- **API FastAPI** : service Python 3.12+ sur hôte conteneurisé/ASGI capable de garder des connexions réseau sécurisées vers la base ; limit/rate, authentification admin, validation bbox, CORS et tests de disponibilité.
- **PostGIS** : base managée compatible extension ou hôte isolé avec sauvegardes testées, migration contrôlée Alembic, compte SQL à privilèges minimaux et connexions TLS ; pas de base publique sans contrôle d'accès.
- **Imports/ML** : jobs batch séparés des requêtes HTTP et du Worker public ; coûts/quotas et idempotence.
- **R2 / stockage objet** : seulement si un produit volumineux le nécessite et si sa licence autorise le cache ; ne pas créer de stockage avant besoin mesuré.

## Critères de sélection
1. Évaluer l'hébergement avec trois scénarios : développement local sans dépenses cloud ; pilote hébergé à faible volume ; extension régionale. Chiffrer au minimum CPU, RAM, temps de calcul, requêtes, stockage, sauvegardes, trafic sortant et coûts incompressibles avec devis actualisé.
2. Comparer une API conteneur + base managée et une API + base autohébergées sur fiabilité, administration, sauvegarde, sécurité, migration, RGPD et capacité à traiter PostGIS.
3. Tester la chaîne de bout en bout sur données non sensibles : `/health`, `/ready`, requête de territoire bornée, état sans prédiction ; HTTPS, secret côté serveur, aucune clé fournisseur au navigateur.
4. Définir les invariants de mise en service : rollback, migrations avant déploiement, état `stale`, alertes, test restauration, logs non sensibles, plafonds de budget et circuit d'approbation.
5. En cas de fournisseur non retenu ou API absente, la preview demeure frontend-only et l'indisponibilité est affichée clairement.

## Décision
MR-043 **n'effectue aucun choix ni déploiement** de FastAPI ou PostGIS. Le choix final et son coût nécessitent la comparaison documentée et une autorisation de provisioning distincte.
