#!/bin/bash
# Passive only: no GPIO writes, service changes, USB actions or image mutation.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
date -Iseconds
uname -r
pacman -Q python kvmd
pinctrl get 17
pinctrl get 18
for i in 0 1; do
    printf 'Drive %s: ' "$i"
    cat "/sys/kernel/config/usb_gadget/kvmd/functions/mass_storage.usb$i/lun.0/file"
done
systemctl show --property=ActiveState,NRestarts,MainPID pikvm-button-menu.service pikvm-oled-custom.service pikvm-power-hold.service kvmd.service kvmd-nginx.service
PYTHONPATH="$repo/scripts" python3 -B "$repo/scripts/pikvm-oled-benchmark.py" --iterations 30
python3 -B "$repo/scripts/pikvm-portable-perf" --duration 30 --interval 10 --no-threads --label rc12-passive
python3 -B - <<'PY'
import json
from pathlib import Path
for name in ('button','frame'):
    path=Path('/run/pikvm-oled')/(name+'.json')
    if not path.is_symlink() and path.stat().st_size<16384:
        data=json.loads(path.read_text())
        print(name,json.dumps({k:v for k,v in data.items() if k not in ('pixels','id','control_id','context')}))
PY
