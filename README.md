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
- arrêt automatique après inactivité ;
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

Le PiKVM s'éteint automatiquement lorsque les deux conditions suivantes restent vraies pendant une heure :

- aucun signal HDMI ;
- aucune activité clavier ou souris via le KVM.

Une activité clavier ou souris remet le compteur à zéro.

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
