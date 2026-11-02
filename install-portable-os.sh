#!/bin/bash
set -eu
REPO="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$REPO/scripts/pikvm-portable-install" "${@:-install}"
