#!/bin/sh
# KVMD 4.213 otgmsd uses these exact configfs attributes. Read only, no Python,
# no KVMD configuration/plugin initialization. Unknown/unstable/attached = fail.
set -eu
LC_ALL=C
export LC_ALL
lun=/sys/kernel/config/usb_gadget/kvmd/functions/mass_storage.usb1/lun.0
snapshot() {
    for attr in file cdrom ro removable nofua; do
        # Hex keeps NUL/malformed bytes observable: shell substitutions would
        # otherwise silently discard NUL and could turn unknown into "empty".
        raw=$(od -An -v -tx1 "$lun/$attr") || { printf 'LUN_READ_ERROR %s\n' "$attr" >&2; return 1; }
        set -- $raw
        if [ "$attr" = file ]; then
            if [ "$#" -ne 0 ] && ! { [ "$#" -eq 1 ] && [ "$1" = 0a ]; }; then
                echo 'LUN_ATTACHED_OR_UNKNOWN: eject Drive 1 cleanly on PC; inspect malformed state' >&2
                return 1
            fi
            printf 'file_empty=1\n'
        else
            if [ "$#" -lt 1 ] || [ "$#" -gt 2 ] || { [ "$#" -eq 2 ] && [ "$2" != 0a ]; }; then
                printf 'LUN_INVALID %s\n' "$attr" >&2; return 1
            fi
            case "$1" in 30) value=0;; 31) value=1;; *) printf 'LUN_INVALID %s\n' "$attr" >&2; return 1;; esac
            if [ "$attr" = removable ] && [ "$value" != 1 ]; then
                echo 'LUN_NOT_REMOVABLE' >&2
                return 1
            fi
            printf '%s=%s\n' "$attr" "$value"
        fi
    done
}
first=$(snapshot) || exit 1
second=$(snapshot) || exit 1
[ "$first" = "$second" ] || { echo 'LUN_CHANGED: hardware state unstable' >&2; exit 1; }
printf '%s\nLUN_READ_COMPLETE\n' "$first"
