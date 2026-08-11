"""Verification for the area-transition fix (#15).

Mocks read_hp/read_u16 to replay the exact memory sequences that happen
during real play, and asserts the tracker only emits real damage events.
Run: python dev/tools/test_tracker_fix.py
"""

import sys, os
# Walk up from this file until we find the project root (contains core/)
_root = os.path.dirname(os.path.abspath(__file__))
while _root and not os.path.isdir(os.path.join(_root, 'core')):
    _root = os.path.dirname(_root)
sys.path.insert(0, _root)

import core.scanner_eden as se
from core.scanner_eden import EdenMonsterTracker, OFF_HP_PTR, OFF_INIT_HP, OFF_NAME

FAILED = []
def check(name, cond, detail=''):
    mark = 'PASS' if cond else 'FAIL'
    print(f'  [{mark}] {name} {detail}')
    if not cond:
        FAILED.append(name)


class FakeMem:
    """Replay table: addr -> value. read_u16 returns values stored at the
    OFF_NAME offset when present, else the current monster id."""
    def __init__(self):
        self.vals = {}
        self.mid = 3
    def read_hp(self, handle, addr):
        return self.vals.get(addr)
    def read_u16(self, handle, addr):
        v = self.vals.get(addr)
        if v is not None:
            return v
        if addr == 0:  # init_hp offset register
            return self.init_hp
        return self.mid

# patch module-level readers
se.read_hp = lambda h, a: mem.read_hp(h, a)
se.read_u16 = lambda h, a: mem.read_u16(h, a)

ADDR = 0x10000
NAME_OFF = ADDR - OFF_HP_PTR + OFF_NAME
INIT_OFF = ADDR - OFF_HP_PTR + OFF_INIT_HP


def fresh_tracker(init_hp, hp, mid):
    global mem
    mem = FakeMem()
    mem.mid = mid
    mem.init_hp = init_hp
    mem.vals[ADDR] = hp
    mem.vals[INIT_OFF] = init_hp
    mem.vals[NAME_OFF] = mid
    t = EdenMonsterTracker(0)
    t.add_monster(ADDR)
    return t


print('== 1. 正常掉血: 同一只怪 1000->900, 应发伤害 100 ==')
t = fresh_tracker(1000, 1000, 3)
mem.vals[ADDR] = 900
d = t.update()
check(len(d) == 1 and d[0][0] == 100 and d[0][1] == 3, f'got {d}')

print('== 2. 换区复用: mid 3->17, 不发任何伤害, 地址立即移除 ==')
t = fresh_tracker(1000, 900, 3)
mem.mid = 17
mem.vals[NAME_OFF] = 17
mem.vals[ADDR] = 800   # "新怪" 的 HP, 差值 100 很像伤害
d = t.update()
check(d == [], f'got {d}')
check(ADDR not in t.monsters, '地址已移除')

print('== 3. 真实击杀: HP 归零且 mid 一致, 发最后一击 ==')
t = fresh_tracker(1000, 100, 3)
mem.vals[ADDR] = 0
d = t.update()
check(len(d) == 1 and d[0][0] == 100, f'got {d}')

print('== 4. 换区加载中: HP 归零但 mid 读不到(None), 不发 ==')
t = fresh_tracker(1000, 500, 3)
mem.mid = None
del mem.vals[NAME_OFF]
mem.vals[ADDR] = 0
d = t.update()
check(d == [], f'got {d}')

print('== 5. 换区后新怪满血: HP 高于旧怪(不满足 delta>0), 不发 ==')
t = fresh_tracker(6000, 500, 3)   # 旧怪剩 500
mem.mid = 17
mem.vals[NAME_OFF] = 17
mem.vals[ADDR] = 6000             # 新怪满血
d = t.update()
check(d == [], f'got {d}')
check(ADDR not in t.monsters, '地址已移除')

print('== 6. 换区后新怪低血: HP 差值像伤害但 mid 变了, 不发 ==')
t = fresh_tracker(6000, 6000, 3)
mem.mid = 42
mem.vals[NAME_OFF] = 42
mem.vals[ADDR] = 5500             # 差值 500, 看起来像伤害
d = t.update()
check(d == [], f'got {d}')
check(ADDR not in t.monsters, '地址已移除')

print('== 7. 连续多轮掉血: 正常伤害流 ==')
t = fresh_tracker(6000, 6000, 3)
for hp in (5900, 5800, 5700):
    mem.vals[ADDR] = hp
    d = t.update()
    check(len(d) == 1 and d[0][0] == 100, f'hp={hp} got {d}')

print()
if FAILED:
    print(f'{len(FAILED)} FAILED: {FAILED}')
    sys.exit(1)
print('ALL TRACKER TESTS PASSED')
