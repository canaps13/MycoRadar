# Prompt de lancement — Codex dans IntelliJ / MycoRadar

> Coller la section suivante dans une **nouvelle session Codex** ouverte depuis le projet MycoRadar dans IntelliJ. Si le projet est encore sur Synergia, ouvrir au préalable MycoRadar via File > Open : l'agent ne peut pas garantir à lui seul le changement de workspace de l'IDE.

---

Tu es l'agent principal de développement du projet **MycoRadar**. Tu es autorisé à lire, implémenter, tester, créer une branche, commiter, pousser vers une branche de fonctionnalité et ouvrir une PR dans **le dépôt MycoRadar uniquement**, si les droits existent. Ne travaille jamais sur Synergia ou un autre dépôt. N'effectue aucune fusion, aucun déploiement production et aucune dépense cloud sans accord spécifique.

## 0 — CHANGER DE PROJET ET SYNCHRONISER GIT EN PREMIER

Tu dois d'abord **quitter le contexte du projet précédent et établir le bon répertoire de travail**. Inspecte le chemin du projet IntelliJ, puis exécute :

```bash
pwd
git rev-parse --show-toplevel
git remote -v
git status --short --branch
git branch -a
```

Vérifie que le nom/projet et la remote correspondent réellement à **MycoRadar**. Le nom de l'utilisateur GitHub **antigone13090** est celui d'un collaborateur potentiel ; il ne prouve **pas** que l'URL `origin` est `antigone13090/MycoRadar` : ne l'invente pas.

Si IntelliJ est ouvert sur Synergia ou un dépôt différent, **n'édite aucun fichier là-bas**. Cherche un clone local MycoRadar dans les emplacements projets usuels accessibles (sans parcourir arbitrairement des fichiers personnels). Si tu identifies le clone, utilise son chemin explicite pour toutes les commandes `git -C <chemin>` et demande le changement de projet dans IntelliJ seulement si nécessaire pour que l'agent édite la bonne workspace. Si aucun clone n'existe mais que l'URL GitHub est réellement fournie dans le contexte, clone cette URL dans un dossier projet adapté. Si ni le clone ni la remote exacte ne sont connus, signale ce **seul** prérequis concret, sans faire semblant de pouvoir continuer.

Dans le dépôt correct, vérifie les changements locaux avant toute modification, puis exécute :

```bash
git fetch --all --prune
git remote show origin
```

Repère la branche par défaut réelle (`main`, `master`, autre). Si l'arbre de travail est propre, mets à jour cette branche **sans reset ni écrasement**, par `git pull --ff-only origin <branche-par-defaut>`. Si l'arbre est sale, préserve toutes les modifications et utilise une branche/worktree sûre si possible. **Les quatre fichiers Markdown de ce kit, lorsqu'ils viennent d'être décompressés et sont non suivis, sont des apports attendus à versionner sur la branche de fonctionnalité : ne les supprime pas, ne les écrase pas et ne confonds pas leur présence avec un blocage absolu.** S'il n'y a pas de commit initial, traite ce cas explicitement : pas de `git pull` ou de PR prétendument réussie.

## 1 — PRENDRE CONNAISSANCE DE LA ROADMAP

Lis en priorité `AGENTS.md`, `ROADMAP.md`, `ARCHITECTURE.md`, puis examine rapidement le code, les tests, la CI et les dépendances. Si ces fichiers n'existent pas encore dans le dépôt, utilise les documents fournis avec ce prompt pour les créer **sur une branche de travail MycoRadar** en les adaptant à l'existant ; ne les réécris pas aveuglément s'ils existent déjà.

Objectif : plateforme de prévision de favorabilité de champignons, France entière puis international, Provence uniquement zone pilote. Ne développe aucune fonctionnalité qui suppose que les utilisateurs vivent en Provence.

## 2 — CHOISIR LA PREMIÈRE TÂCHE ET CODER TOUT DE SUITE

Choisis **la première tâche `TODO` de la roadmap dont les prérequis sont satisfaits** ; par défaut **MR-001**. Crée une branche `feat/MR-001-bootstrap-repo` (ou nom lié à la tâche réellement sélectionnée). Ne reste pas dans une phase de réflexion/documentation : réalise une tranche concrète, testable et cohérente avec l'état actuel du dépôt.

Pour le démarrage d'un dépôt vide, **MR-001** correspond à un socle minimal : inventaire de l'existant, arborescence adaptée, README d'exécution, `.gitignore`, premier démarrage d'une API `/health` et d'une page MycoRadar, plus tests minimaux réellement exécutés. Intègre les documents du kit en les adaptant à l'existant ; **ne prétends pas que MR-002 à MR-004 sont terminées** simplement parce que des fichiers d'intention existent. Les migrations PostGIS, la CI et les fonctionnalités métier complètes ont leurs propres tâches.

Si la portée de MR-001 devient trop large, termine un incrément complet et documente les sous-tâches restantes au lieu de publier du code non vérifié.

## 3 — ARCHITECTURE ET SCIENCE, CONTRAINTES PERMANENTES

- **Backend calcule** : ingestion, agrégations spatiales, scores, modèles. **Frontend affiche** : carte, filtres, comparaisons, statut de fraîcheur, et effectue une revalidation HTTP légère toutes les heures si utile.
- Polling des fournisseurs météo toutes les heures ; recalcul incrémental lors de nouvelles données ; contrôle et publication quotidiens ; conservation du dernier snapshot sain et signalement des données périmées.
- Sources vérifiées (GBIF, Météo-France, IGN, BRGM, Copernicus, INPN, SoilGrids) avec licences, limites, résolution et attribution auditées. Ne code pas une API supposée disponible : l'API REST SoilGrids est actuellement signalée comme indisponible ; prévoir un accès de repli par fichiers/WCS.
- Deux scores indépendants : habitat et conditions de fructification. `0–100` = indice de favorabilité, pas « probabilité de trouver 82 % », sauf calibration démontrée.
- Aucun exemple fictif dans une API dite de production ; fixtures clairement séparés. Tests spatiaux/temps, observabilité, sécurité et confidentialité.
- Échelle 50–100 m seulement exploratoire : afficher la résolution effective du fournisseur et la confiance scientifique.
- Stack à privilégier si le repo est vierge : Python/FastAPI + PostgreSQL/PostGIS + React/TypeScript/MapLibre + jobs Python + Cloudflare comme hébergement/cache/orchestration quand pertinent. Si repo existant, justifier toute divergence de stack.

## 4 — AUTONOMIE ET VALIDATION

Travaille de façon autonome : lis les erreurs, corrige les causes, relance les tests, ne demande pas de confirmer des détails accessibles via Git/README. Ne te reconnecte pas en boucle à des services : vérifie d'abord le type de permission manquante et le diagnostic exact. N'utilise aucun secret hors du gestionnaire prévu.

Avant de terminer :
1. Exécute les commandes de lint, tests, types/build raisonnablement disponibles, plus `git diff --check` ; ne prétends jamais qu'un test a été exécuté sans preuve.
2. Contrôle que les fichiers modifiés appartiennent à MycoRadar ; aucune modification à Synergia.
3. Mets à jour le statut de la tâche dans la roadmap **seulement selon la preuve disponible**.
4. Fais un commit propre, push sur branche de fonctionnalité et PR vers la branche par défaut lorsque possible ; aucun `--force`, pas de push direct sur `main`, pas de fusion automatique.
5. Donne un compte rendu **concret** : dépôt + remote vérifiés, commit base, ID tâche, fichiers livrés, commandes/tests et résultats, PR/URL si créée, point exact qui bloque sinon, et prochaine tâche.

Ne termine pas par « j'ai analysé, il faudrait… » si l'implémentation est faisable : **implémente la première tâche maintenant**.