#!/bin/bash

set -e

# ------------------------------------------------------------
# PiKVM Portable - Installation automatique
# ------------------------------------------------------------

# L'installation doit être lancée en root.
if [ "$(id -u)" -ne 0 ]; then
    echo "ERREUR : lance ce script en root."
    exit 1
fi

# Dossier dans lequel se trouve install.sh.
REPO="$(cd "$(dirname "$0")" && pwd)"

echo
echo "======================================"
echo " Installation du PiKVM portable"
echo "======================================"
echo

# Passe le système PiKVM en mode lecture/écriture.
rw

# Maintient immédiatement l'alimentation.
# GPIO17 commande le système de maintien du relais.
pinctrl set 17 op dh

echo "[OK] GPIO17 maintenu à HIGH"
echo
echo ">>> TU PEUX MAINTENANT RELACHER LE BOUTON POWER <<<"
echo

# GPIO18 = bouton physique.
pinctrl set 18 ip pd

# Attend réellement que le bouton soit relâché.
while pinctrl get 18 | grep -q "| hi"
do
    sleep 0.1
done

sleep 0.3

echo "[OK] Bouton POWER relâché"

# ------------------------------------------------------------
# I2C OLED / MAX17048
# ------------------------------------------------------------

REBOOT_I2C=0

if [ ! -e /dev/i2c-1 ]; then

    if ! grep -qxF "dtparam=i2c_arm=on" /boot/config.txt; then
        echo "dtparam=i2c_arm=on" >> /boot/config.txt
        echo "[OK] I2C activé dans /boot/config.txt"
    else
        echo "[OK] I2C déjà configuré dans /boot/config.txt"
    fi

    REBOOT_I2C=1

    echo "[INFO] I2C sera disponible après redémarrage"

else

    echo "[OK] Bus I2C déjà disponible"

fi

# Fonction exécutée automatiquement si le script s'arrête.
fin_installation() {
    ro >/dev/null 2>&1 || true
}

trap fin_installation EXIT

echo
echo "[1/8] Installation des dépendances..."

# N'installe que les paquets réellement absents.
# Cela évite une mise à jour partielle de Python / KVMD.

PAQUETS=(
    hostapd
    dnsmasq
    qrencode
    i2c-tools
    v4l-utils
    patch
)

MANQUANTS=()

for PAQUET in "${PAQUETS[@]}"
do
    if ! pacman -Q "$PAQUET" >/dev/null 2>&1; then
        MANQUANTS+=("$PAQUET")
    fi
done

if [ "${#MANQUANTS[@]}" -gt 0 ]; then

    echo "Paquets manquants : ${MANQUANTS[*]}"

    pacman -Sy --needed --noconfirm "${MANQUANTS[@]}"

else

    echo "[OK] Tous les paquets système sont déjà présents"

fi

# Ces bibliothèques Python sont normalement fournies par PiKVM.
python3 - <<'PYDEPS'
import PIL
import smbus2
import luma.core
import luma.oled

print("[OK] Bibliothèques Python présentes")
PYDEPS

echo "[OK] Dépendances installées"

echo
echo "[2/8] Création des sauvegardes..."

BACKUP="/root/pikvm-portable-backup-$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP"

sauvegarder() {
    FICHIER="$1"

    if [ -e "$FICHIER" ]; then
        mkdir -p "$BACKUP$(dirname "$FICHIER")"
        cp -a "$FICHIER" "$BACKUP$FICHIER"
    fi
}

sauvegarder /usr/share/kvmd/web/index.html
sauvegarder /usr/share/kvmd/web/kvm/index.html
sauvegarder /usr/share/kvmd/web/share/js/power-control.js

echo "[OK] Sauvegardes : $BACKUP"

echo
echo "[3/8] Installation des scripts..."

install -m 755 \
    "$REPO/scripts/pikvm-oled-custom" \
    /usr/local/bin/pikvm-oled-custom

install -m 755 \
    "$REPO/scripts/pikvm-button-menu" \
    /usr/local/bin/pikvm-button-menu

install -m 755 \
    "$REPO/scripts/pikvm-power-hold-startup" \
    /usr/local/bin/pikvm-power-hold-startup

install -m 755 \
    "$REPO/scripts/pikvm-hotspot" \
    /usr/local/bin/pikvm-hotspot

install -m 755 \
    "$REPO/scripts/wifi-wizard-api" \
    /usr/local/bin/wifi-wizard-api

install -m 755 \
    "$REPO/scripts/pikvm-auto-shutdown" \
    /usr/local/bin/pikvm-auto-shutdown

echo "[OK] Scripts installés"

echo
echo "[4/8] Installation des services systemd..."

cp -a "$REPO/systemd/"*.service \
    /etc/systemd/system/

mkdir -p \
    /etc/systemd/system/pikvm-oled-custom.service.d

cp -a \
    "$REPO/systemd/pikvm-oled-custom.service.d/power-hold.conf" \
    /etc/systemd/system/pikvm-oled-custom.service.d/

install -m 755 \
    "$REPO/systemd-shutdown/pikvm-power-cut" \
    /usr/lib/systemd/system-shutdown/pikvm-power-cut

systemctl daemon-reload

echo "[OK] Services installés"

echo
echo "[5/8] Configuration du hotspot de dépannage..."

HOTSPOT_ENV="/etc/kvmd/pikvm-hotspot.env"

if [ ! -f "$HOTSPOT_ENV" ]; then

    echo
    echo "Configuration du Wi-Fi de dépannage."
    echo

    read -r -p "Nom du hotspot [PiKVM-Setup] : " HOTSPOT_SSID
    HOTSPOT_SSID="${HOTSPOT_SSID:-PiKVM-Setup}"

    while true; do
        read -r -s -p "Mot de passe du hotspot (8 caractères minimum) : " HOTSPOT_PASS
        echo

        if [ "${#HOTSPOT_PASS}" -ge 8 ]; then
            break
        fi

        echo "Le mot de passe doit contenir au moins 8 caractères."
    done

    cat > "$HOTSPOT_ENV" <<HOTSPOTCONF
HOTSPOT_SSID="$HOTSPOT_SSID"
HOTSPOT_PASS="$HOTSPOT_PASS"
HOTSPOT_IP="192.168.50.1"
HOTSPOTCONF

    chmod 600 "$HOTSPOT_ENV"

    echo "[OK] Configuration hotspot créée"

else

    echo "[OK] Configuration hotspot existante conservée"

fi

source "$HOTSPOT_ENV"

cat > /etc/kvmd/pikvm-hotspot-hostapd.conf <<HOTSPOTCONF
interface=wlan0
driver=nl80211

ssid=${HOTSPOT_SSID}

country_code=FR
hw_mode=g
channel=6

ieee80211n=1
wmm_enabled=1

auth_algs=1

wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_passphrase=${HOTSPOT_PASS}
HOTSPOTCONF

cat > /etc/kvmd/pikvm-hotspot-dnsmasq.conf <<HOTSPOTCONF
interface=wlan0
bind-interfaces

dhcp-range=192.168.50.10,192.168.50.100,255.255.255.0,12h

dhcp-option=3,${HOTSPOT_IP}
dhcp-option=6,${HOTSPOT_IP}

dhcp-leasefile=/run/pikvm-hotspot.leases
pid-file=/run/pikvm-hotspot-dnsmasq.pid

address=/pikvm.setup/${HOTSPOT_IP}

no-resolv
log-dhcp
HOTSPOTCONF

echo "[OK] Hotspot configuré"

echo
echo "[6/8] Installation de l'interface web..."

mkdir -p /usr/share/kvmd/web/extras/wifi-wizard
mkdir -p /usr/share/kvmd/web/power-terminal
mkdir -p /usr/share/kvmd/web/share/js

cp -a \
    "$REPO/web/extras/wifi-wizard/." \
    /usr/share/kvmd/web/extras/wifi-wizard/

cp -a \
    "$REPO/web/power-terminal/." \
    /usr/share/kvmd/web/power-terminal/

cp \
    "$REPO/web/share/js/power-control.js" \
    /usr/share/kvmd/web/share/js/power-control.js

mkdir -p /usr/share/kvmd/extras/wifi-wizard

cp -a \
    "$REPO/kvmd-extras/wifi-wizard/." \
    /usr/share/kvmd/extras/wifi-wizard/

echo "[OK] Extension nginx Wi-Fi Wizard installée"

python3 - <<'PY'
from pathlib import Path

script = '<script src="/share/js/power-control.js"></script>'

pages = [
    Path("/usr/share/kvmd/web/index.html"),
    Path("/usr/share/kvmd/web/kvm/index.html"),
]

for page in pages:

    if not page.exists():
        print(f"[ATTENTION] Page absente : {page}")
        continue

    text = page.read_text()

    if script in text:
        print(f"[OK] power-control.js déjà présent : {page}")
        continue

    if "</body>" not in text:
        print(f"[ATTENTION] Impossible de modifier : {page}")
        continue

    text = text.replace(
        "</body>",
        script + "\n</body>",
        1,
    )

    page.write_text(text)

    print(f"[OK] power-control.js ajouté : {page}")
PY

echo "[OK] Interface web installée"

echo
echo "[7/8] Installation du suivi d'activité clavier/souris..."

HID_FILE="$(python3 -c \
'import inspect, kvmd.apps.kvmd.api.hid as h; print(inspect.getsourcefile(h))')"

echo "Fichier HID détecté : $HID_FILE"

if grep -q "PIKVM_HID_ACTIVITY_MARKER" "$HID_FILE"; then

    echo "[OK] Suivi HID déjà installé"

else

    # Sauvegarde le fichier original avant modification.
    sauvegarder "$HID_FILE"

    echo "Vérification de la compatibilité du patch..."

    if patch \
        --dry-run \
        --forward \
        --batch \
        "$HID_FILE" \
        < "$REPO/patches/hid-activity.patch" \
        >/dev/null
    then

        echo "Application du patch..."

        patch \
            --forward \
            --batch \
            "$HID_FILE" \
            < "$REPO/patches/hid-activity.patch"

    else

        echo
        echo "ERREUR : le fichier HID de cette version de PiKVM"
        echo "n'est pas compatible avec le patch."
        echo
        echo "Aucun patch HID n'a été appliqué."
        exit 1

    fi

fi

python3 -m py_compile "$HID_FILE"

echo "[OK] Suivi d'activité HID installé"

echo
echo "[8/8] Activation des services..."

systemctl disable --now kvmd-oled.service \
    2>/dev/null || true

systemctl daemon-reload

systemctl enable pikvm-power-hold.service
systemctl enable pikvm-oled-custom.service
systemctl enable pikvm-button-menu.service
systemctl enable wifi-wizard-api.service
systemctl enable pikvm-auto-shutdown.service

echo "[OK] Services activés"

echo
echo "Vérification des scripts Python..."

python3 -m py_compile \
    /usr/local/bin/pikvm-oled-custom

python3 -m py_compile \
    /usr/local/bin/pikvm-button-menu

python3 -m py_compile \
    /usr/local/bin/wifi-wizard-api

python3 -m py_compile \
    /usr/local/bin/pikvm-auto-shutdown

echo "[OK] Scripts Python valides"

echo
echo "Démarrage des services personnalisés..."

# Le bouton a déjà été relâché plus haut.
systemctl restart pikvm-power-hold.service

if [ "$REBOOT_I2C" -eq 0 ]; then

    systemctl restart pikvm-oled-custom.service
    systemctl restart pikvm-button-menu.service

else

    echo "[INFO] OLED et menu bouton démarreront après le redémarrage I2C"

fi

systemctl restart wifi-wizard-api.service
systemctl restart pikvm-auto-shutdown.service

echo "[OK] Services personnalisés démarrés"

echo
echo "Rechargement de PiKVM..."

systemctl restart kvmd.service
systemctl restart kvmd-nginx.service

echo "[OK] PiKVM rechargé"

echo
echo "Contrôle des services..."

SERVICES="
pikvm-power-hold
pikvm-oled-custom
pikvm-button-menu
wifi-wizard-api
pikvm-auto-shutdown
"

for SERVICE in $SERVICES
do

    if systemctl is-active --quiet "$SERVICE.service"; then
        echo "[OK] $SERVICE"
    else
        echo "[ERREUR] $SERVICE n'est pas actif"
        systemctl --no-pager --full status "$SERVICE.service" || true
    fi

done

echo
echo "Contrôle I2C..."

if [ -e /dev/i2c-1 ]; then

    I2C_RESULT="$(i2cdetect -y 1)"

    if echo "$I2C_RESULT" | grep -q "36"; then
        echo "[OK] MAX17048 détecté à 0x36"
    else
        echo "[ATTENTION] MAX17048 non détecté"
    fi

    if echo "$I2C_RESULT" | grep -q "3c"; then
        echo "[OK] OLED détecté à 0x3C"
    else
        echo "[ATTENTION] OLED non détecté"
    fi

else

    echo "[ATTENTION] /dev/i2c-1 absent"
    echo "[INFO] Redémarrage nécessaire pour activer I2C"

fi

echo

echo "======================================"
echo " Installation terminée"
echo "======================================"
echo
echo "Sauvegarde des anciens fichiers :"
echo "$BACKUP"
echo
echo "Configuration du hotspot :"
echo "/etc/kvmd/pikvm-hotspot.env"
echo
echo "Pour effectuer un contrôle complet :"
echo "cd $REPO"
echo "./check-install.sh"
echo
