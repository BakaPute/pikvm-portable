#!/bin/bash
set -eu
REPO="$(cd "$(dirname "$0")" && pwd)"
if [ "${1:-install}" != restore ]; then
    bash "$REPO/scripts/pikvm-python-integrity.sh"
fi
exec python3 "$REPO/scripts/pikvm-portable-install" "${@:-install}"
