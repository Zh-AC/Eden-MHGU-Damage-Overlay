"""
Eden memory scanner for MHGU damage overlay.
Uses scanmodule C extension for AOB scanning.

Detection algorithm mirrors the proven MHGU-MHXX-HP-Overlay v1.1.8
reference implementation (modules/mhgu_xx.py):
  1. AOB scan for monster data entries
  2. Filter by known large-monster ID (at match + 0x7644)
  3. Filter by visibility flag (byte at hp_ptr - 0x17A0 != 0x07)
  4. Track HP continuously; every decrease is a damage event

No "wait for HP to drop" verification phase — a monster is accepted as
soon as its ID and visibility check out, so tracking starts immediately
when a quest loads.
"""

import ctypes
import ctypes.wintypes
import time as _time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Dict, Tuple

# Try to import scanmodule and numpy
_SCANMODULE = None
_NP = None

import sys, os
# scanmodule.pyd ships inside core/ next to this file (or in the
# PyInstaller bundle). Add this module's own directory to the import
# path so `import scanmodule` finds it — no machine-specific paths.
_core_dir = os.path.dirname(os.path.abspath(__file__))
if _core_dir not in sys.path:
    sys.path.insert(0, _core_dir)

if getattr(sys, 'frozen', False):
    _bundle_dir = os.path.join(sys._MEIPASS, 'core')
    if _bundle_dir not in sys.path:
        sys.path.insert(0, _bundle_dir)

try:
    import scanmodule as _scanmod
    _SCANMODULE = _scanmod
except ImportError:
    pass

try:
    import numpy as _numpy
    _NP = _numpy
except ImportError:
    pass

from .addresses import MONSTER_NAMES

# Windows API
kernel32 = ctypes.windll.kernel32
kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
kernel32.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
kernel32.CloseHandle.restype = ctypes.c_bool
kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
kernel32.ReadProcessMemory.restype = ctypes.c_bool
kernel32.ReadProcessMemory.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
kernel32.CreateToolhelp32Snapshot.restype = ctypes.wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.DWORD]
kernel32.Process32First.restype = ctypes.c_bool
kernel32.Process32First.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_void_p]
kernel32.Process32Next.restype = ctypes.c_bool
kernel32.Process32Next.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_void_p]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t
kernel32.VirtualQueryEx.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]

class PE(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.wintypes.DWORD), ("cntUsage", ctypes.wintypes.DWORD),
        ("th32ProcessID", ctypes.wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.wintypes.ULONG)),
        ("th32ModuleID", ctypes.wintypes.DWORD), ("cntThreads", ctypes.wintypes.DWORD),
        ("th32ParentProcessID", ctypes.wintypes.DWORD),
        ("pcPriClassBase", ctypes.wintypes.LONG), ("dwFlags", ctypes.wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]

class MBI(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", ctypes.wintypes.DWORD),
        ("PartitionId", ctypes.wintypes.WORD),
        ("RegionSize", ctypes.c_size_t), ("State", ctypes.wintypes.DWORD),
        ("Protect", ctypes.wintypes.DWORD), ("Type", ctypes.wintypes.DWORD),
    ]

# ── AOB pattern and offsets (identical to reference v1.1.8) ──────────

AOB_MONSTER_DATA = "?? ?? 01 ?? ?? 18 00 00 ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? 20 00 00 00 00 00 00 00"

# Offsets relative to AOB match position
OFF_HP_PTR   = 0x17A4   # current HP (u16)        -> scan_chunk result[1]
OFF_INIT_HP  = 0x17A8   # initial/max HP (u16)    -> scan_chunk result[2]
OFF_NAME     = 0x7644   # monster ID (u16)        -> scan_chunk result[0]
OFF_VISIBLE  = -0x17A0  # visibility byte (!= 0x07 means slot active)

# Candidate emulated-RAM region sizes (yuzu-family layout, same as reference)
REGION_SIZES = [0x9BBF000, 0x9BAE000, 0xDC11000]

# How far past the region base the AOB scan covers (same as reference)
SCAN_SIZE = 0xB000000   # ~176 MB

MIN_HP = 1
MAX_HP = 65535


def has_scanmodule():
    return _SCANMODULE is not None and _NP is not None


def find_eden_pid() -> Optional[int]:
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    if snapshot == -1 or snapshot == 0:
        return None
    entry = PE(); entry.dwSize = ctypes.sizeof(PE)
    if kernel32.Process32First(snapshot, ctypes.byref(entry)):
        while True:
            try:
                if entry.szExeFile.decode('utf-8', errors='ignore').lower() == 'eden.exe':
                    kernel32.CloseHandle(snapshot)
                    return entry.th32ProcessID
            except Exception:
                pass
            if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snapshot)
    return None


def open_process(pid: int) -> Optional[int]:
    if pid == 0:
        return None
    return kernel32.OpenProcess(0x10 | 0x0400 | 0x0008, False, pid)


# ── Memory read helpers ──────────────────────────────────────────────

def read_mem(handle: int, address: int, size: int) -> Optional[bytes]:
    buf = ctypes.create_string_buffer(size)
    br = ctypes.c_size_t(0)
    if kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address), buf, size, ctypes.byref(br)):
        return buf.raw[:br.value] if br.value != size else buf.raw
    return None


def read_u8(handle: int, address: int) -> Optional[int]:
    data = read_mem(handle, address, 1)
    return data[0] if data else None


def read_u16(handle: int, address: int) -> Optional[int]:
    data = read_mem(handle, address, 2)
    if data is None or len(data) < 2:
        return None  # partial read would decode as a wrong small value
    return int.from_bytes(data, 'little')


def read_hp(handle: int, address: int) -> Optional[int]:
    """Read current HP (u16) at a monster HP pointer."""
    return read_u16(handle, address)


def get_game_region(pid: int, process_name: str = 'eden.exe') -> Optional[int]:
    """Find the emulated-RAM region base by matching known region sizes."""
    if _SCANMODULE is None:
        return None
    for size in REGION_SIZES:
        try:
            base = _SCANMODULE.get_regions(process_name, size)
            if base and base > 0:
                print(f'[+] get_regions("{process_name}", 0x{size:X}) -> 0x{base:X}')
                return base
        except Exception as e:
            print(f'[-] get_regions("{process_name}", 0x{size:X}): {e}')
    return None


def list_large_regions(pid: int, min_size: int = 16 * 1024 * 1024) -> List[Tuple[int, int]]:
    """Diagnostic: list committed memory regions >= min_size (base, size)."""
    handle = open_process(pid)
    if not handle:
        return []
    regions = []
    addr = 0
    mbi = MBI()
    while kernel32.VirtualQueryEx(handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        base = mbi.BaseAddress or 0
        if mbi.State == 0x1000 and mbi.RegionSize >= min_size:  # MEM_COMMIT
            regions.append((base, mbi.RegionSize))
        addr = base + mbi.RegionSize
        if addr >= 0x7FFFFFFFFFFF:
            break
    kernel32.CloseHandle(handle)
    return regions


# ── Monster HP scan (reference algorithm) ────────────────────────────

def find_monster_hp(handle: int, game_base: int) -> List[int]:
    """
    AOB-scan for monster data entries and return HP pointers of all
    visible large monsters (matching reference v1.1.8 logic).
    """
    if not has_scanmodule():
        print("[!] scanmodule/numpy not available")
        return []

    parts = AOB_MONSTER_DATA.split()
    pbytes = bytes(int(p, 16) if p != '??' else 0 for p in parts)
    mbytes = bytes(0 if p == '??' else 0xFF for p in parts)
    pattern_np = _NP.frombuffer(pbytes, dtype=_NP.uint8)
    mask_np = _NP.frombuffer(mbytes, dtype=_NP.uint8)
    plen = len(pattern_np)

    num_chunks = 400
    chunk_size = SCAN_SIZE // num_chunks

    def _scan_one(i):
        off = i * chunk_size
        # read plen-1 extra bytes so matches at the chunk edge are caught
        data = read_mem(handle, game_base + off, chunk_size + plen - 1)
        if not data or len(data) < plen:
            return []
        return _SCANMODULE.scan_chunk(data, pattern_np, mask_np, game_base, off)

    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        for chunk_results in executor.map(_scan_one, range(num_chunks)):
            if chunk_results:
                results.extend(chunk_results)

    print(f'[+] AOB scan: {len(results)} raw matches')

    # Phase 1 filter: known monster ID + visible slot + sane HP
    candidates: Dict[int, Tuple[int, int, int]] = {}
    for r in results:
        if len(r) < 3:
            continue
        name_addr, hp_ptr, init_addr = r[0], r[1], r[2]
        if hp_ptr in candidates:
            continue
        monster_id = read_u16(handle, name_addr)
        if monster_id not in MONSTER_NAMES:
            continue
        hp = read_u16(handle, hp_ptr)
        init_hp = read_u16(handle, init_addr)
        if not hp or not init_hp:
            continue
        if not (MIN_HP <= hp <= MAX_HP) or init_hp > 40000:
            continue
        if hp > init_hp:
            continue
        vis = read_u8(handle, hp_ptr + OFF_VISIBLE)
        visible = (vis != 0x7) or hp != 0
        if not visible:
            continue
        candidates[hp_ptr] = (monster_id, hp, init_hp)

    print(f'[+] Phase1 candidates: {len(candidates)}')
    if not candidates:
        return []

    # Phase 2 stability check: real monster HP is static between hits and
    # the ID/init fields never change. Garbage matches fluctuate constantly.
    # (No damage required — unchanged HP is accepted.)
    _time.sleep(0.4)
    found: Dict[int, Tuple[int, int, int]] = {}
    for hp_ptr, (monster_id, hp1, init_hp) in candidates.items():
        id2 = read_u16(handle, hp_ptr - OFF_HP_PTR + OFF_NAME)
        hp2 = read_u16(handle, hp_ptr)
        init2 = read_u16(handle, hp_ptr - OFF_HP_PTR + OFF_INIT_HP)
        if id2 != monster_id or init2 != init_hp or hp2 is None:
            continue
        if not (-500 <= hp2 - hp1 <= 5000):
            continue
        found[hp_ptr] = (monster_id, hp2, init_hp)
        print(f'  monster: id={monster_id} hp={hp2}/{init_hp} ptr=0x{hp_ptr:X}')

    print(f'[+] Verified monsters: {len(found)}')
    return list(found.keys())


def describe_monster(handle: int, hp_ptr: int) -> Optional[Tuple[int, int, int]]:
    """Return (monster_id, hp, initial_hp) for a HP pointer, or None."""
    monster_id = read_u16(handle, hp_ptr - OFF_HP_PTR + OFF_NAME)
    hp = read_u16(handle, hp_ptr)
    init_hp = read_u16(handle, hp_ptr - OFF_HP_PTR + OFF_INIT_HP)
    if monster_id is None or hp is None or init_hp is None:
        return None
    return (monster_id, hp, init_hp)


class EdenMonsterTracker:
    """Tracks monster HP and detects damage events."""

    def __init__(self, process_handle: int):
        self.handle = process_handle
        self.monsters: Dict[int, dict] = {}
        self.damage_events: List[Tuple[int, float]] = []
        self._next_id = 0

    def add_monster(self, hp_address: int):
        hp = read_hp(self.handle, hp_address)
        if hp is None or hp <= 0:
            return
        init_hp = read_u16(self.handle, hp_address - OFF_HP_PTR + OFF_INIT_HP) or hp
        mid = read_u16(self.handle, hp_address - OFF_HP_PTR + OFF_NAME)
        max_hp = max(hp, init_hp)
        self.monsters[hp_address] = {
            'hp': hp, 'max_hp': max_hp, 'init_hp': max_hp,
            'prev_hp': hp, 'id': self._next_id, 'mid': mid,
            'bad_reads': 0,
        }
        self._next_id += 1

    def update(self) -> List[Tuple[int, int]]:
        """Poll monster HP; return damage events as (damage, monster_id).

        monster_id is None when unreadable; callers fall back to large.

        Address-identity guards: on area transition / map load the game
        recycles monster memory, so the address can point at a different
        monster (or garbage). We re-read the monster id AND the max HP
        every poll: a different id, or a different max HP in the same slot
        (an area change can slot in another monster of the same species),
        means the "HP drop" is not a damage event - the slot is dropped or
        re-seeded. The killing blow is only emitted when HP hits exactly 0
        AND the id still matches (a real death)."""
        damages = []
        for addr, info in list(self.monsters.items()):
            hp = read_hp(self.handle, addr)
            if hp is None:
                continue
            mid = read_u16(self.handle, addr - OFF_HP_PTR + OFF_NAME)
            init_hp = read_u16(self.handle, addr - OFF_HP_PTR + OFF_INIT_HP)

            # Identity mismatch: address recycled into another monster
            # (area transition, quest reload). Never a damage event.
            if mid is not None and info['mid'] is not None and mid != info['mid']:
                del self.monsters[addr]
                continue

            # Slot reloaded with a different monster: max HP differs from
            # the one we recorded (an area change can slot in another
            # monster of the same species, so the id check above doesn't
            # always fire). Re-seed this slot instead of counting the HP
            # difference as damage - that's how "26"-style false numbers
            # on area change get through.
            if init_hp is not None and init_hp != info['init_hp']:
                info['init_hp'] = init_hp
                info['max_hp'] = max(hp, init_hp)
                info['prev_hp'] = hp
                info['hp'] = hp
                info['bad_reads'] = 0
                continue

            # Real monster HP can never exceed its quest max (init_hp).
            # Anything above it means the address was recycled into garbage.
            if hp <= 0 or hp > info['init_hp']:
                # Emit the killing blow only for a real death: HP exactly 0
                # and the monster id still readable and unchanged. During
                # scene reloads the id is often unreadable (None) - skip.
                if hp == 0 and info['bad_reads'] == 0 \
                        and mid is not None and mid == info['mid']:
                    delta = info['hp']
                    if 0 < delta <= 5000:
                        damages.append((delta, info['mid']))
                        self.damage_events.append((delta, _time.time()))
                # Tolerate transient bad reads (area transitions, state
                # changes can briefly zero/spike the HP field). Only drop
                # the address after ~1s of consistently invalid values.
                info['bad_reads'] += 1
                if info['bad_reads'] >= 20:
                    del self.monsters[addr]
                continue
            info['bad_reads'] = 0
            if hp > info['max_hp']:
                info['max_hp'] = hp
            info['prev_hp'] = info['hp']
            info['hp'] = hp
            delta = info['prev_hp'] - info['hp']
            if 0 < delta <= 5000 and delta < info['max_hp']:
                damages.append((delta, info['mid']))
                self.damage_events.append((delta, _time.time()))
        return damages

    def cleanup_old_damage(self, max_age: float = 10.0):
        now = _time.time()
        self.damage_events = [(d, t) for d, t in self.damage_events if now - t < max_age]

    @property
    def monster_count(self) -> int:
        return len(self.monsters)

    def get_monster_hp_list(self) -> List[Tuple[int, int]]:
        return [(info['hp'], info['max_hp']) for info in self.monsters.values()]
