#!/bin/bash
# Lecture seule. Aucun montage, GPIO, attachement/ejection ou reset USB.
set -u
printf '\n=== Versions ===\n'
pacman -Q kvmd python 2>/dev/null || true
printf '\n=== Drive 1 (lecture uniquement) ===\n'
kvmd-otgmsd -i 1
printf '\n=== LUN ===\n'
for attr in file cdrom ro removable nofua; do
    printf '%s: ' "$attr"
    cat "/sys/kernel/config/usb_gadget/kvmd/functions/mass_storage.usb1/lun.0/$attr" 2>/dev/null || true
done
printf '\n=== UDC et etat observe par Linux ===\n'
cat /sys/kernel/config/usb_gadget/kvmd/UDC 2>/dev/null || true
for state in /sys/class/udc/*/state; do cat "$state" 2>/dev/null || true; done
printf '\n=== Liens du gadget ===\n'
find /sys/kernel/config/usb_gadget/kvmd/configs -type l -printf '%p -> %l\n' 2>/dev/null || true
printf '\n=== Arret automatique (lecture) ===\n'
systemctl show pikvm-auto-shutdown.service -p ActiveState -p UnitFileState --no-pager
printf '\n=== Montages et loops existants ===\n'
findmnt -rn -o TARGET,SOURCE,FSTYPE,OPTIONS
losetup --list --output NAME,BACK-FILE,RO
printf '\nLe montage Windows et la lettre de lecteur ne sont pas observables ici.\n'
