# Contribuer à MycoRadar

`AGENTS.md` définit les règles persistantes. `ROADMAP.md` fixe l'ordre des tâches
et `ARCHITECTURE.md` contient les décisions et contrats. Les instructions de
l'utilisateur dans la session restent prioritaires ; ne pas déduire une
autorisation de fusion ou de déploiement du présent guide.

## Une tâche, une branche, une PR

1. Vérifier racine Git, remote et état local ; récupérer les modifications avec
   `git fetch --all --prune`. Préserver tout travail local non commité.
2. Synchroniser `main` par `git pull --ff-only origin main`, puis choisir la
   première tâche `TODO` dont les dépendances sont satisfaites.
3. Créer `feat/MR-XXX-description`, avec une description en minuscules et tirets.
   Exemple : `feat/MR-002-project-conventions`. Utiliser aussi cette convention
   pour une correction rattachée à une tâche de la roadmap.
4. Réaliser une seule unité vérifiable : code ou documentation selon la tâche,
   tests adaptés, migration uniquement si nécessaire, preuves dans le dépôt.
5. Commiter avec l'identifiant de tâche, par exemple
   `docs(MR-002): document contribution rules`. Les commits restent descriptifs ;
   aucun hook local obligatoire ni format de commit imposé par la CI.
6. Pousser la branche et créer une PR vers `main`, titre
   `MR-XXX : description`. Ne pas inclure plusieurs tâches dans une seule PR.

## Description et recette d'une PR

Le [modèle de PR](.github/pull_request_template.md) contient trois rubriques
obligatoires : `Objectif`, `Validation`, `Risques et retour arrière`.
Remplacer les commentaires d'aide par des informations propres à la modification.

- **Objectif** : problème concret, résultat attendu, tâche et périmètre. Ajouter
  les captures si l'interface change et une ADR si une décision durable change.
- **Validation** : commandes réellement exécutées et résultats observés, liens
  vers CI et preuves. Distinguer explicitement réussi, échoué et non exécuté.
  Pour une commande non exécutée, expliquer la raison. Ne pas copier les chiffres
  d'une ancienne PR comme s'ils validaient la nouvelle modification.
- **Risques et retour arrière** : limites, données ou migrations affectées,
  procédure de retour. Si rien ne nécessite de migration, l'indiquer simplement.

Les commandes applicables au code sont dans le [README](README.md#valider).
Une modification purement documentaire ne justifie pas à elle seule de nouveaux
tests applicatifs ; vérifier ses liens, exemples et cohérence avec l'existant.
Le workflow Bootstrap actuel continue à tester le socle sur les PR.

Pour des données ou scores, documenter les sources, licences, dates, résolution
effective et couverture ; séparer habitat et fructification et expliciter les
valeurs absentes. Les fixtures doivent être identifiées comme synthétiques.
Ne pas publier de données privées ou de secrets dans une PR ou ses captures.

Pour intégrer un fournisseur : appliquer la
[procédure d'admission et d'attribution](docs/data-policy.md) et mettre à jour
son entrée dans le [registre des produits](docs/data-providers.md). Vérifier
les conditions du lot réel, pas seulement celles du portail. Une licence ou un
droit d'usage inconnu/contradictoire bloque l'opération concernée ; les sources
marquées `blocked` ne doivent pas être activées sans preuve levant ce blocage.

## Contrôle automatique des conventions

`PR conventions` vérifie les métadonnées à l'ouverture, la réouverture, la sortie
du brouillon, au push et à la modification du titre ou du corps de la PR :

- branche `feat/MR-XXX-description`, titre `MR-XXX : description`, même ID ;
- cible `main`, ID présent dans la table de la roadmap ;
- statut de cette tâche `IN_PROGRESS` ou `DONE` ;
- trois rubriques obligatoires renseignées, au-delà des commentaires HTML.

Le contrôle lit le JSON GitHub depuis `GITHUB_EVENT_PATH` ; titre et corps ne
sont jamais interpolés dans une commande shell. Il n'utilise ni secret ni droit
d'écriture. Il vérifie la structure, pas la véracité scientifique des preuves,
l'absence de modification cachée d'une autre tâche ou la qualité d'une revue.
Les protections GitHub restent indépendantes : ce workflow ne les configure pas.

Pour reproduire le contrôle avec le JSON d'un événement PR enregistré localement :

```sh
uv run --locked python scripts/check_pr.py --event-file chemin/vers/event.json
```

Le JSON doit contenir `pull_request.title`, `pull_request.head.ref`,
`pull_request.base.ref` et `pull_request.body`. Les tests du contrôle font partie
de `uv run --locked pytest`. Ils utilisent uniquement des événements synthétiques.

## Statuts et fusion

`TODO` : pas commencée. `IN_PROGRESS` : travail ou validation en cours.
`BLOCKED` : obstacle concret documenté. `DONE` : critères réellement observés,
avec preuve de test/commande, commit, PR ou exécution CI. `DONE` ne veut pas dire
que la PR est déjà fusionnée. Une CI rouge ou non exécutée ne devient pas verte
par une déclaration dans la description.

Avant toute fusion : vérifier le dernier SHA de la PR, tous les contrôles et les
revues exigés par GitHub, puis vérifier que l'autorisation explicite de fusion
donnée par l'utilisateur couvre cette opération. Respecter sa portée et les
autorisations déjà données dans la session sans les redemander. Ne pas contourner un contrôle ni utiliser une fusion
administrateur pour le forcer. Après fusion, synchroniser `main` sans reset puis
créer la branche de la tâche suivante. Pas de force-push ni d'écriture directe
sur `main`. Un déploiement ou une dépense reste soumis à une autorisation distincte.
