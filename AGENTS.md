# AGENTS.md — MycoRadar (instructions persistantes pour Codex)

## Objectif
Construire une plateforme extensible France/Europe/monde de favorabilité et de fructification des champignons. La Provence est uniquement le **pilote**, jamais une contrainte métier ni une identité de marque.

## Source de vérité
- Lire `ROADMAP.md` pour choisir **la première tâche TODO dont les dépendances sont satisfaites**.
- Lire `ARCHITECTURE.md` pour les contrats des services, les décisions backend/cache et les garde-fous scientifiques.
- Examiner l'existant avant de choisir frameworks et arborescence ; conserver ce qui fonctionne et éviter les refontes inutiles.
- Lire `CONTRIBUTING.md` pour les conventions de branche/PR et leur contrôle automatisé ; utiliser `.github/pull_request_template.md`.
- Maintenir dans `ROADMAP.md` le statut et les preuves vérifiables des tâches livrées. Ne pas annoncer DONE tant que tests/critères ne sont pas observés.

## Non-négociable
- Ingestion traçable, licences/attributions et date des sources vérifiables ; pas de secrets dans Git.
- Un score 0–100 n'est pas une probabilité % par défaut ; ne jamais inventer de présence réelle, de résolution effective ou de fraîcheur.
- Habitat et fructification séparés ; si données manquantes, renvoyer un état `partial`/`unavailable` explicite.
- Backend responsable des calculs ; frontend ne fait que visualisation, filtres et revalidation légère.
- Calculs lourds hors requêtes frontend et hors Workers HTTP ; jobs idempotents, relançables, versionnés, incrémentaux.
- Localisations et observations privées jamais exposées par défaut ; pas d'affirmation sur comestibilité/accès non sourcée.
- Tests et preuves d'exécution requis, y compris CI ; ne pas inventer de chiffres de validation.

## Workflow d'une tâche
1. Confirmer le bon dépôt avec `git rev-parse --show-toplevel`, `git remote -v`, `git status --short --branch`; faire `git fetch --all --prune`.
2. Si travail local non commité, ne rien écraser : proposer branche/worktree isolé ou arrêter avec diagnostic précis.
3. Synchroniser la branche de base par `git pull --ff-only` si possible, puis branche `feat/MR-XXX-description`.
4. Implémenter une seule unité de travail de la roadmap avec tests, documentation et migration adaptée.
5. Exécuter localement ce qui est possible ; reporter exactement ce qui a réussi, échoué, et non exécuté ; `git diff --check`.
6. Commit/push sur branche de fonctionnalité et PR si la connexion GitHub le permet et que cela ne contourne pas de contrôle d'accès. Pas de force-push, pas d'écriture directe sur `main`, pas de fusion sans checks requis et politique explicite.
7. Ne modifier que MycoRadar. Synergia peut inspirer des pratiques, mais aucune dépendance/copie de code ni changement à Synergia sans autorisation.

## Escalade
- Si l'IDE est ouvert sur un autre dépôt, ne pas traiter ce dépôt. Se placer dans le vrai projet MycoRadar ou demander à l'utilisateur de l'ouvrir dans IntelliJ si l'agent ne peut pas changer de workspace.
- Ne jamais inventer remote, chemin local, autorisations, secrets ou accès. En cas de refus d'accès, expliquer le blocage exact après les tentatives non destructives utiles ; ne pas répéter indéfiniment l'authentification.
- Aucun déploiement production, dépense cloud, migration destructive ou transmission de données privées sans approbation spécifique.
