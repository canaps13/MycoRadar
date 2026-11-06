# MR-023 — Exercice de reprise PostGIS

## Portée

`scripts/check_postgis_recovery.py` teste une sauvegarde logique puis sa
restauration sur des données **entièrement synthétiques**. Il ne sauvegarde pas
la base applicative existante. Le catalogue public conserve son
[outil de reprise distinct](MR-023.md) : il n'est pas reconstruit depuis PostGIS.

Le script exige `MYCORADAR_TEST_DATABASE=1`, un hôte de connexion local et une
base de contrôle nommée `mycoradar_test…`. Il crée trois bases avec un identifiant
aléatoire propre à l'exécution. Seules les créations effectivement réussies sont
nettoyées ; un nom existant n'est jamais repris ni supprimé. Aucun `--clean`,
`--create`, `DROP … FORCE`, arrêt de connexion ou écrasement d'une base existante.
La base de contrôle sert uniquement à ouvrir la session d'administration.

Le rôle doit pouvoir créer et supprimer ces bases jetables et installer PostGIS.
Ces privilèges sont ceux du rôle de développement Compose ; cette procédure ne
définit pas les privilèges d'un futur service de production.

## Contrôles réalisés

1. Créer la source depuis `template0`, appliquer les vraies migrations Alembic
   et insérer le fixture dans les onze tables métier : géométries, relations,
   provenance, run sans score et deux occurrences privées/restreintes.
2. Exécuter `pg_dump --format=custom --no-owner --no-privileges` dans le
   conteneur PostGIS existant, vers un fichier temporaire privé côté client.
   L'archive est bornée à 64 Mio pour cet exercice et son SHA-256 est conservé
   en mémoire séparément. Aucune archive ni ligne de données n'est téléversée.
3. Ajouter une corruption au fichier de test. La divergence de SHA doit être
   détectée avant `pg_restore` ; la cible doit rester vide.
4. Restaurer les octets vérifiés dans la cible neuve avec `--single-transaction`
   et `--exit-on-error`, sans filtrer les tables. Comparer toutes les lignes des
   tables métier et d'Alembic, les définitions d'index et de contraintes.
5. Vérifier la révision attendue, PostGIS, les valeurs inconnues, la visibilité
   privée par défaut et le statut non vérifié. Tenter de violer un SRID, une clé
   étrangère et une visibilité : les contraintes restaurées doivent les refuser.
6. Dans la troisième base, créer une table `occurrences` témoin avant la reprise.
   Exiger l'erreur PostgreSQL précise de relation déjà existante, puis vérifier
   que seule la table témoin et sa ligne subsistent, sans extension PostGIS ni
   objets partiellement restaurés. Une erreur d'authentification ou de transport
   ne compte pas comme preuve de rollback.
7. Revérifier la source inchangée et supprimer uniquement les trois bases créées
   par cette exécution. Un échec de nettoyage empêche toute déclaration de succès.

Les commandes passent leurs arguments sans shell. Les sorties des outils et
les erreurs SQL restent capturées ; le stdout final ne contient que des codes
fixes, des booléens et le `run_id`. Les messages de pg_dump/pg_restore sur stderr,
même avec code 0, font échouer l'exercice. Les logs Alembic normaux sont capturés
séparément pendant la migration. L'échec inattendu est résumé `drill_failed`,
sans mot de passe, chaîne de connexion, archive, coordonnées ou chemin privé.

Les clients PostgreSQL sont ceux de l'image PostGIS épinglée dans Compose, sur
son socket Unix local. Une configuration refusant ce mode échoue ; aucun repli
vers un hôte distant ou une authentification affaiblie n'est effectué.
Le Python de l'API n'embarque aucun binaire PostgreSQL supplémentaire.

Les choix suivent les documentations PostgreSQL 18 de
[pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html) et de
[pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html), consultées le
6 novembre 2026 : archive logique d'une base, restauration transactionnelle,
propriété et privilèges traités séparément. Une restauration exécute du code SQL ;
ce test ne restaure que son archive fabriquée pendant la même exécution.

## Exécution locale isolée

Depuis la racine du worktree de cette PR, dans une **nouvelle session PowerShell**
avec Docker Desktop fonctionnel. Le projet Compose et le port ci-dessous doivent
être libres ; ne pas remplacer ceux d'une instance existante.

```powershell
$env:COMPOSE_PROJECT_NAME = 'mycoradar-recovery-drill'
$env:PGHOST = '127.0.0.1'
$env:PGPORT = '55433'
$env:PGDATABASE = 'mycoradar_test_recovery_control'
$env:PGUSER = 'mycoradar'
$env:PGPASSWORD = 'mycoradar-local-only'
$env:MYCORADAR_TEST_DATABASE = '1'
$env:PYTHONPATH = 'api/src'
docker compose --env-file .env.example up -d --wait db
uv run --locked python scripts/check_postgis_recovery.py
```

Contrôler le code de sortie : `0` seulement si tous les contrôles et le nettoyage
ont réussi. Le `run_id` permet de retrouver les noms
`mycoradar_test_recovery_<run_id>_{source,restored,rejected}` si une interruption
brutale a empêché le nettoyage. Dans ce cas, examiner les bases et leurs connexions
avant toute suppression manuelle ; le script ne force jamais leur fermeture.
Ne pas relancer en prétendant que l'exercice interrompu a réussi.

Arrêter ensuite le conteneur de ce projet sans effacer son volume :

```powershell
docker compose --env-file .env.example stop db
```

Validation locale de l'extension : 392 tests Python dont 23 nouveaux garde-fous
réussis, 51 PostGIS désélectionnés ; Ruff lint/format, mypy sur 22 sources et
`git diff --check` réussis. Docker Desktop est indisponible (pipe LinuxEngine
absent) : le dump et la restauration réels de cette révision restent à observer
en CI. Les runs verts antérieurs ne prouvent que la reprise du catalogue.

La CI Compose exécute le même script après les migrations et les tests PostGIS,
sur son propre cluster jetable. Son résultat est explicitement présent dans le
résumé, y compris s'il a échoué ou n'a pas été exécuté. Les tests unitaires des
garde-fous ne remplacent pas cette exécution réelle.

## Limites et future exploitation

Ce test ne couvre ni les rôles globaux, ni les droits de production (ils sont
délibérément omis de la restauration), ni les tablespaces, ni la réplication,
ni une reprise temporelle par WAL. Il ne définit pas de rétention, chiffrement,
stockage hors machine, RPO ou RTO. Aucun objectif de production n'est démontré.
Un snapshot logique de test ne remplace pas une stratégie de sauvegarde complète.

Pour une future sauvegarde réelle, approuver séparément le périmètre, les droits,
le stockage privé, le secret de vérification et la restauration sur un hôte
isolé compatible. Ne jamais pointer cet exercice synthétique vers une base
utilisée, ni réutiliser son rôle administrateur comme rôle de l'API.
Le SHA détecte une modification, sans authentifier un fournisseur ou admettre
un modèle scientifique. Les données réelles restent soumises à la confidentialité.

MR-023 reste IN_PROGRESS pour ces décisions d'exploitation et les métriques des
jobs. Retour arrière : retirer le script, ses tests et son étape CI ; aucune
migration ou modification de l'image HTTP n'est nécessaire.
