# Garde-fous de validation scientifique — MycoRadar

**Document de conception, pas une validation acquise.** À réaliser avant MR-016/MR-017 et à appliquer lors de MR-024 à MR-029.

## Données et biais à auditer
1. Catalogue taxonomique : synonymes, identifications vérifiées, changements de taxon et droits/licences de chaque observation.
2. Coordonnées : pays, CRS, doublons spatiaux et temporels, arrondis et coordonnées floutées, valeur `coordinateUncertaintyInMeters` si présente, protection des espèces et lieux sensibles avant requête publique.
3. Couverture par espèce / région / mois / année : biais d'accès, proximité des routes, popularité des forêts, effort observateur. Les observations opportunistes **présence-seule** ne prouvent jamais une absence ailleurs.
4. Variables prédictives : heure réelle de disponibilité, taille de pixel, emprise, valeurs manquantes, transformations, provenance, licence ; rejeter toute variable publiée après la date de prédiction.

## Protocole préenregistré
- Séparer géographiquement les sites/secteurs (blocs spatiaux au-delà de l'autocorrélation observée) et chronologiquement les saisons/années. Les observations corrélées d'une même sortie ou cellule restent dans le même groupe.
- Geler le jeu de test avant ajustement et hyperparamétrage ; validation croisée spatiale **à l'intérieur** de l'entraînement ; test final temporel et/ou hors-zone tenu à l'écart.
- Les pseudo-absences / points de fond doivent reproduire l'effort d'échantillonnage admissible et être explicitement nommés ; jamais les présenter comme des « non-trouvailles » vérifiées.
- Baselines : saisonnalité seule, habitat forestier simple et indicateurs météo naïfs. Un modèle complexe n'est publié que s'il améliore les baselines sur le test indépendant sans augmenter indûment l'incertitude.
- Métriques adaptées aux présences opportunistes et au protocole : rappel/rang relatif et qualité par bloc, couverture, incertitude. Les métriques probabilistes (Brier, calibration, etc.) ne s'appliquent que si des cibles valides et un protocole d'observation permettent une probabilité correctement définie.
- Rapporter des résultats par **espèce, territoire, saison et horizon** (pas seulement une moyenne globale). Conserver les échecs et les zones non couvertes.

## Publication et représentation spatiale
Enregistrer `display_cell_size_m`, `effective_resolution_m`, `location_uncertainty_m` séparément ; `location_uncertainty_m` peut être inconnu et la résolution effective doit être justifiée. Ne jamais traduire une grille affichée de 50 m en précision de prédiction à 50 m.
Les sorties portent : `model_version`, `run_id`, `computed_at`, `data_cutoff`, `valid_at`, `coverage_status`, `confidence`, provenance et facteurs. Si couverture trop faible, retourner `unavailable` ou `partial`, pas un score.
L'indice 0–100 exprime une favorabilité **relative** ; aucun pourcentage de présence ni garantie de comestibilité/accès sans calibration indépendante et justification appropriée.

## Seuils de décision
Avant implémentation : figer les métriques, les seuils minimaux d'échantillons/blocs temporels et les critères de gain vs baseline dans une PR de protocole (MR-046). Si ces seuils ne peuvent pas être justifiés, garder `BLOCKED` pour la publication de scores. Une carte avec données réelles sans prédiction reste acceptable.
