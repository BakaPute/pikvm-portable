# Réinstallation sur une nouvelle carte microSD

## 1. Installer PiKVM

Installer une image PiKVM compatible Raspberry Pi Zero 2 W.

Configurer le Wi-Fi afin d'obtenir un accès SSH.

## 2. Vérifier la compatibilité

Pour RC10, vérifier KVMD 4.213 et Python 3.14.7-1. Ne pas lancer de mise à jour
globale ou partielle pour faire passer un précontrôle. Préparer séparément les
dépendances officielles compatibles manquantes, après autorisation.

## 3. Cloner le dépôt

    cd /root
    git clone https://github.com/BakaPute/pikvm-portable.git
    cd pikvm-portable

## 4. Installer

    chmod +x install.sh
    ./install.sh --initial-hardware-setup

Cette commande configure GPIO17/18 et le démarrage sur une **nouvelle carte** ; elle
exige une validation matérielle explicite. Elle ne doit jamais servir à mettre à
jour le Pi actuel ni remplacer sa configuration GPIO18 `ip --` validée. Pour une
mise à jour existante, suivre [la migration additive RC10](portable-os-rc10-audit.md).
Le conteneur `.USB-TRANSFER.img`, SHARE et les ISO utilisateur restent à conserver.

## 5. Configurer le hotspot

Modifier :

    /etc/kvmd/pikvm-hotspot.env

## 6. Vérifier les périphériques I2C

    i2cdetect -y 1

Résultat attendu :

    0x36 = MAX17048
    0x3C = OLED

## 7. Vérifier les GPIO

    pinctrl get 17
    pinctrl get 18

GPIO17 doit être utilisé pour le maintien d'alimentation.

GPIO18 doit être utilisé pour le bouton.

## 8. Vérifier les services

    systemctl status pikvm-power-hold.service
    systemctl status pikvm-oled-custom.service
    systemctl status pikvm-button-menu.service
    systemctl status wifi-wizard-api.service
    systemctl status pikvm-auto-shutdown.service

## 9. Vérifier l'USB KVM

    cat /sys/class/udc/*/state

Résultat attendu lorsque le PC est connecté :

    configured

## 10. Vérifier l'alimentation

    vcgencmd get_throttled

Résultat attendu :

    throttled=0x0

## 11. Lancer le contrôle complet

    ./check-install.sh

## 12. Restaurer PIKVM-SHARE

Restaurer la configuration existante du Drive 1 et la sauvegarde de
`.PIKVM-SHARE.img`, puis utiliser l'installateur ciblé :

    bash install.sh --share-only

L'installateur SHARE ne configure ni les GPIO ni le Drive 0 et ne recrée aucune
image manquante. Consulter [la procédure SHARE](pikvm-share.md) pour l'ordre des
étapes, les sauvegardes, les précontrôles et le retour arrière. Ne pas utiliser
PIKVM-XFER pour initialiser ou restaurer l'image SHARE.
