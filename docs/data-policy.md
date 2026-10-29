# Admission, provenance et attribution des données

Ce document prépare MR-010 à MR-014 et les futures API. **Aucun mécanisme
d'admission automatique ni endpoint d'attribution n'est implémenté par MR-005.**
Le [registre](data-providers.md) est la source documentaire des décisions sur les
produits ; les migrations métier restent à MR-006.

## Admission d'un produit puis d'un lot

1. Choisir l'entrée exacte du registre, sa couverture, son édition et son mode
   d'accès. Revoir les conditions lors de l'intégration et à chaque changement
   de version, de licence, d'usage ou de service ; une date de revue passée ne
   prouve pas les droits du prochain lot.
2. Consigner la notice produit et les termes effectivement lus : URL, version,
   date/heure UTC de consultation, conclusions distinctes pour commercial,
   cache de fichiers, cache HTTP, redistribution et produits dérivés. Identifier
   les quotas, restrictions et comptes nécessaires. Un résultat inconnu ou
   contradictoire reste bloquant pour l'opération concernée.
3. Vérifier le lot : licence et titulaire applicables, précision géographique
   autorisée, conditions d'export, données personnelles/sensibles, droits des
   médias. Conserver les preuves permises (métadonnées, référence du texte,
   empreinte et version), hors Git pour toute donnée privée ou tout secret.
4. Vérifier les métadonnées scientifiques, unités, CRS, emprise, valeurs manquantes,
   dates et incertitudes ; importer en zone de travail isolée. Ne pas confondre
   autorisation de réutilisation et validation de qualité. Les jobs seront
   idempotents, versionnés, incrémentaux et exécutés hors requêtes frontend.
5. Publier seulement après validation du lot et préparation de ses crédits.
   Documenter les transformations et la licence de sortie sans supprimer les
   obligations des entrées. Consigner la décision dans la PR de l'adaptateur avec
   tests et preuves d'exécution ; un catalogue accessible ne remplace pas ce contrôle.

Pour GBIF, MycoRadar retient **CC0 et CC BY uniquement** pour son usage cible
commercial possible ; CC BY-NC, licence inconnue ou incompatible sont exclues,
y compris des features/entraînements destinés à cet usage. Contrôler les licences
par jeu et enregistrement, pas uniquement le libellé global d'une archive.
Conserver les citations, identifiants des éditeurs, `datasetKey`, identifiant
d'occurrence et DOI réellement obtenu. Les médias demandent une revue séparée.
[Accord GBIF](https://www.gbif.org/terms/data-user),
[archives et fichiers de droits/citations](https://techdocs.gbif.org/en/data-use/download-formats).

## Informations à conserver

Ces noms sont un aide-mémoire pour les futurs contrats, pas un nouveau schéma SQL.
Ils complètent les entités `source_datasets` et `source_versions` prévues dans
[l'architecture](../ARCHITECTURE.md).

| Groupe | Informations requises |
|---|---|
| Produit | ID du registre, fournisseur, identifiant catalogue, URL de la notice, couverture pays/régions |
| Droits | Licence exacte et URL, version, titulaire, crédits, restrictions, preuves et date de revue, décision par usage |
| Lot | Identifiant/version fournisseur, URL réellement téléchargée, checksum de contenu, date de collecte `fetched_at`, date publiée `source_published_at`, date de mise à jour source si distincte |
| Mesure | Date/période d'observation, date d'émission d'une prévision, échéance, fuseau, CRS, unités, NoData, couverture et résolution effective justifiée ou inconnue |
| Traitements | Versions des jobs, paramètres, transformations, lots parents, contrôles qualité et statut de validation |
| Diffusion | Classification public/privé/sensible, précision publiable, texte et emplacement des crédits, licence/conditions des exports, résultats/runs dépendants |

Si une date, licence ou résolution manque, conserver l'inconnu et appliquer
la règle d'admission adaptée ; ne pas remplacer la date d'observation par la
date de téléchargement. La date d'une fiche catalogue n'est pas nécessairement
celle de tous ses fichiers. Les scores habitat/fructification resteront séparés ;
une grille fine affichée ne rend pas les données sources plus précises.

## Attribution par surface de diffusion

| Surface future | Contenu et emplacement attendus | Recette à prévoir |
|---|---|---|
| Carte interactive | Crédit du fond visible et lien licence ; provenance des couches et dates consultables dans les détails | Sur mobile et bureau, vérifier que contrôles/fiches ne masquent pas les crédits |
| API de données/prédictions | Références des lots réellement utilisés, fournisseur, licence/URL, crédits, dates et version dans les métadonnées liées au résultat | Aucun lot parent perdu dans une agrégation ou une pagination |
| Export | Fichier de métadonnées/crédits livré avec les données, licences d'entrée et conditions de redistribution | Export relu sans dépendre de l'interface web ; absence de données privées |
| Rapport ou image partagée | Source, licence, version/date et mention de transformation dans le document lui-même | Crédit préservé après export/capture |

Gabarit **à remplir lors d'une ingestion réelle**, jamais à afficher tel quel :

```text
Source : <fournisseur et contributeurs requis> — <produit>, <version/lot>.
Source mise à jour le <date déclarée par la source> ; collectée le <date UTC>.
Licence : <nom/version et URL>. Source/DOI : <référence réellement obtenue>.
Traitements MycoRadar : <transformations et version du job>.
```

Pour LO 2.0, mentionner la source et sa dernière mise à jour. Pour CC BY,
préserver les crédits requis et identifier les changements ; aucune approbation
du fournisseur ne doit être suggérée.
[LO 2.0](https://github.com/etalab/licence-ouverte/blob/master/LO.md),
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Pour SoilGrids, reprendre la référence correspondant à la propriété dans la
[FAQ ISRIC](https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_04.html).

## Confidentialité et correction d'une diffusion

Une licence ouverte ne supprime pas les droits des personnes ni les restrictions
de localisation. Les observations privées restent privées par défaut. Minimiser
les champs personnels importés, préserver le floutage fourni et ne pas reconstruire
une localisation sensible à partir de croisements. L'accès public à une observation
ne prouve ni le droit d'entrer sur un terrain ni la comestibilité d'un champignon.

Avant toute activation de tuiles/API côté navigateur, examiner les données
transmises au service (adresse IP, emprise, Referer). Ne pas transmettre un carnet
privé ou des coordonnées privées dans des URL, journaux publics ou requêtes
fournisseurs sans l'approbation spécifique requise par AGENTS.md. Les besoins
de consentement, conservation et accès seront traités avec les fonctions concernées.

Si des droits deviennent incertains : suspendre l'opération concernée et les
nouvelles publications dépendantes ; isoler le lot ; identifier caches, exports
et runs concernés grâce à la provenance. Conserver les preuves nécessaires avec
accès restreint, corriger les crédits ou retirer la diffusion si nécessaire,
puis recalculer à partir des seuls lots admis. Ne pas garder automatiquement
un ancien snapshot public dont les droits seraient eux-mêmes remis en cause.
Consigner incident, décision et vérification de correction dans une PR/runbook.
