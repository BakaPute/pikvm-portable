#!/bin/bash
# Read-only compatibility gate; do not repair/update anything here.
set -euo pipefail
export LC_ALL=C
fail() { printf 'PRECHECK FAILED: %s\n' "$*" >&2; exit 1; }
python_package=$(pacman -Q python) || fail 'Python package unavailable.'
kvmd_package=$(pacman -Q kvmd) || fail 'KVMD package unavailable.'
[[ "$python_package" == 'python 3.14.7-1' ]] || fail 'Candidate targets exactly Python 3.14.7-1; manual compatibility review required.'
[[ "$kvmd_package" == kvmd\ 4.213-* || "$kvmd_package" == 'kvmd 4.213' ]] || fail 'Candidate targets KVMD 4.213.'
db=/var/lib/pacman/local/python-3.14.7-1
target=/usr/lib/python3.14/logging/__init__.py
[[ -f "$target" && ! -L "$target" && -f "$db/mtree" ]] || fail 'logging or package metadata unavailable.'
expected=$(gzip -dc "$db/mtree" | awk '$1 == "./usr/lib/python3.14/logging/__init__.py" {for(i=2;i<=NF;i++) if($i ~ /^sha256digest=/) {sub(/^sha256digest=/,"",$i); print $i}}')
[[ "$expected" =~ ^[0-9a-f]{64}$ ]] || fail 'logging baseline hash unavailable.'
[[ "$(sha256sum "$target" | cut -d' ' -f1)" == "$expected" ]] || fail 'logging checksum mismatch: repair before migration.'
/usr/bin/python3 -I -B -c 'import sys,logging,asyncio,ssl,aiohttp,mako,kvmd; assert sys.version_info[:2] == (3,14); assert kvmd.__version__ == "4.213"; assert hasattr(logging,"FileHandler")' || fail 'Python / KVMD imports failed.'
kvmd-otgmsd -i 1 >/dev/null 2>&1 || fail 'Drive 1 read-only command failed; no migration attempted.'
nginx -t -p /etc/kvmd/nginx -c /run/kvmd/nginx.conf -g 'pid /run/kvmd/nginx.pid; user kvmd-nginx; error_log stderr;' || fail 'Current nginx configuration invalid.'
for service in kvmd.service kvmd-nginx.service; do
    systemctl is-active --quiet "$service" || fail "$service inactive."
done
printf 'Compatibility: Python 3.14.7-1, logging integrity, KVMD 4.213, Drive 1 read, nginx: OK.\n'
