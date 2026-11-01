# Échantillon de validation du lecteur GBIF

`sample-request.json` décrit une lecture manuelle de vingt lignes maximum,
sur le jeu ONF publié via GBIF. `FR` est le filtre pays ; le fichier ne sélectionne
ni une zone privée ni le pilote scientifique. Le nom *Boletus edulis* sert à
exercer un rapprochement exact dans la taxonomie historique GBIF, sans admission
de l'espèce dans le catalogue public.

Le [contrat et la revue](../../docs/MR-010.md) décrivent les droits et limites.
Le [reçu agrégé](../../docs/evidence/MR-010-sample.json) ne contient aucune
coordonnée, identité d'occurrence ou donnée de collecteur. Ne pas ajouter les
bruts dans ce dossier. La commande ne sauvegarde aucun enregistrement et ne
dispose pas d'option pour publier les points.
