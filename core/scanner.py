"""
Memory scanner for Eden Switch Emulator.
Uses AOB (Array of Bytes) scanning and value-based search to locate
monster HP values in the emulator's process memory.

Works with eden.exe and other Switch emulators (Ryujinx, Yuzu, Sudachi, Suyu).
"""

import ctypes
import ctypes.wintypes
import struct
import time
import threading
from typing import Optional, List, Tuple, Dict
from dataclasses import dataclass, field

# Windows API constants
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_OPERATION = 0x0008
PAGE_READWRITE = 0x04
MEM_COMMIT = 0x1000
MEM_MAPPED = 0x40000
MEM_PRIVATE = 0x20000
TH32CS_SNAPPROCESS = 0x00000002

# Windows API functions via ctypes
kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi
user32 = ctypes.windll.user32

# ── Set ctypes function signatures (64-bit safe) ───────────────────

kernel32.CreateToolhelp32Snapshot.restype = ctypes.wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.DWORD]

kernel32.Process32First.restype = ctypes.c_bool
kernel32.Process32First.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_void_p]

kernel32.Process32Next.restype = ctypes.c_bool
kernel32.Process32Next.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_void_p]

kernel32.CloseHandle.restype = ctypes.c_bool
kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]

kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
kernel32.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]

kernel32.ReadProcessMemory.restype = ctypes.c_bool
kernel32.ReadProcessMemory.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]

kernel32.VirtualQueryEx.restype = ctypes.c_size_t
kernel32.VirtualQueryEx.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.c_size_t]

user32.IsWindowVisible.restype = ctypes.c_bool
user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]

user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [ctypes.wintypes.HWND]

user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [ctypes.wintypes.HWND, ctypes.c_void_p, ctypes.c_int]

user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [ctypes.wintypes.HWND, ctypes.c_void_p]

user32.EnumWindows.restype = ctypes.c_bool
user32.EnumWindows.argtypes = [ctypes.c_void_p, ctypes.wintypes.LPARAM]

# Callback type for EnumWindows
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

# Struct definitions
class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", ctypes.wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", ctypes.wintypes.DWORD),
        ("Protect", ctypes.wintypes.DWORD),
        ("Type", ctypes.wintypes.DWORD),
    ]


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.wintypes.DWORD),
        ("cntUsage", ctypes.wintypes.DWORD),
        ("th32ProcessID", ctypes.wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.wintypes.ULONG)),
        ("th32ModuleID", ctypes.wintypes.DWORD),
        ("cntThreads", ctypes.wintypes.DWORD),
        ("th32ParentProcessID", ctypes.wintypes.DWORD),
        ("pcPriClassBase", ctypes.wintypes.LONG),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


@dataclass
class MemoryRegion:
    """Represents a readable memory region in the target process."""
    base_address: int
    size: int
    state: int
    protect: int
    type: int


@dataclass
class MonsterInfo:
    """Information about a tracked monster."""
    monster_id: int
    hp_address: int
    current_hp: int
    max_hp: int
    previous_hp: int = 0
    last_damage: int = 0
    last_update_time: float = 0.0


@dataclass
class DamageEvent:
    """A damage event to be displayed as a floating number."""
    monster_id: int
    damage: int
    spawn_time: float
    screen_x: int = 0
    screen_y: int = 0


class ProcessManager:
    """Manages process discovery and attachment."""

    @staticmethod
    def find_process_by_name(name: str) -> Optional[int]:
        """Find a process by its executable name. Returns PID or None."""
        name_lower = name.lower()
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == -1 or snapshot == 0:
            return None

        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)

        if kernel32.Process32First(snapshot, ctypes.byref(entry)):
            while True:
                try:
                    exe_name = entry.szExeFile.decode('utf-8', errors='ignore').lower()
                except Exception:
                    exe_name = ''
                if exe_name == name_lower:
                    kernel32.CloseHandle(snapshot)
                    return entry.th32ProcessID
                if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                    break

        kernel32.CloseHandle(snapshot)
        return None

    @staticmethod
    def find_process_by_title(title_substring: str) -> Optional[int]:
        """Find a process by window title substring. Returns PID or None."""
        result = []

        @WNDENUMPROC
        def enum_callback(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    try:
                        if title_substring.lower() in buf.value.lower():
                            pid = ctypes.wintypes.DWORD()
                            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                            result.append(pid.value)
                            return False
                    except Exception:
                        pass
            return True

        user32.EnumWindows(enum_callback, 0)
        return result[0] if result else None

    @staticmethod
    def open_process(pid: int) -> Optional[int]:
        """Open a process handle with required access rights."""
        if pid == 0:
            return None
        handle = kernel32.OpenProcess(
            PROCESS_VM_READ | PROCESS_VM_OPERATION | PROCESS_QUERY_INFORMATION,
            False,
            pid
        )
        return handle if handle else None

    @staticmethod
    def close_handle(handle: int):
        """Safely close a process handle."""
        if handle:
            kernel32.CloseHandle(handle)


class MemoryScanner:
    """
    Scans the emulator's process memory to find monster HP values.

    Uses two strategies:
    1. AOB (Array of Bytes) pattern scanning - fast, needs known patterns
    2. Value-based scanning - slower but works without pre-known patterns
    """

    def __init__(self, process_handle: int, hp_max_limit: int = 70000):
        self.handle = process_handle
        self.hp_max_limit = hp_max_limit
        self._scan_cache: Dict[int, int] = {}  # address -> expected offset cache

    def read_bytes(self, address: int, size: int) -> Optional[bytes]:
        """Read bytes from the target process at the given address."""
        buf = ctypes.create_string_buffer(size)
        bytes_read = ctypes.c_size_t(0)
        result = kernel32.ReadProcessMemory(
            self.handle,
            ctypes.c_void_p(address),
            buf,
            size,
            ctypes.byref(bytes_read)
        )
        if result and bytes_read.value == size:
            return buf.raw
        return None

    def read_int32(self, address: int) -> Optional[int]:
        """Read a 32-bit integer from the target process."""
        data = self.read_bytes(address, 4)
        if data:
            return struct.unpack('<i', data)[0]
        return None

    def read_uint32(self, address: int) -> Optional[int]:
        """Read an unsigned 32-bit integer from the target process."""
        data = self.read_bytes(address, 4)
        if data:
            return struct.unpack('<I', data)[0]
        return None

    def read_float(self, address: int) -> Optional[float]:
        """Read a 32-bit float from the target process."""
        data = self.read_bytes(address, 4)
        if data:
            return struct.unpack('<f', data)[0]
        return None

    def enumerate_memory_regions(self) -> List[MemoryRegion]:
        """
        Enumerate all readable committed memory regions in the target process.
        Returns list of MemoryRegion objects sorted by address.
        """
        regions = []
        address = 0
        mbi = MEMORY_BASIC_INFORMATION()

        while kernel32.VirtualQueryEx(
            self.handle,
            ctypes.c_void_p(address),
            ctypes.byref(mbi),
            ctypes.sizeof(mbi)
        ):
            if (mbi.State == MEM_COMMIT and
                mbi.Protect & (PAGE_READWRITE) and
                mbi.Type in (MEM_PRIVATE, MEM_MAPPED)):
                regions.append(MemoryRegion(
                    base_address=mbi.BaseAddress or 0,
                    size=mbi.RegionSize,
                    state=mbi.State,
                    protect=mbi.Protect,
                    type=mbi.Type,
                ))

            address = (mbi.BaseAddress or 0) + mbi.RegionSize

            # Safety limit: don't scan beyond reasonable bounds
            if address > 0x7FFFFFFFFFFF:
                break

        return regions

    def find_game_memory_region(self) -> Optional[Tuple[int, int]]:
        """
        Find the most likely game memory region.
        The Switch emulator allocates a large block for emulated RAM.
        For MHGU, this is typically a ~4GB region containing heap data.

        Returns (start_address, end_address) or None.
        """
        regions = self.enumerate_memory_regions()

        # Strategy: Find large private memory regions (> 1GB)
        # that likely contain the emulated Switch RAM
        candidates = []
        for r in regions:
            if r.size >= 0x40000000:  # >= 1GB
                candidates.append(r)

        if not candidates:
            # Fallback: use the largest region found
            if regions:
                largest = max(regions, key=lambda r: r.size)
                candidates = [largest]

        if candidates:
            # Use the largest candidate
            largest = max(candidates, key=lambda r: r.size)
            return (largest.base_address, largest.base_address + largest.size)

        return None

    def aob_scan(self, pattern: str, start: int = 0, end: int = 0,
                 max_results: int = 50) -> List[int]:
        """
        Array of Bytes scan in the target process memory.

        Args:
            pattern: AOB pattern string like '48 8B ?? ?? 8B 40 ?? C3'
                     ?? = wildcard byte
            start: Start address for scan
            end: End address for scan (0 = scan whole process)
            max_results: Maximum number of results to return

        Returns:
            List of matching addresses
        """
        # Parse pattern
        pattern_bytes = []
        wildcard_mask = []
        for part in pattern.split():
            if part == '??' or part == '?':
                pattern_bytes.append(0)
                wildcard_mask.append(1)  # 1 = wildcard
            else:
                pattern_bytes.append(int(part, 16))
                wildcard_mask.append(0)  # 0 = exact match

        pattern_len = len(pattern_bytes)
        pattern_buf = bytes(pattern_bytes)
        mask_buf = bytes(wildcard_mask)

        # Determine scan range
        if end == 0 or end <= start:
            game_region = self.find_game_memory_region()
            if game_region:
                scan_start, scan_end = game_region
            else:
                scan_start = 0x10000
                scan_end = 0x7FFFFFFFFFFF
        else:
            scan_start = start
            scan_end = end

        # Use the cached scan range if available (narrows subsequent scans)
        if start == 0 and self._scan_cache.get('_region_start'):
            scan_start = max(scan_start, self._scan_cache['_region_start'])
        if end == 0 and self._scan_cache.get('_region_end'):
            scan_end = min(scan_end, self._scan_cache['_region_end'])

        results = []
        chunk_size = 4096 * 1024  # 4MB chunks
        overlap = pattern_len - 1
        address = scan_start

        while address < scan_end and len(results) < max_results:
            read_size = min(chunk_size, scan_end - address)
            data = self.read_bytes(address, read_size)

            if data:
                # Search within this chunk
                for i in range(len(data) - pattern_len + 1):
                    match = True
                    for j in range(pattern_len):
                        if wildcard_mask[j] == 0 and data[i + j] != pattern_bytes[j]:
                            match = False
                            break
                    if match:
                        results.append(address + i)
                        if len(results) >= max_results:
                            break

            address += read_size - overlap if read_size > overlap else read_size

        return results

    def scan_for_hp_values(self, known_hp: int = 0,
                           region_start: int = 0,
                           region_end: int = 0) -> List[int]:
        """
        Scan for addresses containing a specific HP value.
        This is a value-based search, useful when AOB patterns aren't known.

        Args:
            known_hp: Known HP value to search for (0 = scan for any plausible HP)
            region_start: Start of region to scan (0 = auto)
            region_end: End of region to scan (0 = auto)

        Returns:
            List of addresses containing 32-bit integers in HP range
        """
        if region_start == 0 or region_end == 0:
            game_region = self.find_game_memory_region()
            if game_region:
                region_start, region_end = game_region
            else:
                return []

        results = []
        chunk_size = 256 * 1024  # 256KB chunks
        address = region_start

        while address < region_end:
            read_size = min(chunk_size, region_end - address)
            data = self.read_bytes(address, read_size)

            if data:
                for i in range(0, len(data) - 3, 4):
                    val = struct.unpack_from('<i', data, i)[0]
                    if known_hp > 0:
                        if val == known_hp:
                            results.append(address + i)
                    else:
                        # Look for plausible HP values (1-70000)
                        if 1 <= val <= self.hp_max_limit:
                            results.append(address + i)

            address += read_size

            # Limit results
            if len(results) > 10000:
                break

        return results

    def read_hp_value(self, address: int) -> Optional[int]:
        """Read a 32-bit HP value from the given address."""
        return self.read_int32(address)

    def find_monster_data_base(self,
                                region_start: int = 0,
                                region_end: int = 0) -> Optional[int]:
        """
        Find the monster data array base address using the known AOB pattern.
        Uses the exact pattern from the working MHGU HP overlay.

        Scans within the dynamically-detected game memory region first,
        then falls back to known base addresses for other emulators.

        Returns:
            Base address of monster data array, or None if not found.
        """
        from .addresses import AOB_MONSTER_DATA, MEMORY_BASE_ADDRESSES, MAX_SCAN_RANGE

        # PRIORITY 1: Scan the dynamically-found game memory region
        # This is the most reliable approach for any emulator
        game_region = self.find_game_memory_region()
        if game_region:
            gs, ge = game_region
            # Scan the entire game region in 80MB chunks
            chunk = MAX_SCAN_RANGE
            pos = gs
            while pos < ge:
                end = min(pos + chunk, ge)
                print(f"    AOB scanning game RAM: 0x{pos:X} - 0x{end:X}")
                results = self.aob_scan(AOB_MONSTER_DATA, pos, end, max_results=1)
                if results:
                    addr = results[0]
                    print(f"    [+] Monster data found at: 0x{addr:016X}")
                    return addr
                pos = end

        # PRIORITY 2: Try user-specified region
        if region_start != 0 and region_end != 0:
            print(f"    AOB scanning user region: 0x{region_start:X} - 0x{region_end:X}")
            results = self.aob_scan(AOB_MONSTER_DATA, region_start, region_end, max_results=1)
            if results:
                addr = results[0]
                print(f"    [+] Monster data found at: 0x{addr:016X}")
                return addr

        # PRIORITY 3: Try hardcoded base addresses (Ryujinx/Yuzu layout fallback)
        for base in MEMORY_BASE_ADDRESSES:
            start = base
            end = base + MAX_SCAN_RANGE
            if start < 0x10000:
                start = 0x10000
            print(f"    AOB scanning fallback: 0x{start:X} - 0x{end:X}")
            results = self.aob_scan(AOB_MONSTER_DATA, start, end, max_results=1)
            if results:
                addr = results[0]
                print(f"    [+] Monster data found at: 0x{addr:016X}")
                return addr

        return None

    def scan_monster_hp_entries(self, data_base: int, max_monsters: int = 5) -> List[int]:
        """
        Read HP values from all monster entries in the data array.

        Args:
            data_base: Base address from AOB scan
            max_monsters: Maximum number of monster entries to check

        Returns:
            List of (hp_address, hp_value) tuples
        """
        from .addresses import HP_OFFSET, MONSTER_ENTRY_STRIDE

        entries = []
        for i in range(max_monsters):
            entry_base = data_base + (i * MONSTER_ENTRY_STRIDE)
            hp_addr = entry_base + HP_OFFSET
            hp_val = self.read_uint32(hp_addr)

            if hp_val is not None and 1 <= hp_val <= self.hp_max_limit:
                entries.append(hp_addr)
            elif hp_val is not None and hp_val > 0:
                # HP might be above limit (some bosses have 60k+)
                entries.append(hp_addr)

        return entries

    def find_monster_hp_addresses(self,
                                   aob_patterns: List[str] = None,
                                   known_hp_range: Tuple[int, int] = None,
                                   region_start: int = 0,
                                   region_end: int = 0) -> List[int]:
        """
        Find monster HP addresses using the MHGU AOB approach.

        1. Scan for monster data array using known AOB pattern
        2. Read HP entries from the array at correct offsets
        3. Fall back to value-based scan if AOB fails

        Returns:
            List of HP addresses
        """
        # Primary approach: AOB-based (from reference MHGU overlay)
        data_base = self.find_monster_data_base(region_start, region_end)
        if data_base:
            hp_addrs = self.scan_monster_hp_entries(data_base)
            if hp_addrs:
                print(f"    [+] Found {len(hp_addrs)} monster HP entries via AOB scan")
                return hp_addrs

        # Fallback: try user-provided AOB patterns or value scan
        print(f"    [*] AOB scan did not find monsters, trying fallback...")
        candidates = set()

        if aob_patterns:
            for pattern in aob_patterns:
                if pattern.strip():
                    try:
                        results = self.aob_scan(pattern, region_start, region_end)
                        for addr in results:
                            hp = self.read_uint32(addr)
                            if hp is not None and 1 <= hp <= self.hp_max_limit:
                                candidates.add(addr)
                    except Exception:
                        continue

        if not candidates and known_hp_range:
            low, high = known_hp_range
            for test_hp in range(low, min(high + 1, low + 1000), 100):
                addresses = self.scan_for_hp_values(test_hp, region_start, region_end)
                for addr in addresses[:10]:
                    hp = self.read_uint32(addr)
                    if hp is not None and 1 <= hp <= self.hp_max_limit:
                        candidates.add(addr)
                if len(candidates) >= 5:
                    break

        return sorted(candidates)

    def monitor_address(self, address: int, interval: float = 0.1) -> List[int]:
        """
        Monitor a memory address for value changes.
        Returns list of [old_value, new_value] when a change is detected.
        """
        old_val = self.read_uint32(address)
        if old_val is None:
            return []

        time.sleep(interval)
        new_val = self.read_uint32(address)
        if new_val is None:
            return []

        if old_val != new_val:
            return [old_val, new_val]
        return []


class MonsterTracker:
    """
    Tracks monster HP values and calculates damage events.
    Manages the lifecycle of tracked monsters across quests.
    """

    def __init__(self, scanner: MemoryScanner):
        self.scanner = scanner
        self.monsters: Dict[int, MonsterInfo] = {}
        self.damage_events: List[DamageEvent] = []
        self._next_monster_id = 0
        self._baseline_hp: Dict[int, int] = {}  # address -> max HP seen

    def add_monster(self, hp_address: int) -> int:
        """Start tracking a monster at the given HP address."""
        current_hp = self.scanner.read_uint32(hp_address)
        if current_hp is None or current_hp <= 0:
            return -1

        monster_id = self._next_monster_id
        self._next_monster_id += 1

        monster = MonsterInfo(
            monster_id=monster_id,
            hp_address=hp_address,
            current_hp=current_hp,
            max_hp=current_hp,
            previous_hp=current_hp,
        )
        self.monsters[monster_id] = monster
        self._baseline_hp[hp_address] = current_hp
        return monster_id

    def update(self) -> List[DamageEvent]:
        """
        Update all tracked monsters and detect damage events.
        Returns list of new DamageEvent objects.
        """
        new_events = []
        current_time = time.time()
        monsters_to_remove = []

        for monster_id, monster in list(self.monsters.items()):
            current_hp = self.scanner.read_uint32(monster.hp_address)
            if current_hp is None:
                continue

            # Handle quest transitions / monster despawn
            if current_hp <= 0 or current_hp > self.scanner.hp_max_limit:
                monsters_to_remove.append(monster_id)
                continue

            monster.previous_hp = monster.current_hp
            monster.current_hp = current_hp

            # Update max HP (for display)
            if current_hp > monster.max_hp:
                monster.max_hp = current_hp

            # Detect damage
            hp_delta = monster.previous_hp - monster.current_hp

            if hp_delta > 0:
                # Verify it's real damage (not a buffer swap or data change)
                if hp_delta < monster.max_hp * 0.5:  # Max 50% in one hit
                    # Check for HP recovery (negative damage = healing)
                    if hp_delta > 0:
                        monster.last_damage = hp_delta
                        monster.last_update_time = current_time
                        event = DamageEvent(
                            monster_id=monster_id,
                            damage=hp_delta,
                            spawn_time=current_time,
                        )
                        new_events.append(event)
                        self.damage_events.append(event)

            # Detect HP recovery (possible new monster or quest restart)
            elif hp_delta < -100:
                # HP increased significantly - might be a new monster
                # Reset baseline
                self._baseline_hp[monster.hp_address] = current_hp
                monster.max_hp = current_hp

        # Clean up dead/despawned monsters
        for mid in monsters_to_remove:
            addr = self.monsters[mid].hp_address  # read before deleting
            del self.monsters[mid]
            self._baseline_hp.pop(addr, None)

        return new_events

    def get_display_hp(self, monster_id: int) -> Tuple[int, int, float]:
        """
        Get display info for a monster: (current_hp, max_hp, hp_percentage).
        """
        monster = self.monsters.get(monster_id)
        if monster:
            pct = (monster.current_hp / monster.max_hp * 100) if monster.max_hp > 0 else 0
            return (monster.current_hp, monster.max_hp, pct)
        return (0, 0, 0.0)

    def cleanup_old_events(self, max_age_seconds: float = 10.0):
        """Remove damage events older than max_age_seconds."""
        current_time = time.time()
        self.damage_events = [
            e for e in self.damage_events
            if current_time - e.spawn_time < max_age_seconds
        ]
