# Registre des fournisseurs de données

**Revue : 29 octobre 2026 — MR-005, complété par MR-007.** Ce registre documentaire couvre des
produits candidats France/monde, sans activer un fournisseur ni ingérer ses données.
La Provence ne détermine pas les droits des autres territoires. Une autorisation
sur un produit ne s'étend pas aux autres produits d'un même organisme.

`candidate` : une licence a été identifiée ; la version et le lot réels restent
à contrôler avant ingestion. `blocked` : un élément nécessaire manque ou se
contredit ; aucune ingestion, mise en cache de données ou publication autorisée
par le projet tant que ce point n'est pas résolu. Ces statuts concernent le
registre, pas la disponibilité des futures prédictions.

## Droits par produit

Dans la table, **conditionnel** signifie permis par la licence identifiée sous
réserve de ses obligations et de la revue du lot selon la
[procédure d'admission](data-policy.md). Le cache désigne une copie des fichiers
de données ; les conditions d'un service HTTP s'ajoutent à ces droits.
Toutes les sources liées ont été consultées le **2026-10-29**. Les métadonnées
sélectionnées de cinq catalogues sont conservées dans la
[preuve JSON](evidence/MR-005-catalogue.json), avec les URL API et l'heure UTC.

| ID stable / fournisseur / produit / couverture | Licence identifiée et preuve | Usage commercial | Cache de données | Redistribution | Attribution à compléter avec le lot | Décision |
|---|---|---|---|---|---|---|
| `gbif-occurrences` — GBIF / occurrences / monde | Selon le jeu : CC0, CC BY ou CC BY-NC ; [accord utilisateur](https://www.gbif.org/terms/data-user) et [politique de licences](https://www.gbif.org/terms) | Conditionnel, CC0 ou CC BY ; CC BY-NC exclu par politique MycoRadar | Conditionnel, par jeu | Conditionnel, conserver éditeur et droits de chaque enregistrement | Éditeurs, citations et DOI du téléchargement ; conserver les références des jeux contributeurs | `candidate`, sélection des jeux en MR-010 |
| `mf-climatology-hourly` — Météo-France / observations horaires contrôlées / métropole et outre-mer | [Catalogue du produit](https://www.data.gouv.fr/datasets/donnees-climatologiques-de-base-horaires), `lov2` : LO 2.0 | Conditionnel | Conditionnel | Conditionnel | Météo-France, produit, source et date de mise à jour du fichier | `candidate`, MR-011 |
| `mf-arome-001` — Météo-France / paquets AROME 0,01° / emprise EURW1S100 | [Catalogue du produit](https://www.data.gouv.fr/datasets/paquets-arome-resolution-0-01deg), `lov2` : LO 2.0 | Conditionnel | Conditionnel | Conditionnel | Météo-France, paquet, run émis, échéance, mise à jour et source | `candidate`, MR-011 |
| `ign-bdforet-v2` — IGN / BD Forêt V2 / France métropolitaine | [Catalogue IGN](https://www.data.gouv.fr/datasets/bd-foret-r), `lov2` : LO 2.0 | Conditionnel | Conditionnel pour fichiers | Conditionnel | IGN, BD Forêt V2, édition et millésime de l'emprise, date de mise à jour et source | `candidate`, MR-012 |
| `ign-rge-alti` — IGN / RGE ALTI / emprise à vérifier dans chaque livraison | [Catalogue RGE](https://www.data.gouv.fr/datasets/referentiel-a-grande-echelle-rge), `lov2` ; description incluant RGE ALTI sous Licence Ouverte | Conditionnel | Conditionnel pour fichiers | Conditionnel | IGN, RGE ALTI, livraison, emprise, date de mise à jour et source | `candidate`, MR-013 ; vérifier métadonnées du produit livré |
| `ign-adminexpress-cog-carto` — IGN / limites départementales / France | [Notice producteur](https://www.data.gouv.fr/datasets/admin-express-admin-express-cog-admin-express-cog-carto-admin-express-cog-carto-pe-admin-express-cog-carto-plus-pe), catalogue `5808de39c751df1e0679df72`, `lov2` : LO 2.0 | Conditionnel | Conditionnel | Conditionnel | IGN, ADMIN EXPRESS COG CARTO, URL du lot, date source inconnue et collecte distinctes, transformations | Extrait public des trois départements pilotes admis pour MR-007 ; [manifeste et empreinte](../data/territories/provence/manifest.json). Ce snapshot n'active pas un flux fournisseur. |
| `isric-soilgrids-2` — ISRIC / SoilGrids 2.0 / monde | [Documentation officielle](https://docs.isric.org/globaldata/soilgrids/) : CC BY 4.0 | Conditionnel | Conditionnel pour rasters | Conditionnel | ISRIC, couche/profondeur/statistique, version, licence, transformations et citation de la [FAQ officielle](https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_04.html) | `candidate`, MR-013 ; REST exclu pour l'instant |
| `brgm-charm50` — BRGM / BD Charm-50 / France métropolitaine | [Notice du BRGM](https://www.data.gouv.fr/datasets/cartes-geologiques-vectorisees-et-harmonisees-a-1-50-000-du-brgm) : API `license=notspecified` ; aucun droit déduit du caractère public du portail | Non établi | Non établi | Non établi | BRGM, carte/livraison, mise à jour ; texte de licence du lot à obtenir | `blocked`, R1 / MR-013 |
| `inpn-openobs` — INPN/SINP / observations publiques / France | [Portail OpenObs](https://openobs.mnhn.fr/) protégé lors de la consultation ; licence des lots non vérifiée | Non établi | Non établi | Non établi | Producteurs contributeurs et licence du lot à obtenir | `blocked`, R2 / MR-010 |
| `c3s-era5-land` — C3S/ECMWF / ERA5-Land horaire / monde | [Fiche CDS](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land?tab=overview) : libellé « CC-BY licence » ; texte complet/version et conditions de compte à confirmer | Non établi pour le lot | Non établi | Non établi | Citation CDS, DOI `10.24381/cds.e2161bac`, version et mention de traitement à confirmer | `blocked`, R3 / MR-011 |
| `osm-data` — contributeurs OpenStreetMap / base cartographique / monde | [Copyright OSM](https://www.openstreetmap.org/copyright) : ODbL ; lire le [texte juridique](https://opendatacommons.org/licenses/odbl/1-0/) avant choix d'une base dérivée | Conditionnel | Conditionnel pour un extrait obtenu légalement | Conditionnel ; obligations ODbL à étudier pour une base adaptée | © OpenStreetMap contributors, lien copyright/licence | `candidate`, R4 / MR-008 ; aucun serveur choisi |
| `osm-standard-tiles` — OSMF / tuiles raster standard / monde | Licence des données et [politique du service raster](https://operations.osmfoundation.org/policies/tiles/) distinctes | Service sans garantie de continuité | Cache HTTP requis ; en-têtes du serveur, ou minimum 7 jours s'ils ne sont pas interprétables | Pas d'archives de tuiles issues d'un téléchargement massif/hors ligne | Crédit OSM visible sur la carte | `blocked` pour préchargement/offline ; choix d'un service en MR-008 |

Les textes de référence sont la [LO 2.0 publiée par Etalab](https://github.com/etalab/licence-ouverte/blob/master/LO.md)
et [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). L'application des
droits de reproduction au cache de fichiers est notre interprétation de ces
licences ; elle ne constitue pas une permission de surcharger une API.
LO 2.0 impose source et date de mise à jour ; CC BY impose les crédits applicables,
le lien de licence et la mention des modifications. Ne pas suggérer une caution
officielle des fournisseurs.

## Accès, cadence et limites scientifiques

Les cadences **cibles MycoRadar** ci-dessous sont des règles de conception,
non des jobs déjà en service. Une vérification horaire des métadonnées ne
signifie ni nouvelle donnée chaque heure ni import complet. Les quotas non
vérifiés restent inconnus : aucun nombre n'est inventé et aucun compte n'a été créé.

| ID | Accès envisagé / contraintes à vérifier à l'intégration | Cadence fournisseur observée / fraîcheur | Cible MycoRadar | Résolution/couverture à conserver |
|---|---|---|---|---|
| `gbif-occurrences` | Recherche pour petits échantillons, téléchargement pour lots ; identifiants requis selon opération, secrets côté serveur ; quotas à relever | Variable selon éditeur, pas de cadence mondiale garantie | Vérifier métadonnées au plus une fois/heure, importer seulement changements | Incertitude des coordonnées par occurrence, date d'événement, taxonomie et biais ; présence déclarée ≠ absence ailleurs |
| `mf-climatology-hourly` | CSV compressés par territoire/période ; API éventuelle à auditer séparément, sans reprendre un quota d'un autre service | Fichiers des deux dernières années quotidiens, période courante plus ancienne mensuelle, anciennes décennies annuelles selon notice | Polling léger horaire, import des fichiers modifiés | Mesures aux stations, aucune grille uniforme implicite ; qualité, fuseau indiqué et période réels |
| `mf-arome-001` | GRIB2 et documentation des paquets ; limites de téléchargement, cycles disponibles et API à vérifier | Pas temporel 1 h ; catalogue `continuous`, ce qui ne donne pas la cadence exacte d'émission | Vérifier nouveaux runs chaque heure ; conserver heure d'émission et échéance | Grille 0,01° ≠ résolution effective garantie ; prévision ≠ observation ; emprise EURW1S100 |
| `ign-bdforet-v2` | Fichiers de livraison ; fiche produit désormais sur cartes.gouv.fr ; si API, [CGU Géoplateforme](https://cartes.gouv.fr/cgu/) en plus de la licence | Catalogue `irregular`, millésime local à lire | Import sur nouvelle édition, revue des métadonnées mensuelle | Formations cartographiées ≥ 5 000 m² selon notice ; ce seuil n'est pas une précision métrique |
| `ign-rge-alti` | Livraison dédiée RGE ALTI ; quotas des services IGN non vérifiés | Catalogue RGE `irregular` | Import sur nouvelle édition, revue mensuelle | CRS, taille de pixel, précision altimétrique, emprise et acquisition propres à la livraison |
| `ign-adminexpress-cog-carto` | WFS GetFeature borné à 3 départements ; couche et propriété `code_insee` vérifiées par DescribeFeatureType, [CGU Géoplateforme](https://cartes.gouv.fr/cgu/) | `LATEST` n'est pas une date d'édition ; publication du lot non établie | Snapshot gelé MR-007 ; revoir notice et version avant remplacement, aucun polling activé | MultiPolygon WGS84 longitude/latitude ; résolution effective inconnue ; limites administratives, pas masques de forêt/terre |
| `isric-soilgrids-2` | WCS/WebDAV documentés, à tester sur petit extrait ; documentation annonçant REST suspendu | Pas de calendrier ferme identifié | Import sur nouvelle édition, revue mensuelle | Pixels annoncés 250 m, profondeur/unité/quantiles ; prédictions de sol, pas analyses locales mesurées |
| `brgm-charm50` | Ne pas importer avant résolution de R1 ; accès InfoTerre à confirmer | Catalogue `punctual`, pas de fraîcheur opérationnelle prouvée | Sur édition après levée du blocage | Échelle 1:50 000 ≠ résolution 50 m ; géologie ≠ mesure directe de pH du sol |
| `inpn-openobs` | Aucun contournement de protection ; obtenir notice publique et conditions du lot | Inconnue | Après levée du blocage, vérification légère horaire selon quotas | Géoprécision, floutage, sensibilité, date et doublons GBIF à conserver |
| `c3s-era5-land` | Compte/acceptation des conditions et quotas CDS à confirmer avant requête de données | Fiche : données horaires, mise à jour quotidienne ; latence du lot non vérifiée | Après admission, vérifier métadonnées chaque heure, télécharger changements | Réanalyse ; natif annoncé 9 km, distribution 0,1° ; aucun remplacement implicite d'une prévision actuelle |
| `osm-data` | Extraits autorisés et conditions du diffuseur à choisir ; pas de moissonnage de l'API d'édition | Selon extrait choisi | Sur version d'extrait | Géométrie contributive ; accès aux lieux, droit de passage et forêt réelle non garantis |
| `osm-standard-tiles` | HTTPS, identification et Referer conformes ; pas de bulk/offline ; service best effort | Selon en-têtes HTTP, pas de SLA | Consultation interactive uniquement si retenu ; pas de polling scientifique | Image de fond, pas donnée écologique ; politique raster distincte du service vectoriel |

## Risques ouverts et décisions attendues

| Risque | Conséquence / mesure requise avant admission | Responsable de la suite |
|---|---|---|
| R1 — BRGM : licence non spécifiée dans la notice producteur | Une [notice tierce](https://www.data.gouv.fr/datasets/cartes-geologiques-departementales-a-1-50-000-bd-charm-50) publiée par Christian Quest affiche LO 2.0 ; cela ne suffit pas à autoriser le lot du producteur. Obtenir les conditions de la distribution BRGM exacte et consigner la résolution de l'écart. La page InfoTerre de conditions essayée n'a pas été lisible avec l'outil utilisé. | MR-013 |
| R2 — OpenObs : portail protégé et conditions non lues | Rester sur des données publiquement diffusables, vérifier licence, contributeurs et précision autorisée. Aucun accès à des observations sensibles n'est demandé dans MR-005. | MR-010 |
| R3 — CDS : libellé CC-BY sans texte/version lus | Lire les termes applicables au produit/lot, relever citation, compte, quotas et droits exacts ; ne pas extrapoler une licence Copernicus à tous les jeux CDS. | MR-011 |
| R4 — ODbL et service de tuiles | Étudier base dérivée/œuvre produite avant combinaison ; choisir un service compatible avec l'usage, les tests automatisés et la confidentialité. Ne pas financer implicitement un hébergeur ni activer un service tiers. | MR-008 |
| R5 — Attribution perdue dans agrégations/exports | Maintenir les liens de provenance, les licences et crédits de tous les lots contributeurs ; ne pas rebaptiser tout le résultat sous la licence du code. | MR-010 à MR-014, MR-018 |
| R6 — Sources vieillies, indisponibles ou spatialement grossières | Revoir conditions à chaque nouvelle version ; horodater les contrôles séparément des données ; signaler partial/unavailable/stale selon les faits, sans inventer une précision locale. | Adaptateurs et MR-020 à MR-023 |

Une source supplémentaire (autre pays, fond de carte, landcover global) exige
sa propre entrée et ses preuves. Aucune ligne n'autorise par défaut l'usage des
photos, des logos, des observations personnelles ou d'un autre produit du fournisseur.

## Lots cartographiques admis par MR-008

Revue des textes le **29 octobre 2026, vers 23:17 UTC**. Ces deux admissions
portent uniquement sur les extraits d'affichage décrits dans le
[manifeste versionné](../data/map-sources/manifest.json) et la [recette MR-008](MR-008.md).
Elles complètent les candidats de MR-005, sans les activer comme sources écologiques.

| ID / lot et couverture | Preuves consultées | Commercial / copie fichier / redistribution / dérivés | Attribution, accès et décision |
|---|---|---|---|
| `ign-adminexpress-display` — IGN ADMIN EXPRESS COG CARTO, WFS LATEST, 13/83/84, empreinte `f967afb56063…` | [Notice IGN publiée sur data.gouv.fr](https://www.data.gouv.fr/datasets/admin-express-admin-express-cog-admin-express-cog-carto-admin-express-cog-carto-pe-admin-express-cog-carto-plus-pe), licence LO 2.0 ; [texte Etalab](https://github.com/etalab/licence-ouverte/blob/master/LO.md) ; [CGU Géoplateforme](https://cartes.gouv.fr/cgu/), version du 15 octobre 2024 | Permis sous attribution et lien effectif à l'information source ; date d'édition inconnue explicitée, collecte distinguée. Copie et dérivé simplifié conservent leur provenance. | IGN, produit, URL du lot et licence affichés ; source publique sans identifiant ; aucun appel WFS client ni polling. Quota non établi, pas de requête supplémentaire nécessaire. `admitted` pour ce lot cartographique public uniquement. |
| `natural-earth-land-display` — Land 1:10 millions, commit `ca96624a56bd…`, contexte Europe occidentale | [Conditions du producteur](https://www.naturalearthdata.com/about/terms-of-use/) et [fichier du dépôt producteur épinglé](https://github.com/nvkelso/natural-earth-vector/blob/ca96624a56bd078437bca8184e78163e5039ad19/geojson/ne_10m_land.geojson) | Domaine public : usage commercial, copie, redistribution et transformations permis ; pas de garantie d'exactitude. Cache HTTP fournisseur sans objet pour le service client : fichier dérivé local. | Crédit volontaire Natural Earth et lien aux termes visibles. Une collecte du fichier public sans compte, pas de tuiles ni coût de service ; original de 10 Mo gardé hors Git, SHA-256 vérifié avant transformation. `admitted` comme fond de contexte uniquement. |

La mise à jour de la fiche IGN n'est pas attribuée à l'extrait WFS LATEST :
la date du lot reste inconnue. L'interprétation d'admission LO 2.0 repose sur
l'attribution effective et l'URL de l'information prévues par le texte, sans
inventer une édition. Les deux sources sont publiques et ne contiennent aucune
observation personnelle. OSM et ses services ne sont pas utilisés par MR-008 ;
le risque R4 reste à instruire si un service OSM est ultérieurement choisi.

### Lot API admis par MR-009

Revue le 30 octobre 2026 : [notice IGN](https://www.data.gouv.fr/datasets/admin-express-admin-express-cog-admin-express-cog-carto-admin-express-cog-carto-pe-admin-express-cog-carto-plus-pe)
et [Licence Ouverte 2.0](https://github.com/etalab/licence-ouverte/blob/master/LO.md).
`ign-adminexpress-display-20261029` est admis exclusivement pour les contours
administratifs publics 13/83/84, extrait WFS LATEST d'empreinte `f967afb56063…`.
Copie, usage commercial, redistribution et dérivé simplifié autorisés sous
attribution effective IGN et URL source ; cette attribution et le lien de licence
accompagnent les géométries via `/v1/metadata`. Date d'édition inconnue explicitée,
collecte datée du 29 octobre 2026, aucune fraîcheur déduite de la notice.
Le lot est réutilisé sans appel WFS ; quotas non établis, aucun polling activé.
Pas de donnée personnelle ni de masque forestier. [Manifeste et preuves](MR-009.md).
Cette admission ne concerne aucun autre produit IGN ni taxon/occurrence.

## Échantillon GBIF MR-010

Revue du **30 octobre 2026** : métadonnées du jeu ONF
[`017f23ba-bf04-4eb7-a076-04ab2e5de250`](https://api.gbif.org/v1/dataset/017f23ba-bf04-4eb7-a076-04ab2e5de250),
DOI [`10.15468/tgap4x`](https://doi.org/10.15468/tgap4x), publié par UAR PatriNat
(OFB-MNHN-CNRS-IRD), Paris. La licence du jeu et des vingt enregistrements lus
est CC BY 4.0 ; lien producteur `http://creativecommons.org/licenses/by/4.0/legalcode`,
[texte juridique Creative Commons consulté](https://creativecommons.org/licenses/by/4.0/legalcode.en).
Usage commercial, copie et dérivés sont permis sous les obligations d'attribution,
lien de licence et mention des modifications. Cette lecture de licence ne
vaut pas autorisation de diffusion d'une localisation ou d'un taxon sensible.

Décision `admitted-for-memory-audit-only` pour le petit échantillon documenté
dans le [reçu](evidence/MR-010-sample.json), collecté le 30 octobre 2026 à
18:33:47 UTC. Filtre France, *Boletus edulis*, deux pages de dix ; aucune portée
Provence ni représentativité écologique déduite. Les autres lots restent
`candidate`. Les bruts et leurs champs personnels ne sont pas sauvegardés ;
seuls métadonnées publiques, empreintes et comptages sont versionnés. Ni cache
durable de points, ni redistribution de points ou médias n'est admis par cette
revue. Les droits et conditions d'un futur lot devront être revérifiés.

La citation complète du producteur, la licence, son DOI, l'éditeur, les URL de
lecture et les transformations accompagnent le reçu. Les signalements du
producteur ne sont pas effacés : incertitude géographique absente sur vingt
lignes, dix-huit désaccords empreinte/coordonnées et vingt IDs taxonomiques
producteur non retrouvés. Publication du registre en 2022 et modification en
2023 restent distinctes de la date de collecte et des dates d'observation.

[L'API GBIF](https://techdocs.gbif.org/en/openapi/) impose un usage borné et peut
retourner 429 selon sa charge, sans débit garanti. Le job utilise un User-Agent
du projet, des délais/retries limités et n'appelle jamais les pages web pour
extraire des données. L'[accord GBIF](https://www.gbif.org/terms/data-user) était
lisible dans l'index du moteur de recherche ; ses ouvertures directes ont
renvoyé 403, ce qui est consigné sans prétendre avoir consulté ces réponses.
Le service public `api.gbif.org` et les termes Creative Commons étaient accessibles.

La diffusion reste refusée par MR-048, y compris pour cet échantillon sous
licence compatible. Les règles de sensibilité/localisation ne sont pas établies.
L'accès direct INPN/OpenObs reste `blocked` (R2) : ce lot accessible via GBIF
ne prouve pas les droits ni l'accessibilité d'un autre service.
