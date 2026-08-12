# -*- coding: utf-8 -*-
"""Coordinate hunt: look for monster world-position float3s near the
monster data block in eden's memory.

Method
------
1. Find monster HP pointers with the project's proven AOB scan.
2. Dump a memory window around each monster's AOB match address.
3. Take several snapshots a few seconds apart while the monster moves.
4. Diff the snapshots: a world position is 3 consecutive float32s that
   - stay finite and in a plausible world range (|v| < 200000),
   - change by small, smooth amounts while the monster moves
     (not random garbage, which jumps wildly),
   - mostly move in X/Z (Y = height changes less on flat ground).

Usage
-----
    python dev/tools/coord_hunt.py            # 3 snapshots, 4s apart
    python dev/tools/coord_hunt.py 6 3        # 6 snapshots, 3s apart

Best results: be in a quest with the monster ACTIVE (walking around),
do NOT kill it, keep the camera still (camera moves pollute nothing
here - we only diff the monster block, but monster movement is what
makes position values change).

Output: top candidate offsets with their values per snapshot, so a
human can judge which one is the real (x, y, z).
"""

import os
import struct
import sys
import time

_root = os.path.dirname(os.path.abspath(__file__))
while _root and not os.path.isdir(os.path.join(_root, 'core')):
    _root = os.path.dirname(_root)
sys.path.insert(0, _root)

from core import scanner_eden as se

SNAPSHOTS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
INTERVAL = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0

# Window around the AOB match to inspect (match = hp_ptr - OFF_HP_PTR).
# The position may live before or after the scanned status block.
PRE = 0x8000
POST = 0x8000

MAX_WORLD = 200000.0      # |coord| above this is not a world position
MIN_MOVE = 0.05           # smaller deltas = noise / not moving
MAX_MOVE = 500.0          # per-interval delta above this = garbage/teleport data


def f32_list(data: bytes):
    n = len(data) // 4
    return list(struct.unpack('<%df' % n, data[: n * 4]))


def plausible(v: float) -> bool:
    return v == v and abs(v) < MAX_WORLD and v not in (0.0,)


def main():
    pid = se.find_eden_pid()
    if not pid:
        print('[!] eden.exe not running')
        return 1
    handle = se.open_process(pid)
    if not handle:
        print('[!] cannot open eden.exe (try admin)')
        return 1
    base = se.get_game_region(pid)
    if not base:
        print('[!] game region not found - is MHGU loaded?')
        return 1

    hp_ptrs = se.find_monster_hp(handle, base)
    if not hp_ptrs:
        print('[!] no monsters found - get into a quest first')
        return 1
    print(f'[+] {len(hp_ptrs)} monster(s)')

    # Use the first monster (usually the large target monster)
    hp_ptr = hp_ptrs[0]
    match = hp_ptr - se.OFF_HP_PTR
    desc = se.describe_monster(handle, hp_ptr)
    print(f'[+] monster id={desc[0] if desc else "?"}  match=0x{match:X}')
    lo, hi = match - PRE, match + POST

    snaps = []
    for i in range(SNAPSHOTS):
        data = se.read_mem(handle, lo, hi - lo)
        if not data or len(data) < (hi - lo) // 2:
            print(f'[!] snapshot {i}: short read ({0 if not data else len(data)} bytes)')
            return 1
        snaps.append(f32_list(data))
        print(f'[+] snapshot {i} taken ({len(data)} bytes)')
        if i + 1 < SNAPSHOTS:
            time.sleep(INTERVAL)

    # Score every float3 (4-byte aligned) by "moves like a position"
    cands = []
    n = len(snaps[0]) - 2
    for k in range(n):
        tri = [(s[k], s[k + 1], s[k + 2]) for s in snaps]
        if not all(plausible(v) for t in tri for v in t):
            continue
        # deltas between consecutive snapshots, per component
        deltas = [[abs(t[j + 1][c] - t[j][c]) for c in range(3)]
                  for j in range(len(tri) - 1)]
        moved = [sum(1 for d in ds if MIN_MOVE < d < MAX_MOVE) for ds in deltas]
        # a position candidate: at least 2 components moved smoothly at least once
        if not any(m >= 2 for m in moved):
            continue
        # reject wild jumps: no delta may exceed MAX_MOVE
        if any(d >= MAX_MOVE for ds in deltas for d in ds):
            continue
        # X/Z-move bias: horizontal movement dominates on foot monsters
        xz = sum(ds[0] + ds[2] for ds in deltas)
        cands.append((xz, k * 4 - PRE, tri))  # offset relative to AOB match

    cands.sort(key=lambda c: -c[0])
    print(f'\n[+] {len(cands)} position-like float3 candidates (top 15):')
    for xz, off, tri in cands[:15]:
        print(f'  off {off:+#07x} (abs 0x{match + off:X}) xzmove={xz:9.2f}')
        for i, t in enumerate(tri):
            print(f'      snap{i}: ({t[0]:12.2f}, {t[1]:12.2f}, {t[2]:12.2f})')
    if not cands:
        print('  none - monster may not have moved; retry with more movement')
    return 0


if __name__ == '__main__':
    sys.exit(main())
