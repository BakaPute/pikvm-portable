#!/bin/bash
# Diagnostic uniquement : aucune ecriture, aucun montage, aucune ejection.
# A executer via SSH apres saisie interactive du mot de passe par l'utilisateur.
# Ne lit ni mots de passe, ni override.yaml, ni configuration Wi-Fi privee.
set -u
export LC_ALL=C

printf '\n=== SYSTEM ===\n'
uname -a
pacman -Q kvmd exfatprogs util-linux python 2>/dev/null || true

printf '\n=== DRIVE MANAGEMENT HELP (READ ONLY) ===\n'
kvmd-otgmsd --help 2>&1 || true

printf '\n=== MASS STORAGE ATTRIBUTES (READ ONLY) ===\n'
shopt -s nullglob
for lun in /sys/kernel/config/usb_gadget/*/functions/mass_storage.*/lun.*; do
    printf '\n%s\n' "$lun"
    for attr in file ro cdrom removable nofua; do
        if [ -r "$lun/$attr" ]; then
            printf '%s: ' "$attr"
            cat "$lun/$attr"
        fi
    done
done

printf '\n=== USB STATE (READ ONLY) ===\n'
for state in /sys/class/udc/*/state; do
    printf '%s: ' "$state"
    cat "$state"
done

printf '\n=== SHARE IMAGE METADATA ONLY ===\n'
image=/var/lib/kvmd/msd/.PIKVM-SHARE.img
if [ -e "$image" ]; then
    stat -c 'path=%n size=%s blocks=%b mode=%a uid=%u gid=%g inode=%i' "$image"
    readlink -f "$image"
    findmnt -T "$image" -o TARGET,SOURCE,FSTYPE,OPTIONS
    df -h "$(dirname "$image")"
else
    printf 'Share image missing\n'
fi

printf '\n=== MOUNTS AND EXISTING LOOP ASSOCIATIONS ===\n'
findmnt -rn -o TARGET,SOURCE,FSTYPE,OPTIONS
# --list reads existing associations; never creates a loop device.
losetup --list --output NAME,BACK-FILE,RO 2>/dev/null || true

printf '\n=== SERVICES (READ ONLY) ===\n'
for service in kvmd kvmd-nginx wifi-wizard-api pikvm-auto-shutdown pikvm-share-api; do
    printf '%s: ' "$service"
    systemctl is-active "$service.service" 2>/dev/null || true
done

printf '\n=== NGINX AUTH INCLUDE (NO CREDENTIAL FILES) ===\n'
if [ -r /etc/kvmd/nginx/loc-login.conf ]; then
    cat /etc/kvmd/nginx/loc-login.conf
fi

printf '\n=== INSTALLED HELPER LOCATIONS ===\n'
command -v kvmd-otgmsd kvmd-helper-otgmsd-remount mount umount losetup fsck.exfat || true
printf '\n=== END: NO IMAGE CONTENT READ, NO STATE CHANGED BY THIS SCRIPT ===\n'
