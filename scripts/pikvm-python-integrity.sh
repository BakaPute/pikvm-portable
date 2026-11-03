#!/bin/bash
# Bootstrap without Python: diagnose the observed copyreg/logging corruption
# before Python's own imports can fail. No repair, cache deletion or package update.
set -euo pipefail
export LC_ALL=C
mtree=/var/lib/pacman/local/python-3.14.7-1/mtree
for member in usr/lib/python3.14/copyreg.py usr/lib/python3.14/logging/__init__.py; do
    printf '%s integrity START %s\n' "$(date -u +%FT%TZ)" "$member" >&2
    [[ -f "/$member" && ! -L "/$member" && -f "$mtree" ]] || { echo 'Integrity metadata/file missing' >&2; exit 1; }
    expected=$(timeout -k 1 10 gzip -dc "$mtree" | timeout -k 1 10 awk -v file="./$member" '$1 == file {for(i=2;i<=NF;i++) if($i ~ /^sha256digest=/) {sub(/^sha256digest=/,"",$i); print $i}}')
    [[ "$expected" =~ ^[0-9a-f]{64}$ ]] || { echo 'Invalid official package baseline' >&2; exit 1; }
    for sample in 1 2; do
        actual=$(timeout -k 1 10 sha256sum "/$member")
        [[ "${actual%% *}" == "$expected" ]] || { printf 'Integrity FAIL %s sample=%s actual=%s\n' "$member" "$sample" "${actual%% *}" >&2; exit 1; }
    done
    printf '%s integrity OK %s\n' "$(date -u +%FT%TZ)" "$member" >&2
done
