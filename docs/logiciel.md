# Fonctions logicielles

## Écran OLED

Script :

    /usr/local/bin/pikvm-oled-custom

L'écran affiche plusieurs pages :

1. état principal du PiKVM ;
2. batterie ;
3. informations système.

## Batterie

Le pourcentage est calculé à partir de la tension :

    3,10 V = 0 %
    4,13 V = 100 %

Les valeurs sont limitées entre 0 et 100 %.

Le MAX17048 fournit également le taux de charge avec le registre CRATE.

## Bouton physique

Script :

    /usr/local/bin/pikvm-button-menu

Menus disponibles :

    POWER
    WIFI
    DEPANNAGE

Dans POWER :

    maintien 2 s -> redémarrage des services PiKVM
    maintien 5 s -> arrêt complet

## Wi-Fi de dépannage

Le menu DEPANNAGE permet d'activer un point d'accès Wi-Fi.

Adresse utilisée :

    192.168.50.1

Le SSID et le mot de passe sont configurables.

## Assistant Wi-Fi web

Backend :

    /usr/local/bin/wifi-wizard-api

Interface :

    /usr/share/kvmd/web/extras/wifi-wizard/

## Batterie dans l'interface web

Script :

    /usr/share/kvmd/web/share/js/power-control.js

Il affiche :

- le pourcentage ;
- la tension ;
- l'état de charge.

## Détection d'activité HID

Le fichier HID de PiKVM est modifié afin d'enregistrer la dernière activité clavier/souris dans :

    /run/kvmd/pikvm-hid-last-activity

Sont pris en compte :

- clavier ;
- clic souris ;
- déplacement souris ;
- déplacement relatif ;
- molette.

## Arrêt automatique

Script :

    /usr/local/bin/pikvm-auto-shutdown

Délai :

    3600 secondes

Le PiKVM s'arrête uniquement si :

    aucun signal HDMI
    ET
    aucune activité HID pendant 1 heure

Avant l'arrêt, le fichier suivant est créé :

    /run/pikvm-poweroff-requested

Le hook de shutdown repasse ensuite GPIO17 à LOW pour couper le relais.
