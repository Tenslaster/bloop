# BLOOP — Robot de vision pour fantômes Highrise

> Manuel complet d'exploitation, de développement, de configuration, de diagnostic et de publication pour le projet BLOOP de détection de fantômes et d'effets dans Highrise.
>
> Ce document est volontairement plus long qu'un fichier README habituel, car il comprend une référence détaillée de la configuration, un index des symboles du code source, des guides de dépannage, des scénarios d'exploitation et un catalogue de validation. Commencez par **Démarrage rapide**, **Architecture d'exécution** et **Dépannage**.

## Table des matières

- [État du projet et du dépôt](#état-du-projet-et-du-dépôt)
- [Ce que fait BLOOP](#ce-que-fait-bloop)
- [Limites importantes et sécurité](#limites-importantes-et-sécurité)
- [Structure du projet](#structure-du-projet)
- [Prérequis](#prérequis)
- [Démarrage rapide](#démarrage-rapide)
- [Liste de vérification du premier lancement](#liste-de-vérification-du-premier-lancement)
- [Utilisation de l'interface graphique](#utilisation-de-linterface-graphique)
- [Interface en ligne de commande](#interface-en-ligne-de-commande)
- [Architecture d'exécution](#architecture-dexécution)
- [Détection de fenêtre et capture](#détection-de-fenêtre-et-capture)
- [Détection et appariement d'images](#détection-et-appariement-dimages)
- [Images cibles et images de surveillance](#images-cibles-et-images-de-surveillance)
- [Exploration et rétroaction](#exploration-et-rétroaction)
- [Sécurité des clics](#sécurité-des-clics)
- [Optimisation des performances](#optimisation-des-performances)
- [Guide de configuration](#guide-de-configuration)
- [Journaux et diagnostics](#journaux-et-diagnostics)
- [Importateur de dépôt](#importateur-de-dépôt)
- [Modules facultatifs d'apprentissage intelligent et de rapports](#modules-facultatifs-dapprentissage-intelligent-et-de-rapports)
- [Empaquetage de l'exécutable client](#empaquetage-de-lexécutable-client)
- [Tests et assurance qualité](#tests-et-assurance-qualité)
- [Sécurité et confidentialité](#sécurité-et-confidentialité)
- [Dépannage](#dépannage)
- [Guides opérationnels](#guides-opérationnels)
- [Flux de travail du développeur](#flux-de-travail-du-développeur)
- [Référence exhaustive de la configuration](#référence-exhaustive-de-la-configuration)
- [Index des symboles du code source](#index-des-symboles-du-code-source)
- [Atlas de dépannage : du symptôme observable à la correction fondée sur les preuves](#atlas-de-dépannage--du-symptôme-observable-à-la-correction-fondée-sur-les-preuves)
- [Catalogue de validation et conception des tests](#catalogue-de-validation-et-conception-des-tests)
- [Liste de vérification fichier par fichier](#liste-de-vérification-fichier-par-fichier)
- [Glossaire](#glossaire)
- [FAQ](#faq)
- [Liste de vérification de publication](#liste-de-vérification-de-publication)

---

## État du projet et du dépôt

BLOOP est un projet d'automatisation par vision par ordinateur, conçu principalement pour Windows, qui sert à reconnaître les sprites de fantômes et d'effets dans le client Highrise. À l'exécution, il capture une fenêtre de jeu, propose des régions susceptibles de contenir une cible, les vérifie à l'aide des gabarits disponibles, applique des contrôles de sécurité, envoie au besoin des entrées de souris et consigne des éléments de preuve pour les décisions ultérieures.

Lien du dépôt : <https://github.com/Tenslaster/bloop>.

**Note d'inspection du dépôt (2026-10-11) :** la vue publique de la racine sur GitHub montrait des fichiers d'images et un README, mais pas le code d'exécution Python, l'interface graphique, le fichier de dépendances ni les scripts de compilation de l'exécutable dans la liste visible des fichiers de la racine. Ce manuel documente aussi les modules sources fournis avec ce travail. Un clone neuf ne peut pas exécuter l'application complète à moins que le code source et les fichiers de données requis soient versés dans ce dépôt ou distribués séparément. Vérifiez la branche et l'arborescence actuelles du dépôt avant de publier ce README comme une promesse d'obtenir une copie exécutable.

### Portée et règle de la source de vérité

Ce manuel prend comme référence le dernier instantané de source intégrée fourni pour cette tâche : l'instantané du moteur (`main(9).py`, normalisé ici sous le nom `main.py`) branche `SmartGhost` et `WebhookReporter` lorsqu'ils sont disponibles, branche `PopupDismisser` de façon conditionnelle et expose l'interface en ligne de commande d'apprentissage supervisé. L'instantané correspondant de l'interface graphique (`gui(1).py`, normalisé ici sous le nom `gui.py`) comprend les pages d'apprentissage, de gestion des échantillons, des fenêtres contextuelles et des webhooks. Ces noms numérotés sont des noms de téléversement, et non des noms de fichiers recommandés pour le projet. Placez les fichiers sources correspondants côte à côte sous les noms canoniques indiqués dans la structure avant d'utiliser les commandes. Les instantanés antérieurs ou réduits du moteur dans le même projet peuvent ne pas offrir ces capacités; un fichier complémentaire n'est actif que si le point d'entrée en cours d'exécution l'importe, le construit et l'appelle.

Le comportement d'une version donnée est déterminé par sa révision du code source, son schéma de configuration, ses fichiers de données et sa recette de compilation. Si l'implémentation et ce README divergent, inspectez l'implémentation et mettez la documentation à jour avant la livraison.

Pour les sections détaillées sur les commandes et la configuration ci-dessous, l'implémentation de référence est le plus récent instantané de source intégrée fourni pour cette tâche. Il est normalisé sous les noms de fichiers conventionnels `main.py` et `gui.py` aux fins de la documentation. La liste publique sur GitHub ne contenait que des ressources (images) au moment de l'inspection : versez les modules Python correspondants, le manifeste des modèles et des dépendances ainsi que les fichiers de compilation si vous voulez qu'un clone neuf soit exécutable.

### Politique de compatibilité

- Les exemples reposent sur l'ensemble de sources inspecté le 2026-10-11.
- Confirmez les options de ligne de commande à l'aide du `main.py` réel et du binaire compilé réel.
- Un EXE existant n'est pas mis à jour lorsqu'on modifie un fichier `.py` voisin.
- Conservez une copie versionnée des valeurs par défaut de la configuration pour chaque version.
- Testez les dépendances facultatives lorsqu'elles sont présentes et lorsqu'elles sont absentes.
- N'affirmez pas qu'un exécutable a réussi les tests sous Windows s'il n'a pas réellement été exécuté sous Windows.

## Ce que fait BLOOP

Selon les modules branchés dans l'environnement d'exécution choisi, BLOOP peut :

1. repérer une fenêtre Highrise candidate et calculer son rectangle;
2. capturer la zone client ou une région configurée;
3. préparer des représentations redimensionnées des trames et des masques;
4. proposer des régions visuelles susceptibles de contenir un fantôme ou un effet;
5. comparer ces candidats à des gabarits d'images aux échelles prises en charge;
6. fusionner les détections qui se chevauchent et limiter le nombre d'instances;
7. bloquer les actions dangereuses au moyen de délais de récupération, de budgets, de zones d'exclusion, de surveillances de fenêtres contextuelles et de vérifications de fenêtre;
8. s'exécuter en mode simulation (dry-run) ou envoyer des entrées de souris et de clavier;
9. mettre en file d'attente les vérifications de rétroaction postérieures à l'action au lieu d'attendre de façon synchrone dans la boucle de trames;
10. conserver les images cibles apprises et les métadonnées de preuve;
11. importer des collections d'images à partir d'un dépôt public;
12. entraîner et noter facultativement des échantillons au moyen de l'apprenant intelligent distinct;
13. détecter facultativement les notifications de récompense et envoyer des rapports par webhook configurés par l'utilisateur;
14. produire des journaux et des mesures de temps pour diagnostiquer les détections manquées, les faux positifs et les blocages.

Le comparateur de base relève de la vision par ordinateur, et non d'une compréhension sémantique garantie. Un score de similarité élevé est un indice que deux régions se ressemblent selon une métrique donnée. Ce n'est pas une probabilité calibrée qu'une région soit un fantôme.

## Limites importantes et sécurité

- **La simulation (dry-run) ne signifie pas une entrée réelle.** `--dry-run` devrait consigner les actions envisagées et ne doit pas invoquer le véritable pilote d'entrée.
- **L'envoi d'une entrée n'est pas une confirmation du jeu.** Un appel `pydirectinput` réussi ne prouve pas que Highrise a accepté une capture.
- **Un changement de pixels est une rétroaction faible.** Une animation ambiante, un déplacement d'avatar et des changements d'interface sans rapport peuvent survenir après un clic. Une surveillance de récompense en bonne santé et correctement associée constitue une preuve plus solide.
- **Une graine n'encode pas le mouvement.** Les gabarits encodent l'apparence; la recherche dans chaque trame ou le suivi des candidats gère le mouvement.
- **Les captures d'écran de pièces entières ne sont pas de bons gabarits de cibles.** Elles contiennent des objets sans rapport et peuvent correspondre à n'importe quel décor. Traitez-les comme du matériel source jusqu'à ce qu'un véritable sprite ait été isolé.
- **La couleur seule est insuffisante.** Les tenues, les lumières, les décorations et les fantômes peuvent partager des couleurs. Utilisez des indices de forme et de contour ainsi que des tests sur des trames négatives.
- **Le comportement en lecture seule pour le client doit être imposé dans le moteur.** Masquer un bouton d'entraînement ne suffit pas si l'environnement d'exécution peut encore écrire des fichiers de modèle ou d'échantillons.
- **Échouez de façon sécuritaire en cas de mauvaise capture.** Si la fenêtre de jeu ou la trame ne peut pas être vérifiée, ignorez l'action et expliquez pourquoi. Ne reculez pas vers des clics aveugles sur l'ensemble du bureau.
- **Les raccourcis clavier globaux peuvent être limités par les permissions du système d'exploitation.** Conservez un bouton Arrêter dans l'interface graphique et/ou le recours à Ctrl+C.
- **La compatibilité des modèles et des échantillons est importante.** Une archive de modèle doit correspondre au prétraitement des caractéristiques et à l'architecture utilisés par le code choisi.
- **Ne publiez pas les secrets de webhook.** Utilisez un paramètre d'utilisateur privé ou une variable d'environnement lorsque c'est pris en charge. Une URL de webhook Discord d'apparence active figurait dans une configuration de développement; si elle était active, renouvelez-la. Ce README ne la reproduit pas.

## Structure du projet

Une distribution complète des sources devrait ressembler à ce qui suit. Certains éléments sont facultatifs et peuvent être absents d'une copie du dépôt composée uniquement d'images.

```text
bloop/
├── README.md
├── main.py                         # capture, pipeline de vision, sécurité, persistance et interface en ligne de commande
├── gui.py                          # interface graphique Tkinter de développement, le cas échéant
├── BLOOP.pyw                       # lanceur de l'interface sans console, le cas échéant
├── launch_gui.bat                  # lanceur avec console visible, le cas échéant
├── config.json                     # valeurs par défaut d'exécution, sans secrets
├── repository_import.py            # synchronisation des images sources et générateur de rognages
├── smart_ghost.py                  # modèle supervisé et suiveur facultatifs
├── sample_manager.py               # interface facultative de révision des échantillons
├── popup_dismiss.py                # assistant facultatif de fermeture des fenêtres d'achèvement
├── webhook_reporter.py             # OCR facultatif des notifications de récompense et rapporteur de webhook
├── smart/model.npz                # poids facultatifs du classificateur appris pour SmartGhost
├── VagueComplete.png               # image de référence facultative pour la fenêtre contextuelle
├── requirements.txt                # dépendances d'exécution
├── requirements-build.txt          # dépendances d'empaquetage
├── seeds/                          # images de fantômes et d'effets connus
├── learned/                        # images cibles apprises persistantes et métadonnées
├── ok/                             # références de surveillance de confirmation, jamais des cibles de clic
├── corpus/repository/               # corpus source d'images téléchargé
├── corpus/pending/                  # scènes et rognages non résolus en attente de révision
├── smart/positives/                 # échantillons positifs facultatifs
├── smart/negatives/                 # échantillons négatifs facultatifs
├── smart/quarantine/                # échantillons facultatifs en cours de révision
├── diagnostics/                     # superpositions et images de diagnostic
├── logs/                            # journaux rotatifs du robot et traces de démarrage de l'interface
├── .runtime/                        # fichier de contrôle coopératif de l'interface
├── tests/                            # tests unitaires, de fixtures, d'interface et d'intégration simulée
└── dist/                             # sortie de l'exécutable compilé; ne pas versionner à l'aveugle
```

### Matrice des responsabilités des fichiers

| Fichier ou dossier | Responsabilité | Limite importante |
|---|---|---|
| `main.py` | Moteur intégré, configuration, capture, détection, sécurité, intégration de l'apprentissage intelligent, envoi des clics, interface en ligne de commande | Les importations facultatives peuvent échouer; vérifiez les journaux de capacités au démarrage |
| `gui.py` | Panneau de contrôle Tkinter et gestion du processus du moteur | La vision, très gourmande en CPU, devrait s'exécuter dans le processus du moteur, et non dans le rappel Tk |
| `BLOOP.pyw` | Démarre l'interface graphique sans console supplémentaire | N'empaquette pas Python et ne compile pas le projet |
| `launch_gui.bat` | Démarrage avec console visible et diagnostics | Un lanceur ne remplace pas le moteur |
| `repository_import.py` | Synchronise les ressources d'images sources, dérive des rognages, consigne le manifeste et le rapport | Toutes les images sources ne sont pas nécessairement des cibles valides |
| `smart_ghost.py` | Données supervisées par les clics, caractéristiques, entraînement et inférence du modèle, suivi du mouvement | Chargé par l'instantané intégré lorsqu'il est disponible et activé dans la configuration |
| `sample_manager.py` | Révision facultative des échantillons positifs, négatifs et en quarantaine | La révision ne garantit pas un modèle valide sans entraînement ni validation |
| `popup_dismiss.py` | Détection facultative des fenêtres contextuelles et séquence d'actions | Les actions sur les fenêtres contextuelles sont distinctes des actions sur les fantômes |
| `webhook_reporter.py` | OCR des notifications, événements de gain et envoi HTTP | L'initialisation du rapporteur dépend de l'URL de webhook configurée et de la disponibilité du module; l'OCR nécessite Tesseract |
| `config.json` | Paramètres d'exécution | Ne doit pas contenir d'identifiants dans un dépôt public |
| `smart/model.npz` | Tableaux du modèle entraîné facultatif utilisés par `SmartGhost` | Doit correspondre au schéma de caractéristiques et de modèle; sauvegardez avant de le remplacer |
| `seeds/` | Références de cibles connues | Évitez les captures d'écran de pièces entières comme gabarits |
| `learned/` | Éléments de preuve de cibles apprises persistants | Sauvegardez ensemble les PNG et les métadonnées |
| `ok/` | Images de surveillance de confirmation | Les surveillances identifient un état; ce ne sont pas des cibles de clic |
| `corpus/pending/` | Matériel source qui n'a pas pu être rogné de façon sécuritaire | Révisez-le manuellement plutôt que de cliquer dessus automatiquement |

## Prérequis

### Système d'exploitation

Le flux de capture de fenêtre et d'entrée en direct est destiné principalement à Windows. Les utilitaires de traitement d'image purs peuvent être testés sur d'autres plateformes, mais un bac à sable Linux ne peut pas établir de véritables identifiants de fenêtre Windows, l'exactitude de la capture de la zone client, les crochets de clavier ni l'acceptation des entrées par le jeu.

### Python

Utilisez une version prise en charge de CPython compatible avec le manifeste de dépendances réel. Le code source fourni utilise une syntaxe de types moderne; Python 3.10 ou plus est une base pratique, mais vérifiez la version exacte exigée par votre recette de compilation.

```powershell
py --version
py -0p
python --version
```

Utilisez un seul interpréteur pour l'installation, les tests, l'interface graphique et l'empaquetage. Un paquet installé dans un environnement Python peut être absent d'un autre.

### Dépendances principales et facultatives

Le moteur de base importe NumPy et OpenCV. Les chemins facultatifs de capture et d'entrée utilisent `mss`, `pydirectinput`, `keyboard`, `pywin32` et `pynput`. Le module complémentaire d'OCR et de webhook peut utiliser `requests`, `pytesseract` et un exécutable Tesseract installé séparément.

Privilégiez le manifeste exact lorsqu'il est disponible :

```powershell
py -m pip install -r requirements.txt
```

N'exécutez cette commande que si la version extraite comprend réellement `requirements.txt`. La vue publique du dépôt inspectée pour ce guide ne montrait ni ce manifeste ni les modules d'exécution. Si vous préparez une copie des sources à partir des scripts fournis et qu'il n'y a pas de manifeste, utilisez les commandes d'installation explicites ci-dessous et tenez à jour un véritable fichier de dépendances pour votre version.

Pour un environnement de base minimal, les importations laissent croire que les paquets d'exécution suivants sont probablement nécessaires :

```powershell
py -m pip install numpy opencv-python mss pydirectinput keyboard pywin32 pynput
```

L'OCR et les rapports facultatifs peuvent aussi nécessiter :

```powershell
py -m pip install requests pytesseract
```

`pytesseract` est une enveloppe Python. Il n'installe pas le binaire Tesseract distinct. Vérifiez l'installation de l'OCR avec `tesseract --version` ou configurez le chemin pris en charge dans l'environnement.

### Note sur le GPU

Les appels ordinaires comme `cv2.matchTemplate` s'exécutent sur le CPU dans la version standard d'OpenCV. Une GTX 1050 Ti ne les accélère pas automatiquement. Ajustez les dimensions de la trame de travail, le nombre d'échelles de cibles, le budget de candidats, la réutilisation du cache et les opérations bloquantes avant de présumer qu'une accélération par GPU est nécessaire.

## Démarrage rapide

### 1. Obtenir le projet complet

```powershell
git clone https://github.com/Tenslaster/bloop.git
cd bloop
```

Cela ne produit une copie exécutable que si le dépôt contient les modules sources ainsi que les fichiers de dépendances et de données. Si le dépôt ne contient actuellement que des images, utilisez séparément le paquet complet des sources ou versez d'abord le code source.

### 2. Créer un environnement isolé

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Si la version comprend un manifeste de dépendances, installez-le avec :

```powershell
python -m pip install -r requirements.txt
```

Sinon, installez les dépendances selon les modules sources choisis, comme décrit plus haut. Ne présumez pas qu'une copie composée uniquement d'images contient du code exécutable.

Si l'activation est bloquée par la stratégie PowerShell, appelez directement l'interpréteur de l'environnement :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Configurer la racine du projet et la fenêtre

Gardez `config.json` à côté de `main.py`, ou passez `--root` avec le répertoire contenant la configuration et les dossiers de données. L'instantané de source intégrée documenté ici prend en charge `--process highrise.exe`; la correspondance par processus est préférable à une large correspondance de sous-chaîne dans le titre lorsqu'elle est configurée. Exécutez toujours `python main.py --help` avec la source ou l'exécutable exact que vous lancerez : un EXE figé peut avoir été compilé à partir d'un ancien analyseur d'arguments et rejeter des options qui existent dans un fichier `.py` plus récent.

### 4. Prévisualiser sans clics

```powershell
py main.py --root . --process highrise.exe --dry-run --scan-every-frame
```

Si le nom du processus cible est inconnu, utilisez `--list-windows` ainsi que la journalisation des processus et des titres de la source pour identifier le bon sélecteur. Gardez Highrise ouvert et visible. Confirmez la trame, les boîtes de détection, les noms des cibles, les coordonnées et les scores. La simulation (dry-run) ne devrait jamais appeler le pilote d'entrée réel.

### 5. Mode en direct une fois la prévisualisation correcte

```powershell
py main.py --root . --process highrise.exe --patient
```

Cela active l'entrée réelle pour la logique des cibles connues, sous réserve des garde-fous de sécurité configurés. N'utilisez `--explore` qu'après avoir validé la détection des cibles connues et le comportement sur les trames négatives. N'activez pas l'exploration pour contourner un chemin de capture défectueux. Si vous devez d'abord constituer l'apprenant, exécutez plutôt la commande du mode enseignant ci-dessous au lieu des clics autonomes.

### 6. Arrêter et examiner

Utilisez le raccourci clavier de sortie du moteur configuré (la valeur par défaut de la source intégrée est F12) ou Ctrl+C dans le terminal. L'interface graphique cliente distincte peut utiliser sa propre action F12 pour basculer entre démarrage et arrêt; ne présumez pas que le client et le moteur associent la même touche dans toutes les versions. Confirmez qu'un message d'arrêt et d'enregistrement propre s'affiche et examinez le plus récent fichier sous `logs/` avant de modifier des seuils.

## Liste de vérification du premier lancement

- [ ] Les fichiers sources complets et leurs dépendances sont présents.
- [ ] `config.json` s'analyse correctement et respecte le schéma attendu.
- [ ] L'interpréteur Python approprié a OpenCV et NumPy installés.
- [ ] Highrise est ouvert et son titre correspond à `window_title`.
- [ ] La capture produit une trame actuelle et non vide.
- [ ] La télémétrie des FPS et des cycles progresse.
- [ ] Les coordonnées de la superposition de diagnostic s'alignent avec la trame d'origine.
- [ ] Les images cibles sont des sprites rognés avec précision plutôt que des pièces entières.
- [ ] `ok/` ne contient que des références de confirmation et de surveillance.
- [ ] La prévisualisation détecte les fantômes et rejette les détails ordinaires de la pièce.
- [ ] Les zones d'exclusion protègent les menus, le clavardage et les éléments d'interface qui ne sont pas des cibles.
- [ ] Les plafonds de clics et les délais de récupération restent prudents pendant le réglage.
- [ ] Aucun message `CAPTURE WAIT` répété ne reste inexpliqué.
- [ ] L'entrée en direct n'est activée qu'après la vérification en simulation.
- [ ] `learned/`, les données du modèle et la configuration sont sauvegardés.
- [ ] Aucun secret de webhook n'est inclus dans les fichiers publics.

## Utilisation de l'interface graphique

L'interface graphique de développement est une surface de contrôle Tkinter autour d'un processus de moteur distinct. L'interface devrait rester réactive pendant que la vision s'exécute dans le processus enfant; la sortie des fils de travail devrait être renvoyée vers la boucle d'événements de Tk.

### Lancement

Lancement de l'interface sans console lorsque `BLOOP.pyw` existe :

```powershell
pyw BLOOP.pyw
```

Lancement de diagnostic avec console visible :

```powershell
py -3 gui.py
```

Un lanceur par lots fourni peut aussi servir aux diagnostics de démarrage visibles. Gardez-le simple et vérifiez quel interpréteur Python il sélectionne.

### Commandes

- **Prévisualisation / simulation (dry-run) :** détecte et consigne sans entrée réelle de la souris ou du clavier.
- **Démarrer en direct :** lance un processus qui peut envoyer des entrées réelles après les vérifications de sécurité.
- **Pause / Reprise :** suspend les actions sans supprimer l'état.
- **Arrêter et enregistrer :** demande un arrêt coopératif afin que les fichiers puissent être enregistrés.
- **Forcer l'arrêt (Kill) :** terminaison forcée lorsque l'arrêt coopératif échoue; peut entraîner la perte de l'état non enregistré.
- **Recharger la bibliothèque :** relit les cibles et les surveillances lorsque cela est mis en œuvre dans la version active de l'interface ou du moteur.
- **Afficher/masquer la console :** modifie l'espace vertical disponible pour les paramètres.
- **Enregistrer les paramètres :** écrit la configuration saisie; les paramètres s'appliquent généralement à un processus nouvellement démarré, sauf s'il existe un rechargement à chaud.

### Défilement et mise à l'échelle de l'écran

La surface des paramètres devrait utiliser une véritable barre de défilement et une région de défilement du Canvas correctement mise à jour. Si les derniers contrôles sont inaccessibles, utilisez la barre de défilement visible ou les touches Page précédente et Page suivante, agrandissez la fenêtre, masquez la zone de journal et testez la mise à l'échelle de Windows à 100 %, 125 % et 150 %. La gestion de la molette de la souris devrait fonctionner au-dessus des champs de saisie et des cases à cocher, et pas seulement sur l'espace vide. Liez les événements `<Configure>` des enfants pour mettre à jour la région de défilement et conservez un chemin de navigation au clavier.

### Ne cliquez pas sur l'interface graphique

L'interface graphique ne doit pas être confondue avec la capture de Highrise. En mode en direct, elle devrait masquer ou réduire le contrôleur, se mettre en pause lorsque le contrôleur est restauré et masquer le contrôleur avant de reprendre. Le moteur doit, de façon distincte, revalider la fenêtre de jeu sélectionnée et le point de clic proposé. Les protections limitées à l'interface ne suffisent pas.

## Interface en ligne de commande

L'analyseur de `main.py` inspecté actuellement prend en charge les options suivantes. Un exécutable compilé peut différer s'il a été construit à partir d'une autre révision; comparez sa sortie `--help` avant de vous fier à ces options.

| Option | Signification | Notes |
|---|---|---|
| `--window`, `-w` | Sous-chaîne du titre de la fenêtre | Utilisée lorsqu'aucun nom de processus n'est configuré ou sélectionné, selon les règles de détection des fenêtres |
| `--process` | Nom de l'exécutable ou du processus, p. ex. `highrise.exe` | Remplace le sélecteur de processus configuré dans l'instantané de source intégrée |
| `--teach` | Mode enseignant | Le robot n'envoie aucune entrée pendant qu'il recueille des exemples de clics humains, si l'apprentissage intelligent est branché et disponible |
| `--no-smart` | Désactive l'apprentissage intelligent supervisé par les clics | Revient à la logique non intelligente disponible dans cette version |
| `--root` | Racine des données et de la configuration du projet | Le répertoire courant par défaut |
| `--debug` | Mode de journalisation de débogage | Sortie de diagnostic plus détaillée |
| `--log-level` | `DEBUG`, `INFO`, `WARNING` ou `ERROR` | Remplacement courant pour la console et les fichiers |
| `--dry-run` | Aucune entrée réelle | À utiliser avant le mode en direct |
| `--explore` | Active l'exploration | Remplace le mode patient lorsque c'est pris en charge |
| `--patient` | Désactive les clics exploratoires | Les gabarits connus peuvent tout de même s'exécuter en direct |
| `--no-explore` | Désactive l'exploration des cibles jamais vues | Exploration désactivée |
| `--scan-every-frame` | Passage rapide de propositions sur chaque trame capturée | Plus de travail CPU est possible |
| `--full-template-every-frame` | Augmente le budget de gabarits exacts | Diagnostic et gourmand en CPU, mais toujours borné dans la source actuelle |
| `--control-file` | Fichier JSON de contrôle coopératif de l'interface | Utilisez un chemin unique pour chaque instance indépendante |
| `--reset-learned` | Supprime les données des cibles apprises | Destructif; sauvegardez d'abord |
| `--max-cps` | Remplace le budget de cadence de clics | Toujours borné par la validation |
| `--list-windows` | Liste les titres des fenêtres visibles | Ne démarre pas la détection |
| `--sync-repository [OWNER/REPO]` | Télécharge et importe les images du dépôt | Tâche ponctuelle, et non boucle de trames en direct |
| `--force-reimport` | Force la régénération des rognages | À associer à la synchronisation ou à la réimportation du corpus local |
| `--reimport-corpus` | Reconstruit les rognages à partir du corpus de dépôt local | Ne nécessite aucun appel réseau |

### Commandes courantes

Lister les fenêtres visibles :

```powershell
py main.py --list-windows
```

Prévisualiser uniquement les gabarits connus :

```powershell
py main.py --root . --window Highrise --dry-run --patient
```

Prévisualiser avec l'analyse rapide à chaque trame :

```powershell
py main.py --root . --window Highrise --dry-run --scan-every-frame
```

Mode en direct avec cibles connues seulement :

```powershell
py main.py --root . --window Highrise --patient
```

Mode en direct avec exploration activée après la validation de la prévisualisation :

```powershell
py main.py --root . --process highrise.exe --explore
```

Mode d'enseignement supervisé par un humain (aucune entrée de souris générée par le robot) :

```powershell
py main.py --root . --process highrise.exe --teach
```

Dans l'instantané de source intégrée, `--teach` désactive les clics autonomes de l'apprentissage intelligent et active le comportement de simulation (dry-run) du moteur pendant que le module intelligent écoute les clics de l'utilisateur. Ce n'est pas équivalent à une exécution sans capture : le jeu doit toujours être sélectionné et une trame valide doit être disponible. Vérifiez que les journaux de démarrage indiquent que l'apprenant intelligent et le crochet de clics sont disponibles avant de présumer que des échantillons sont recueillis.

Désactiver explicitement l'apprenant intelligent :

```powershell
py main.py --root . --process highrise.exe --no-smart --dry-run
```

Synchroniser la collection publique d'images de référence :

```powershell
py main.py --root . --sync-repository Tenslaster/bloop
```

Retraiter le corpus d'images local :

```powershell
py main.py --root . --reimport-corpus --force-reimport
```

N'utilisez les options de réinitialisation destructives qu'après avoir sauvegardé `learned/` et les métadonnées associées.
