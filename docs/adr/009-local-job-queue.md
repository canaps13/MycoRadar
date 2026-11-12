# ADR-009 — File locale persistante, hors serveurs HTTP

Statut : implémentation MR-020 en revue ; aucune planification hébergée activée.

Les PR de lecteurs et de jointures sont indépendantes, non fusionnées. Le pilote
scientifique n'est pas admis et aucun budget/hébergement de scheduler n'est
autorisé. Le socle peut néanmoins vérifier cadence, concurrence et reprise
sans créer de ressource cloud ni déclencher d'import réel.

Décision : fournir `mycoradar.job_queue`, une bibliothèque SQLite standard,
versionnée, sur un seul hôte avec stockage local persistant. SQLite stocke
uniquement états de contrôle, identifiants et empreintes ; PostGIS conserve son
rôle de stockage métier. Il ne s'agit ni d'une base scientifique alternative,
ni d'une file distribuée entre machines.

Les transactions `BEGIN IMMEDIATE` sérialisent les acquisitions, avec attente
SQLite bornée à cinq secondes. Aucun appel fournisseur ou traitement métier
n'est fait dans ces transactions. Les baux, jetons d'acquittement, échéances,
budgets d'essais, cooldowns et clés de jobs survivent aux processus. La reprise
est au moins une fois : les adaptateurs doivent rendre leurs écritures
idempotentes avec `Job.id`. Un jeton de bail protège l'état de la file ; il
n'empêche pas une écriture externe tardive. L'ordre de publication atomique et
la protection contre les versions anciennes relèvent aussi de MR-021.

Conséquences : aucune dépendance, migration PostGIS, route FastAPI ou tâche
Worker ajoutée. Le Dockerfile copie déjà le module et ses dépendances standard.
La CI éprouve deux processus dans cette image, sans réseau. L'intégration des
adaptateurs, leur admission/quota et le déclencheur hébergé restent à livrer
avant une activation réelle. Une évolution vers une file hébergée devra
préserver clés, reprises et tests, avec ADR et autorisation d'infrastructure.

Voir [contrat et recette MR-020](../MR-020.md).
