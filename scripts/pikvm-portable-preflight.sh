#!/bin/bash
# Read-only gate; the installer uses the same supervisor and command budgets.
set -euo pipefail
export LC_ALL=C
HERE="$(cd -- "$(dirname -- "$0")" && pwd)"
exec /usr/bin/python3 -I -B "$HERE/pikvm_preflight.py"
