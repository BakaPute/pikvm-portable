#!/bin/bash
# Targeted repair from an authenticated, exact package. NEVER downloads/upgrades.
# Does not depend on Python. inspect is non-destructive; apply requires permission.
set -euo pipefail
umask 077
export LC_ALL=C
TARGET=/usr/lib/python3.14/logging/__init__.py
MEMBER=usr/lib/python3.14/logging/__init__.py
VERSION=3.14.7-1
DB=/var/lib/pacman/local/python-3.14.7-1
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
field() { awk -v key="$1" '$0 == "%" key "%" {getline; print; exit}' "$DB/desc"; }
mtree_hash() { gzip -dc "$1" | awk -v file="./${2:-$MEMBER}" '$1 == file {for(i=2;i<=NF;i++) if($i ~ /^sha256digest=/) {sub(/^sha256digest=/,"",$i); print $i}}'; }
action=${1:-}
archive=${2:-}
[[ "$action" == inspect || "$action" == apply ]] || fail 'Usage: inspect|apply PACKAGE [--authorized]'
for tool in pacman pacman-key bsdtar gzip awk sha256sum realpath; do
    command -v "$tool" >/dev/null || fail "Required tool unavailable: $tool"
done
[[ -f "$archive" && ! -L "$archive" && -f "$archive.sig" ]] || fail 'Package and detached .sig required.'
[[ "$(pacman -Q python)" == "python $VERSION" ]] || fail 'Installed version is not exactly python 3.14.7-1.'
[[ -f "$DB/desc" && -f "$DB/mtree" ]] || fail 'Installed pacman metadata unavailable.'
[[ -f "$TARGET" && ! -L "$TARGET" && "$(realpath -- "$TARGET")" == "$TARGET" ]] || fail 'Unexpected logging path.'
expected_arch=$(field ARCH)
[[ "$expected_arch" == armv7h || "$expected_arch" == aarch64 ]] || fail 'Unsupported or unknown installed architecture.'
# Existing trusted keyring only. Never import keys, change trust or disable checks.
pacman-key --verify "$archive.sig" "$archive" || fail 'Official package signature verification failed; STOP.'
stage=$(mktemp -d)
temp=''
cleanup() { [[ -z "$temp" ]] || rm -f -- "$temp"; rm -rf -- "$stage"; }
trap cleanup EXIT
bsdtar -xOf "$archive" .PKGINFO > "$stage/PKGINFO"
grep -Fqx 'pkgname = python' "$stage/PKGINFO" || fail 'Wrong package name.'
grep -Fqx "pkgver = $VERSION" "$stage/PKGINFO" || fail 'Wrong package release.'
grep -Fqx "arch = $expected_arch" "$stage/PKGINFO" || fail 'Wrong architecture.'
bsdtar -xOf "$archive" .MTREE > "$stage/mtree"
expected=$(mtree_hash "$DB/mtree")
packaged=$(mtree_hash "$stage/mtree")
[[ "$expected" =~ ^[0-9a-f]{64}$ && "$expected" == "$packaged" ]] || fail 'Package hash does not match installed pacman baseline.'
# Extract ONLY the fixed, signed member; preserve its packaged timestamp.
bsdtar -xpf "$archive" -C "$stage" --no-same-owner -- "$MEMBER"
candidate="$stage/$MEMBER"
[[ -f "$candidate" && ! -L "$candidate" ]] || fail 'Package member is not an ordinary file.'
[[ "$(sha256sum "$candidate" | cut -d' ' -f1)" == "$expected" ]] || fail 'Extracted member checksum mismatch.'
printf 'Verified: python %s, %s, logging SHA256 %s\n' "$VERSION" "$expected_arch" "$expected"
# Package-owned bytecode can be healthy even though the source was damaged.
# Never remove tracked .pyc files: verify them against the installed baseline.
untracked=()
for cached in "$(dirname "$TARGET")"/__pycache__/__init__.cpython-314*.pyc; do
    [[ -e "$cached" ]] || continue
    [[ -f "$cached" && ! -L "$cached" ]] || fail 'Unexpected cached bytecode.'
    cached_hash=$(mtree_hash "$DB/mtree" "usr/lib/python3.14/logging/__pycache__/$(basename "$cached")")
    if [[ -n "$cached_hash" ]]; then
        [[ "$(sha256sum "$cached" | cut -d' ' -f1)" == "$cached_hash" ]] || fail 'Additional damaged package-owned bytecode; STOP.'
    else
        untracked+=("$cached")
    fi
done
if [[ "$action" == inspect ]]; then
    printf 'Current SHA256: '; sha256sum "$TARGET"
    printf 'Inspection complete. No system file or service changed.\n'
    exit 0
fi
[[ ${3:-} == --authorized && $EUID -eq 0 ]] || fail 'apply requires root and --authorized AFTER explicit user approval.'
[[ -w "$(dirname "$TARGET")" ]] || fail 'System is read-only; do not change it without authorization.'
backup="/root/pikvm-python-repair-backups/$(date +%Y%m%d-%H%M%S)-$$"
mkdir -m 700 -p "$backup/cache"
cp -a -- "$TARGET" "$backup/__init__.py.before"
sha256sum "$TARGET" > "$backup/before.sha256"
printf '%s\n' "$expected" > "$backup/expected.sha256"
cp -a -- "$DB/desc" "$backup/installed.desc"
sha256sum "$archive" > "$backup/package.sha256"
printf 'Backup: %s\n' "$backup"
temp=$(mktemp "$(dirname "$TARGET")/.logging-repair.XXXXXXXX")
cp -p -- "$candidate" "$temp"
chmod --reference="$TARGET" "$temp"
chown --reference="$TARGET" "$temp"
# Quarantine only untracked logging bytecode; leave verified packaged caches intact.
for cached in "${untracked[@]}"; do
    mv -- "$cached" "$backup/cache/"
done
mv -f -- "$temp" "$TARGET"
temp=''
sync -f "$TARGET"
[[ "$(sha256sum "$TARGET" | cut -d' ' -f1)" == "$expected" ]] || fail 'Post-write hash mismatch. Backup preserved; manual investigation required.'
/usr/bin/python3 -I -B -c 'import logging, asyncio, ssl; logging.getLogger("repair-check").addHandler(logging.NullHandler()); assert hasattr(logging, "FileHandler"); print("logging / asyncio / ssl: OK")'
pacman -Qkk python
printf 'Targeted repair verified. No package upgrade, KVMD restart, GPIO or USB operation performed.\n'
