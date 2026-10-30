# Admission privée/publique des occurrences

Le module `mycoradar.occurrence_privacy` est la frontière de prépublication
MR-048. Les futurs adaptateurs d'occurrences doivent l'appeler **après une
normalisation privée fidèle**, avant tout cache public, API, tuile ou export.
Le module ne collecte pas de données et n'installe aucune route HTTP.

## Politique revue, jamais déduite d'une ligne

`PrivacyPolicy` est une configuration opérateur immuable, distincte des données.
Elle exige une référence HTTPS de revue, un début et une expiration avec fuseau
pour être active. Le [profil livré](../data/privacy/deny-by-default.json) n'a ni
source ni taxon autorisé et ne peut rien publier. Aucun taxon réel n'est classé
par cette livraison ; aucune donnée réelle n'est ingérée.

- `sources` : ID, version exacte, licence, attribution, citation HTTPS publique,
  collecte, publication éventuellement inconnue, autorisation de diffusion
  **fausse par défaut**, seuil minimal d'incertitude éventuellement exigé.
- `taxa` : décision `public`, `sensitive` ou `unknown`, par identifiant taxonomique
  et code pays. Taxon/pays inconnu ou sensible => exclusion totale, même flouté.
- Les licences reconnues sont CC0 1.0, CC BY 4.0 et LO 2.0. Cela n'accorde aucun
  droit par soi-même : l'admission effective et sa preuve restent obligatoires
  selon [la politique des données](data-policy.md). Une autre licence/version
  exige une revue et une extension explicite, jamais une assimilation automatique.
- La licence de la ligne doit correspondre à celle du lot admis ; la version du
  lot doit correspondre exactement. Une licence non commerciale ou inconnue est
  refusée. La citation/revue ne peut transporter de query string, fragment ou
  identifiants de connexion.

La configuration est une entrée de confiance ; ne jamais la construire à partir
d'une requête client ou des affirmations d'une observation. L'adaptateur doit
établir les flags de diffusion depuis les droits et le contexte vérifiés, et
préserver tous les signaux de restriction du producteur. Ce module ne détermine
pas automatiquement une sensibilité réglementaire ou une appartenance géographique.

## Ligne normalisée interne

| Champs | Contrat |
|---|---|
| `record_id`, `source_id`, `source_version`, `record_license` | Identité privée d'entrée et lot ; seule une identité opaque est diffusée |
| `taxon_id`, `country_code` | Correspondance exacte avec la règle revue, pays configurable |
| `location_visibility` | `public` explicite ; absence => `unknown` donc retenue |
| `sensitivity` | `public` explicite et cohérent avec la règle ; sinon retenue |
| `reviewed_for_release` | Booléen strict, faux par défaut |
| `coordinate_crs` | `EPSG:4326` explicite, pas de reprojection implicite |
| `longitude`, `latitude` | Nombres finis dans les bornes ; coordonnées **publiables fournies**, jamais originales à reconstituer |
| `location_uncertainty_m` | Nombre strictement positif ou null explicite, jamais zéro ; aucune résolution déduite des décimales |
| `generalized` | Booléen strict explicite ; si vrai, incertitude connue obligatoire |
| `event_date` | Date calendaire explicite ou null ; pas de timestamp numérique converti implicitement |
| `informationWithheld`, `dataGeneralizations` | Signaux du producteur, traités en mémoire ; texte libre jamais exporté |

Un champ non pris en charge fait retenir la ligne entière. L'adaptateur doit
minimiser les champs personnels avant cette frontière, sans supprimer les flags
de protection. `informationWithheld` non vide retient la ligne par précaution.
`dataGeneralizations` non vide exige `generalized:true`. Le seuil opérateur
d'incertitude, s'il existe, doit être respecté ; les coordonnées et l'incertitude
ne sont jamais modifiées pour faire passer le filtre. Une incertitude inconnue
reste null lorsqu'une politique permet explicitement un point non généralisé.

Les définitions [Darwin Core](https://dwc.tdwg.org/terms/#dwc:coordinateUncertaintyInMeters)
distinguent l'incertitude en mètres (zéro invalide), la précision décimale et les
[généralisations](https://dwc.tdwg.org/terms/#dwc:dataGeneralizations). Les remarques
libres peuvent révéler l'original ; seul le flag de généralisation et la valeur
d'incertitude fournie accompagnent le point public. Aucun croisement ou recentrage.

## Une admission, cinq sorties contrôlées

`admit_occurrences(rows, policy)` termine le lot avant de produire une
`PublicPublication` mémoire. Budget de 10 000 lignes par lot, règles bornées.
Une identité contradictoire ou comportant une copie privée/invalide est retenue
entièrement, quel que soit l'ordre d'arrivée. Les doublons identiques sont réduits.
L'ordre public est stable et l'entrée n'est pas modifiée.

Les sorties de `occurrence_outputs` recontrôlent la politique, son expiration
et un sceau HMAC de contenu local au processus. Ni copie modifiée ni structure
brute ne peut être envoyée accidentellement par ces fonctions. La clé éphémère
n'est ni configurée, stockée, journalisée ni transmise. Ce mécanisme ne défend pas
contre du code Python malveillant exécuté dans le même processus.

| Sortie | Données et garde-fou |
|---|---|
| `api_payload` | Objet JSON public, sources utilisées avec licences/liens/dates, statut partial ou unavailable |
| `tile_geojson` | Entrée GeoJSON **pour un futur tiler**, uniquement points et propriétés admis ; pas de serveur PBF ajouté |
| `export_zip` | CSV et `metadata.json` ensemble, noms fixes, provenance conservée ; mêmes critères d'admission |
| `public_paths` | Chemins relatifs opaques sans coordonnées ni query ; gabarit des futurs consommateurs, aucune route installée |
| `audit_payload` et log du filtre | Comptages globaux et codes fixes ; aucun ID, nom, chemin, coordonnées ou texte d'entrée |

L'identité opaque dérive de source/version/ID original, pas des coordonnées.
Ce n'est pas une preuve d'anonymisation. La liaison privée de provenance reste
à conserver, si nécessaire, dans la zone protégée du futur adaptateur ; pas dans
les journaux ou exports publics. Les sources rejetées ne figurent pas dans les
métadonnées de sortie. Les comptages de motifs sont des événements de contrôle,
peuvent se recouvrir et ne représentent pas un nombre d'observations indépendantes.

## Cache, conservation et révocation

Les règles courantes doivent être fournies à chaque sortie/lecture de cache.
Un changement de contenu invalide la publication même si l'opérateur a oublié
de changer son libellé de version. L'expiration interdit la sortie des données ;
les seuls comptages d'audit peuvent encore être consultés. Aucun fallback vers
un ancien lot n'est permis quand les droits sont révoqués.

La capacité mémoire n'est pas un format de cache persistant et n'est pas
rejouable dans un autre processus. Toute réutilisation persistante devra refaire
l'admission avec les règles courantes ; MR-020 et les futurs services doivent
respecter ce contrat et ajouter leurs tests d'intégration. Ne pas exposer une
archive statique durable comme cache sans contrôle des droits à la lecture.
Les copies déjà diffusées exigent une procédure de retrait ; ce noyau ne peut
effacer une copie détenue par un tiers.

Le filtre n'écrit aucun fichier brut, checkpoint privé ou rejet. Les candidats
restent en mémoire pendant le lot ; la CLI ne sauvegarde aucun fichier et ne
contacte aucun service. Les fichiers d'entrée restent sous la responsabilité du
job privé : accès restreint, rétention minimale documentée selon le besoin et
purge contrôlée. Pas de durée légale ou de consentement supposé. Aucun fichier
d'entrée n'est supprimé automatiquement. Seuls les artefacts sortis avec succès
peuvent être proposés à la publication après les autres contrôles d'admission.

## CLI hors réseau

Depuis la racine, avec Python/uv et le `PYTHONPATH` du projet :

```powershell
$env:PYTHONPATH='api/src'
uv run --locked python scripts/filter_occurrences.py --policy .tools/private/policy.json --input .tools/private/normalized.ndjson --format api
```

Les chemins ci-dessus sont des emplacements opérateur à créer, pas des fichiers
réels fournis. Formats : `api`, `tiles`, `export` (ZIP binaire), `urls`, `audit`.
La sortie va sur stdout uniquement ; vérifier le code retour **avant** de la
stocker/diffuser. Erreur => code 2 et objet JSON minimal sans données d'entrée,
ni chemin ni traceback, même si une erreur arrive après des lignes valides.
Policy JSON limité à 1 Mio, ligne NDJSON à 64 Kio. Les données privées ne doivent
jamais être placées dans les arguments d'une commande ou une URL.

L'ingestion réelle MR-010, les endpoints d'occurrences et la génération PBF
restent à implémenter ; ils devront utiliser ces sorties contrôlées, jamais les
candidats bruts. Cette livraison ne prétend pas sécuriser automatiquement un
composant futur qui contournerait cette frontière.
