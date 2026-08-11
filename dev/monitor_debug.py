"""Diagnostic monitor: plugin-identical tracking, 180 seconds."""
import sys, time
sys.path.insert(0, '.')
from core.scanner_eden import (
    find_eden_pid, open_process, get_game_region, find_monster_hp,
    describe_monster, EdenMonsterTracker, kernel32,
)
from core.addresses import MONSTER_NAMES

DURATION = 180

pid = find_eden_pid()
h = open_process(pid)
base = get_game_region(pid)
print('pid=%d base=0x%X' % (pid, base), flush=True)

tracker = EdenMonsterTracker(h)

def tag_addr(a):
    info = describe_monster(h, a)
    if info:
        mid, hp, init = info
        return 'id=%s(%s) hp=%s/%s' % (mid, MONSTER_NAMES.get(mid, '?'), hp, init)
    return 'unreadable'

def rescan(tag):
    before = set(tracker.monsters)
    addrs = find_monster_hp(h, base)
    for a in addrs:
        if a not in tracker.monsters:
            print('[%s] +TRACK 0x%X  %s' % (tag, a, tag_addr(a)), flush=True)
            tracker.add_monster(a)

rescan('init')
t0 = time.time()
last_rescan = t0
while time.time() - t0 < DURATION:
    now = time.time() - t0
    before = set(tracker.monsters)
    hps = {a: dict(info) for a, info in tracker.monsters.items()}
    dmgs = tracker.update()
    after = set(tracker.monsters)
    for a in before - after:
        print('[%.1fs] -DROP 0x%X (last hp=%s)' % (now, a, hps[a]['hp']), flush=True)
    if dmgs:
        for d, mid in dmgs:
            cur = ', '.join('0x%X:%d' % (a, i['hp']) for a, i in tracker.monsters.items())
            print('[%.1fs] DAMAGE %d (mid=%s)   [%s]' % (now, d, mid, cur), flush=True)
    if time.time() - last_rescan > 5:
        last_rescan = time.time()
        rescan('%.0fs' % (time.time() - t0))
    time.sleep(0.05)

print('monitor done', flush=True)
kernel32.CloseHandle(h)
