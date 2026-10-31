# MVP MycoRadar — livraisons testables

## Portée du pilote
Provence (Bouches-du-Rhône, Var, Vaucluse) en configuration, et non en règle métier codée en dur. Quatre espèces restent des candidates : Lactarius sanguifluus, Boletus aereus, Boletus edulis, Cantharellus cibarius. Le choix de **la première espèce** dépend de l'audit MR-045, pas d'une préférence esthétique.

L'[audit initial MR-045](MR-045.md) ne permet pas d'admettre une espèce :
le reçu de vingt occurrences françaises ne mesure ni la couverture saisonnière
des départements pilotes ni l'effort, et toutes ses incertitudes géographiques
sont inconnues. Le pilote scientifique reste bloqué selon les conditions de
reprise documentées ; les territoires peuvent toujours être affichés sans score.

## Étapes de livraison
1. **A — Carte honnête :** vrai fond cartographique et crédits visibles, vraies limites de territoires et couverture, filtre espèce/date (désactivé/état vide si données absentes), un Worker Cloudflare unique alimenté uniquement par main. Ne jamais afficher de faux scores en production.
2. **B — Données contrôlées :** occurrences, météo et forêt de producteurs admis, dates distinctes d'observation/publication/ingestion, qualité et résolution connues ou « inconnues », preuve de licence, couverture et rafraîchissement.
3. **C — Baseline explicable :** habitat et fructification distincts, score en indice relatif et non en probabilité ; facteurs et raisons, donnée manquante => unavailable ; tests rétrospectifs indépendants et comparaison à une baseline météo/saisonnalité simple.
4. **D — Déploiement élargi :** ajouter les autres espèces/territoires seulement si la couverture et les tests sont suffisants ; documenter les cas de non-publication.

## Vérification à chaque étape
- Tests de rendu bureau/mobile, absence de données fictives non étiquetées, attribution lisible, états d'erreur explicites, performance et accessibilité.
- Cohérence de l'API : pagination / bbox bornées ; tests de provenance, fraîcheur, confidentialité et réponses d'échec ; aucun secret client.
- Réserver les coordonnées sensibles ; une présence est une observation et non une absence ailleurs.
- La taille graphique d'une cellule, la résolution effective des données/modèle et l'incertitude spatiale sont trois mesures indépendantes.
- Les jalons ne sont DONE que lorsque les liens de PR, runs CI, test HTTP et preuves scientifiques existent.
