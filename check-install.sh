#!/bin/bash

echo
echo "======================================"
echo " Vérification du PiKVM portable"
echo "======================================"

echo
echo "=== GPIO ==="

echo -n "GPIO17 : "
pinctrl get 17

echo -n "GPIO18 : "
pinctrl get 18

echo
echo "=== I2C ==="

i2cdetect -y 1

echo
echo "=== SERVICES ==="

SERVICES="
pikvm-power-hold
pikvm-oled-custom
pikvm-button-menu
wifi-wizard-api
pikvm-auto-shutdown
"

for SERVICE in $SERVICES
do
    printf "%-30s : " "$SERVICE"
    systemctl is-active "$SERVICE.service" 2>/dev/null || true
done

echo
echo "=== USB KVM ==="

cat /sys/class/udc/*/state 2>/dev/null || \
echo "Contrôleur USB non trouvé"

echo
echo "=== ALIMENTATION ==="

vcgencmd get_throttled 2>/dev/null || true

echo
echo "=== BATTERIE ==="

curl -s \
http://127.0.0.1:9876/api/battery \
2>/dev/null || \
echo "API batterie inaccessible"

echo

echo
echo "=== ARRET AUTOMATIQUE ==="

if [ -f /run/pikvm-auto-shutdown-state.json ]; then
    cat /run/pikvm-auto-shutdown-state.json
    echo
else
    echo "Fichier d'état absent"
fi

echo
echo "=== ACTIVITE CLAVIER / SOURIS ==="

if [ -f /run/kvmd/pikvm-hid-last-activity ]; then

    python3 - <<'PY'
import time
from pathlib import Path

p = Path("/run/kvmd/pikvm-hid-last-activity")

try:
    timestamp = float(p.read_text().strip())
    age = max(0, time.time() - timestamp)
    print(f"Dernière activité HID : il y a {age:.1f} secondes")
except Exception as err:
    print(f"Erreur : {err}")
PY

else
    echo "Aucune activité HID enregistrée"
fi

echo
echo "=== WIFI WIZARD ==="

if ss -ltn | grep -q '127.0.0.1:9876'; then
    echo "[OK] API Wi-Fi active sur 127.0.0.1:9876"
else
    echo "[ERREUR] API Wi-Fi non détectée"
fi

echo
echo "======================================"
echo " Vérification terminée"
echo "======================================"
echo
