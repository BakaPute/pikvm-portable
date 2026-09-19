# Réinstallation sur une nouvelle carte microSD

## 1. Installer PiKVM

Installer une image PiKVM compatible Raspberry Pi Zero 2 W.

Configurer le Wi-Fi afin d'obtenir un accès SSH.

## 2. Mettre PiKVM à jour

Effectuer les mises à jour PiKVM avant d'installer les modifications de ce projet.

## 3. Cloner le dépôt

    cd /root
    git clone https://github.com/BakaPute/pikvm-portable.git
    cd pikvm-portable

## 4. Installer

    chmod +x install.sh
    ./install.sh

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
