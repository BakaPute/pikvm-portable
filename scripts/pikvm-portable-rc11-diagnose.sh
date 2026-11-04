#!/bin/bash
# Read-only RC11 admission evidence. No credentials, GPIO writes or USB actions.
set -u
step() { printf '\n[%s] %s\n' "$(date -Is)" "$1"; }
step 'Versions'; uname -r; pacman -Q kvmd python
step 'Services'; timeout -k 2 15 systemctl show --no-pager --property=Id,ActiveState,SubState,NRestarts pikvm-power-hold.service kvmd.service kvmd-nginx.service pikvm-portable-api.service pikvm-button-menu.service pikvm-oled-custom.service kvmd-pst.service
step 'GPIO en lecture seule'; timeout -k 2 5 pinctrl get 17; timeout -k 2 5 pinctrl get 18
step 'PST fstab'; awk '!/^#/ && /X-kvmd.pst-/ {print}' /etc/fstab
step 'PST montages'; findmnt -rn -o TARGET,SOURCE,FSTYPE,OPTIONS | awk '$1 ~ /\/pst($|\/)/ {print}'
step 'PST API'; if test -S /run/kvmd/pst.sock; then timeout -k 2 5 curl --silent --show-error --max-time 4 --unix-socket /run/kvmd/pst.sock http://localhost/state; else printf 'Socket PST par défaut absent\n'; fi
step 'Lecteurs (lecture seule)'; for i in 0 1; do p="/sys/kernel/config/usb_gadget/kvmd/functions/mass_storage.usb$i/lun.0"; printf 'Drive %s\n' "$i"; for a in file ro cdrom; do printf '%s=' "$a"; cat "$p/$a"; done; done
step 'Transfert et bail (existence seulement)'; for p in /run/pikvm-share/lease.json /run/pikvm-usb-transfer-state.json /run/pikvm-poweroff-requested /run/pikvm-portable-install.lock; do if test -e "$p"; then stat -c '%n %s bytes' "$p"; else printf '%s absent\n' "$p"; fi; done
step 'Mémoire'; free -m; cat /proc/pressure/memory
step 'Sommes applicatives'; sha256sum /usr/local/bin/pikvm-oled-custom /usr/local/bin/pikvm-button-menu /usr/local/lib/pikvm-portable/pikvm_oled.py /usr/local/lib/pikvm-portable/pikvm_gpio.py
step 'Version interface'; grep -o 'RC[0-9][0-9.]*' /usr/share/kvmd/web/extras/portable-os/index.html | head -1
step 'Images conservées (noms et tailles, aucune lecture des 4 Gio)'; find /var/lib/kvmd/msd -maxdepth 4 -type f \( -iname '*.iso' -o -name '.USB-TRANSFER.img' \) -printf '%P %s bytes\n'
step 'Fin du diagnostic passif'
