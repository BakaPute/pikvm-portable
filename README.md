# PiKVM portable sur batterie

Projet de PiKVM portable basé sur un Raspberry Pi Zero 2 W.

L'objectif est de disposer d'un PiKVM autonome sur batterie avec :

- alimentation par batterie 18650 ;
- recharge par USB-C ;
- arrêt électrique complet grâce à un relais ;
- bouton physique multifonction ;
- écran OLED 128x64 ;
- mesure de batterie avec MAX17048 ;
- point d'accès Wi-Fi de dépannage ;
- assistant Wi-Fi depuis l'interface web ;
- niveau de batterie dans l'interface PiKVM ;
- arrêt après inactivité disponible sur activation manuelle ;
- capture HDMI ;
- clavier et souris KVM par USB-C.

## Matériel utilisé

- Raspberry Pi Zero 2 W
- adaptateur HDMI vers CSI compatible PiKVM
- écran OLED 128x64 I2C
- MAX17048
- batterie 18650
- module de charge/protection 1 cellule
- convertisseur Step-Up réglé à 5,1 V
- relais SRD-05VDC-SL-C
- module MOSFET low-side
- bouton poussoir momentané
- breakout USB-C USB 2.0 avec résistances 5,1 kΩ sur CC1 et CC2
- diodes Schottky SS34
- résistance 47 kΩ
- résistances 100 kΩ

## GPIO utilisés

| Fonction | GPIO | Broche physique |
|---|---:|---:|
| Maintien alimentation | GPIO17 | 11 |
| Bouton | GPIO18 | 12 |
| I2C SDA | GPIO2 | 3 |
| I2C SCL | GPIO3 | 5 |

Les GPIO 22, 23, 24 et 27 sont laissés à PiKVM pour les fonctions ATX.

## Périphériques I2C

- MAX17048 : `0x36`
- OLED : `0x3C`

## Jauge de batterie

Le pourcentage affiché est calculé à partir de la tension :

- 3,10 V = 0 %
- 4,13 V = 100 %

Les valeurs sont limitées entre 0 et 100 %.

## Fonctionnement de l'alimentation

Le relais coupe le positif de la batterie avant le Step-Up.

Le module MOSFET ne coupe plus la masse du Raspberry Pi. Il sert uniquement à commander la bobine du relais.

Toutes les masses restent donc reliées en permanence, ce qui évite les problèmes de retour de masse par HDMI ou USB.

GPIO17 maintient le relais actif après le démarrage.

Lors d'un arrêt propre, GPIO17 repasse à LOW et le relais coupe totalement l'alimentation.

## Arrêt automatique

Sur activation manuelle du service d'inactivité, le PiKVM s'éteint lorsque les deux conditions suivantes restent vraies pendant une heure :

- aucun signal HDMI ;
- aucune activité clavier ou souris via le KVM.

Une activité clavier ou souris remet le compteur à zéro.

Les installateurs et PIKVM-SHARE ne démarrent ni n'activent automatiquement
`pikvm-auto-shutdown.service`. Son état volontairement désactivé est conservé.

Le retour du signal HDMI remet également le compteur à zéro.

## Installation

L'objectif de ce dépôt est de pouvoir repartir d'une installation PiKVM neuve sur une nouvelle carte microSD.

La procédure finale sera :

    git clone https://github.com/BakaPute/pikvm-portable.git
    cd pikvm-portable
    chmod +x install.sh
    ./install.sh

L'installateur sauvegardera les fichiers d'origine avant toute modification.

## Documentation

La documentation détaillée se trouve dans le dossier `docs/`.

Elle explique notamment :

- le matériel utilisé ;
- le câblage électrique ;
- le fonctionnement de l'alimentation ;
- la batterie et le MAX17048 ;
- l'écran OLED ;
- le bouton physique ;
- le Wi-Fi de dépannage ;
- l'interface web ;
- l'USB-C ;
- l'arrêt automatique ;
- la réinstallation complète sur une nouvelle carte microSD.

## Important

Certaines modifications de ce projet touchent directement des fichiers de PiKVM.

Une mise à jour de PiKVM peut donc écraser certaines modifications.

Après une mise à jour de PiKVM, il peut être nécessaire de relancer `install.sh`.

## Premier démarrage sur une carte microSD neuve

Le montage d'alimentation nécessite de maintenir physiquement le bouton POWER pendant le premier démarrage, car GPIO17 n'est pas encore configuré par le projet.

Lancer ensuite `install.sh`.

Dès que l'installateur affiche :

    [OK] GPIO17 maintenu à HIGH
    >>> TU PEUX MAINTENANT RELACHER LE BOUTON POWER <<<

le bouton doit être relâché.

Si `/dev/i2c-1` n'existe pas, l'installateur ajoute automatiquement :

    dtparam=i2c_arm=on

dans `/boot/config.txt`.

Un redémarrage est alors nécessaire pour l'OLED et le MAX17048.

## Image Manager et dossiers

Le PiKVM dispose d'un gestionnaire d'images accessible
depuis sa page d'accueil.

- Importation ISO, IMG et RAW depuis le navigateur.
- Progression et annulation des uploads.
- Transfert USB via PIKVM-XFER.
- Création et navigation dans les dossiers.
- Renommage, déplacement et suppression sécurisés.
- Espace disque utilisé et disponible.
- Sélection des images dans Drive.
- Navigateur de dossiers indépendant dans Drive.

Le disque technique .USB-TRANSFER.img reste masqué.
Les transferts USB et les dossiers sont installés
automatiquement par install.sh.

## PIKVM-SHARE — clé USB indépendante

Gestion Web de l'image exFAT existante `.PIKVM-SHARE.img` sur le **Drive 1** :
fichiers/dossiers, import et téléchargement, espace disponible et bascule USB/Web
avec éjection propre obligatoire côté PC. Authentification par la session PiKVM.

Installation ciblée : `bash install.sh --share-only`, après sauvegarde et
autorisation de déploiement. Ce chemin ne configure aucun GPIO et ne redémarre
pas KVMD. Il exige une image existante et un Drive 1 déjà configuré.

Voir [la procédure complète, les sauvegardes et la restauration](docs/pikvm-share.md).

## PiKVM Portable OS — interface unifiée

Première version sur la branche `codex/portable-os`, issue de `feature/pikvm-share`.
Application unique à `/extras/portable-os/` : tableau de bord, moteur KVM natif
intégré, bibliothèque d'images/Drive 0, SHARE/Drive 1, Wi-Fi, hotspot, terminal,
journaux, alimentation et paramètres. Navigation sans rechargement, composants
et dialogues partagés, thèmes sombre/clair, états centralisés.

Sans dépendance serveur supplémentaire ni compilation sur le Pi. L'installation
additive conserve toutes les interfaces historiques et leurs correctifs.
Voir [architecture, tests, diagnostic Windows et déploiement](docs/portable-os.md).

La candidate **0.2.0-rc.1** ajoute le précontrôle d'intégrité Python, la réparation
ciblée préparée de logging, les contrôles d'attachement USB et la migration
progressive. Voir [la procédure exacte et l'audit des modules](docs/portable-os-rc1.md).

La candidate **0.2.0-rc.2** fait de Portable OS l'entrée `/`, intègre les contrôles
KVM natifs dans une barre flottante et conserve un menu de secours autonome
`/legacy/`. Voir [mise à jour, tests et retour arrière](docs/portable-os-rc2.md).

La candidate **0.2.0-rc.3** ajoute le [miroir OLED interactif](docs/portable-os-oled.md) :
pixels partagés avec les producteurs physiques, fonctionnement sans écran I2C et
appui court logique authentifié depuis la carte Pi Zero 2 W.

La candidate **0.2.0-rc.4** rend l'accès SSD1306 facultatif et non bloquant :
[mode virtuel, reconnexion automatique, tests et mise à jour](docs/portable-os-rc4.md).

La candidate **0.2.0-rc.5** intègre l'OLED dans la sidebar, ajoute les maintiens
logiques avec annulation et gardes sensibles, et sépare la télémétrie du rendu :
[architecture, tests, mise à jour et rollback](docs/portable-os-rc5.md).

La candidate **0.2.0-rc.6** sépare les gestes OLED du rafraîchissement et place les
commandes KVM et leurs panneaux dans Portable OS, en réutilisant les contrôleurs
natifs : [diagnostic, validations, installation et restauration RC5](docs/portable-os-rc6.md).
