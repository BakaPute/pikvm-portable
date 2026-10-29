#!/bin/bash
# Cible exclusivement PIKVM-SHARE : aucun GPIO, Drive 0 ou redemarrage KVMD.
set -eu
REPO="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$REPO/scripts/pikvm-share-install" "${@:-install}"
