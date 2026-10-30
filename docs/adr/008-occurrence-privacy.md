# ADR-008 — Frontière unique de publication des occurrences

Statut : proposé et implémenté par MR-048, validation CI en cours.

Avant MR-010, aucune chaîne commune ne séparait les candidats d'occurrences des
données publiables. Les licences seules ne suffisent pas à autoriser les lieux
ou les taxons ; les protections d'un fournisseur ne doivent pas être annulées.

Décision : politique opérateur explicite, revue et expirante, avec refus par
défaut. La décision conjugue source/version/licence, visibilité de localisation,
revue de la ligne et sensibilité par taxon/pays. Ne pas arrondir une position
privée pour la rendre publiable ; retenir les cas non autorisés ou incohérents.
Les coordonnées déjà généralisées restent identiques avec leur incertitude.

Une publication mémoire scellée est le seul argument des cinq sorties publiques.
Chaque sortie vérifie politique courante, intégrité et expiration. Aucun brut
persisté, aucun identifiant rejeté dans les logs ou sorties, diagnostics fixes.

Conséquences : les adaptateurs et caches futurs doivent intégrer cette frontière
et leurs propres tests. Le noyau ne remplace ni l'admission légale des lots, ni
la classification des taxons, ni le contrôle d'accès d'un carnet privé. Il ne
déploie ni API d'occurrences ni tuiles et n'ajoute pas de dépendance.
Voir le [contrat](../occurrence-privacy.md) et la [recette](../MR-048.md).
