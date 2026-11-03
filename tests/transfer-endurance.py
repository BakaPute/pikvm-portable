"""Bounded synthetic endurance run in a private TemporaryDirectory only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import pikvm_transfer as transfer


def exercise(cycles):
    started, cpu = time.perf_counter(), time.process_time()
    tracemalloc.start()
    descriptors = len(list(Path('/proc/self/fd').iterdir())) if Path('/proc/self/fd').exists() else None
    payload = bytes(range(256)) * 4096
    expected = hashlib.sha256(payload).hexdigest()
    with tempfile.TemporaryDirectory(prefix='portable-synthetic-endurance-') as directory:
        root = Path(directory)
        src, dest = root / 'source', root / 'destination'
        src.mkdir()
        dest.mkdir()
        for index in range(cycles):
            source = src / f'synthetic {index}.iso'
            target = dest / source.name
            source.write_bytes(payload)
            transfer.ImportJournal(dest).copy(source, target)
            # Repeated finalize after a lost HTTP response must add no duplicate.
            transfer.ImportJournal(dest).copy(source, target)
            assert transfer.digest(target) == expected
        assert len(list(dest.glob('*.iso'))) == cycles
        assert not list(dest.glob('.__usbimport-*.part'))
        journal_bytes = (dest / transfer.JOURNAL.name).stat().st_size
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    after = len(list(Path('/proc/self/fd').iterdir())) if descriptors is not None else None
    assert after is None or after <= descriptors
    return {'environment': 'local synthetic, NOT Raspberry Pi', 'python': sys.version.split()[0],
            'platform': sys.platform, 'cycles': cycles, 'bytes_per_file': len(payload),
            'copied_bytes': cycles * len(payload), 'repeat_finalize': cycles,
            'wall_seconds': round(time.perf_counter()-started, 3),
            'cpu_seconds': round(time.process_time()-cpu, 3), 'peak_python_heap_bytes': peak,
            'descriptors_before': descriptors, 'descriptors_after': after,
            'journal_bytes': journal_bytes, 'result': 'passed'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycles', type=int, default=64)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 1 <= args.cycles <= 128:
        parser.error('1–128 cycles only; never use a user storage path')
    text = json.dumps(exercise(args.cycles), indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text)
