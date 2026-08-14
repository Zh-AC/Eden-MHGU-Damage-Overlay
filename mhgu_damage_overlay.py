"""
Eden Switch Emulator - Monster Hunter GU Damage Overlay
======================================================

Displays floating damage numbers on top of the game window when
running Monster Hunter Generations Ultimate (MHGU)
on the eden Nintendo Switch emulator (eden.exe).

Memory scanning (AOB patterns, offsets, scanmodule) is derived from
MHGU-MHXX-HP-Overlay-For-Switch-Emulator by Alexander-Lancellott
(GPL v3) - see README/THANKS. This project is released under GPL v3.

Usage:
    python mhgu_damage_overlay.py
    MHGUDamageOverlay.exe      (standalone executable)

Requirements:
    - Windows 10/11
    - Usually no admin rights needed (reads Eden's memory as the same user)
    - eden Switch emulator running MHGU
"""

__version__ = "1.0.2"

import sys
import os
import time
import io
import traceback
import threading
from datetime import datetime
from typing import Optional, List

# ── Early error logging setup ──────────────────────────────────────────
# All errors are written to overlay_error.log next to the exe/script.
# Max log size: 1MB, rotated on each startup.

_LOG_MAX_SIZE = 1 * 1024 * 1024  # 1MB max

def _log_path():
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.dirname(sys.executable), 'overlay_error.log')
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'overlay_error.log')

# Track last log message to avoid spam
_last_log_msg = None
_last_log_count = 0

def _log(msg: str):
    global _last_log_msg, _last_log_count
    try:
        # Rate-limit: if same message repeats, collapse
        if msg == _last_log_msg:
            _last_log_count += 1
            if _last_log_count > 1 and _last_log_count % 60 != 1:  # Log every 60th repeat
                return
            if _last_log_count == 61:
                msg = f"(repeated {_last_log_count-1} times) ... " + msg
            elif _last_log_count > 61:
                msg = f"(x{_last_log_count}) {msg}"
        else:
            _last_log_msg = msg
            _last_log_count = 1

        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_path = _log_path()

        # Rotate log if too large
        if os.path.exists(log_path) and os.path.getsize(log_path) > _LOG_MAX_SIZE:
            # Truncate to last 100KB
            with open(log_path, 'rb') as f:
                f.seek(-100 * 1024, 2)
                tail = f.read()
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(f'[{stamp}] --- Log rotated (was too large) ---\n')
                f.write(tail.decode('utf-8', errors='replace'))

        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f'[{stamp}] {msg}\n')
    except Exception:
        pass

# Log unhandled exceptions
def _excepthook(exc_type, exc_value, exc_tb):
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
    _log('UNHANDLED EXCEPTION:\n' + ''.join(tb_lines))
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _excepthook

# Add parent directory to path for core module imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_log(f'Starting Eden MHGU Damage Overlay v{__version__}...')
_log(f'Python {sys.version}')
_log(f'Executable: {sys.executable}')
_log(f'Working dir: {os.getcwd()}')

try:
    from core.config import load_config, OverlayConfig, take_config_warnings
    from core.scanner import (
        ProcessManager,
        MemoryScanner,
        MonsterTracker,
        DamageEvent,
    )
    from core.scanner_eden import (
        has_scanmodule,
        find_eden_pid,
        open_process,
        get_game_region,
        find_monster_hp,
        describe_monster,
        EdenMonsterTracker,
    )
    from core.overlay import OverlayRenderer
    from core.addresses import EMULATOR_PROCESSES, SMALL_MONSTERS, MONSTER_NAMES
    _log('All core modules imported successfully.')
except Exception as e:
    _log(f'Module import failed: {e}\n{traceback.format_exc()}')
    raise


class MHGUDamageOverlay:
    """Main application class."""

    def __init__(self, config_path: str = None):
        _log('Loading config...')
        self.config = load_config(config_path)
        for w in take_config_warnings():
            _log('CONFIG WARNING: ' + w)
        _log(f'Config loaded. Emulator target: {self.config.scanner.emulator_process}')
        self.process_handle = None
        self.pid = None
        self.scanner: Optional[MemoryScanner] = None
        self.tracker: Optional[MonsterTracker] = None
        self.renderer: Optional[OverlayRenderer] = None
        self.running = False
        self._scan_thread: Optional[threading.Thread] = None

    def find_emulator(self) -> bool:
        """Locate and attach to the emulator process."""
        process_name = self.config.scanner.emulator_process
        _log(f'Searching for emulator process: {process_name}')

        # Try eden-specific fast path using scanmodule
        if has_scanmodule():
            _log('scanmodule available, using fast eden detection')
            self.pid = find_eden_pid()
            _log(f'find_eden_pid() -> {self.pid}')
            if not self.pid:
                # Fall back to generic process search
                self.pid = ProcessManager.find_process_by_name(process_name)
                _log(f'find_process_by_name("{process_name}") -> {self.pid}')
        else:
            self.pid = ProcessManager.find_process_by_name(process_name)
            _log(f'find_process_by_name("{process_name}") -> {self.pid}')

        if not self.pid:
            base_name = process_name.replace('.exe', '')
            for emu_name, emu_exe in EMULATOR_PROCESSES.items():
                if base_name.lower() in emu_name.lower():
                    self.pid = ProcessManager.find_process_by_name(emu_exe)
                    _log(f'Tried {emu_exe} -> {self.pid}')
                    if self.pid:
                        process_name = emu_exe
                        break

        if not self.pid:
            _log('Trying window title search...')
            try:
                self.pid = ProcessManager.find_process_by_title("Eden")
                _log(f'find_process_by_title("Eden") -> {self.pid}')
            except Exception as e:
                _log(f'Window title search error: {e}')

        if not self.pid:
            for title in ["MHGU", "Monster Hunter", "Ryujinx", "Yuzu", "Sudachi"]:
                try:
                    self.pid = ProcessManager.find_process_by_title(title)
                    _log(f'find_process_by_title("{title}") -> {self.pid}')
                    if self.pid:
                        break
                except Exception:
                    pass

        if not self.pid:
            _log('Emulator process not found.')
            return False

        _log(f'Found PID: {self.pid}  Process: {process_name}')

        self.process_handle = ProcessManager.open_process(self.pid)
        _log(f'open_process -> {self.process_handle}')
        if not self.process_handle:
            _log('Failed to open process (access denied, run with admin rights).')
            return False

        _log('Process handle opened successfully.')
        return True

    def init_scanner(self):
        """Initialize the memory scanner and monster tracker."""
        _log('Initializing memory scanner...')

        # Use eden-specific scanner when scanmodule is available
        if has_scanmodule():
            _log('Using EdenMonsterTracker (scanmodule)')
            self.scanner = None  # Not using MemoryScanner for eden
            self.eden_base = get_game_region(self.pid, self.config.scanner.emulator_process)
            _log(f'Game region from scanmodule: 0x{self.eden_base:X}' if self.eden_base else 'Game region: None')
            self.tracker = EdenMonsterTracker(self.process_handle)
            self._found_hp_addresses = set()
        else:
            _log('Falling back to generic MemoryScanner')
            self.scanner = MemoryScanner(
                self.process_handle,
                hp_max_limit=self.config.scanner.hp_max_limit
            )
            self.tracker = MonsterTracker(self.scanner)
            self.eden_base = None

            _log('Scanning for game memory region...')
            try:
                region = self.scanner.find_game_memory_region()
                if region:
                    start, end = region
                    size_mb = (end - start) / (1024 * 1024)
                    _log(f'Game memory region: 0x{start:016X} - 0x{end:016X} ({size_mb:.0f} MB)')
                else:
                    _log('Could not identify game memory region.')
            except Exception as e:
                _log(f'Memory region scan error: {e}')

    def _is_game_running(self) -> bool:
        """Check if MHGU is running in the emulator by window title."""
        import ctypes
        import ctypes.wintypes
        user32 = ctypes.windll.user32
        found = False

        def enum_cb(hwnd, lparam):
            nonlocal found
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                    if any(t in title for t in ['MONSTER HUNTER', 'Monster Hunter', 'MHGU']):
                        found = True
                        return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        return found

    def init_overlay(self):
        """Initialize the transparent overlay renderer."""
        _log('Initializing damage overlay window...')
        self.renderer = OverlayRenderer(self.config)

        target_hwnd = None
        try:
            target_hwnd = self.renderer.find_emulator_window(
                self.config.scanner.emulator_process
            )
            _log(f'Emulator window HWND: {target_hwnd}')
        except Exception as e:
            _log(f'Find emulator window error: {e}')

        self.renderer.init_window(target_hwnd)
        _log('Overlay window created.')

    def scan_loop(self):
        """Background thread: find monsters once, then track HP changes."""
        _log('Scan loop started.')
        scan_interval = self.config.scanner.scan_interval_ms / 1000.0
        found_addresses = set()
        consecutive_errors = 0
        last_full_scan = 0
        last_scan_attempt = 0
        scan_cooldown = 5.0      # Wait 5s between scan attempts
        full_scan_interval = 15.0
        initial_scan_done = False
        scan_in_progress = False
        rescan_soon = False          # tracker dropped a monster: rescan now
        empty_scan_streak = 0        # consecutive full scans finding nothing

        while self.running:
            try:
                current_time = time.time()

                # Full AOB scan scheduling:
                #  * before the first success: only when the game window is
                #    visible (avoids useless scans during boot), on cooldown;
                #  * after the first success: keep scanning periodically NO
                #    MATTER what the window-title check says. The title
                #    probe is a heuristic that can false-negative (minimized
                #    window, renamed title bar); once monsters were found we
                #    must keep rediscovering them after quest/zone changes
                #    (1.0.1 report: "after the first monster, 0 damage").
                #  * immediately when the tracker dropped addresses (dead /
                #    stale monsters) so the player never waits a full cycle.
                game_running = self._is_game_running()
                since_last = current_time - last_scan_attempt
                need_full_scan = (
                    (not initial_scan_done and game_running and since_last > scan_cooldown) or
                    (initial_scan_done and current_time - last_full_scan > full_scan_interval) or
                    (rescan_soon and current_time - last_full_scan > 1.0)
                )
                if not game_running and not initial_scan_done:
                    # Game not loaded yet — skip scan, try again later
                    if since_last > 15:  # Only log every 15s
                        _log('Waiting for MHGU game to load...')

                if need_full_scan and not scan_in_progress:
                    scan_in_progress = True
                    last_scan_attempt = current_time
                    self._find_and_track_monsters(found_addresses)
                    last_full_scan = current_time
                    scan_in_progress = False
                    rescan_soon = False
                    if found_addresses:
                        initial_scan_done = True
                        empty_scan_streak = 0
                        _log('Initial scan done, tracking %d monsters' % len(found_addresses))
                    else:
                        # Nothing found on the current region base. If this
                        # repeats, the emulated-RAM region may have moved
                        # (game reload): re-detect the base instead of
                        # scanning the wrong region forever (that state
                        # looked like "0 damage until restart" in 1.0.1).
                        empty_scan_streak += 1
                        if empty_scan_streak >= 2 and has_scanmodule():
                            new_base = get_game_region(
                                self.pid, self.config.scanner.emulator_process)
                            empty_scan_streak = 0
                            if new_base and new_base != self.eden_base:
                                _log('Game region moved: 0x%X -> 0x%X'
                                     % (self.eden_base or 0, new_base))
                                self.eden_base = new_base
                        if not initial_scan_done:
                            _log('Scan found no monsters, will retry in %ds' % scan_cooldown)

                # Fast HP update (just reads known addresses)
                if self.tracker:
                    if has_scanmodule() and isinstance(self.tracker, EdenMonsterTracker):
                        damages = self.tracker.update()
                        if damages:
                            for dmg, mid in damages:
                                ammo = None
                                state = None
                                if self.renderer:
                                    state = self.renderer.spawn_damage_number(
                                        dmg, is_small=mid in SMALL_MONSTERS,
                                        mid=mid)
                                name = MONSTER_NAMES.get(mid, 'Unknown')
                                ammo_s = f' ammo={ammo}' if ammo is not None else ''
                                if state:
                                    tname, B, ratio = state
                                    if B is not None:
                                        _log('Damage: %d (%s mid=%s%s) [B=%.0f r=%.2f %s]'
                                             % (dmg, name, mid, ammo_s,
                                                B, ratio, tname))
                                    else:
                                        _log('Damage: %d (%s mid=%s%s) [%s]'
                                             % (dmg, name, mid, ammo_s, tname))
                                else:
                                    _log('Damage: %d (%s mid=%s%s)'
                                         % (dmg, name, mid, ammo_s))
                        self.tracker.cleanup_old_damage(max_age=10.0)
                        # Drop addresses the tracker has removed (dead/left monsters)
                        # so they can be rediscovered by the next full scan.
                        if found_addresses:
                            before = len(found_addresses)
                            found_addresses.intersection_update(self.tracker.monsters.keys())
                            if len(found_addresses) < before:
                                # A monster slot died / went stale: ask for
                                # an immediate full scan instead of waiting
                                # up to a full cycle (slow intervals made
                                # this a multi-minute outage in 1.0.1).
                                rescan_soon = True
                    else:
                        events = self.tracker.update()
                        if events:
                            for event in events:
                                state = None
                                if self.renderer:
                                    state = self.renderer.spawn_damage_number(
                                        event.damage, mid=event.monster_id)
                                name = MONSTER_NAMES.get(event.monster_id, 'Unknown')
                                if state:
                                    tname, B, ratio = state
                                    if B is not None:
                                        _log('Damage: %d (%s mid=%s) [B=%.0f r=%.2f %s]'
                                             % (event.damage, name, event.monster_id,
                                                B, ratio, tname))
                                    else:
                                        _log('Damage: %d (%s mid=%s) [%s]'
                                             % (event.damage, name, event.monster_id, tname))
                                else:
                                    _log('Damage: %d (%s mid=%s)'
                                         % (event.damage, name, event.monster_id))
                        self.tracker.cleanup_old_events(max_age_seconds=10.0)

                consecutive_errors = 0
                time.sleep(scan_interval)

            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors <= 3:
                    _log(f'Scan error: {e}')
                time.sleep(1.0)

    def _find_and_track_monsters(self, found_addresses: set) -> int:
        """Full AOB scan for monster HP addresses; returns how many NEW
        monsters were added.

        There is deliberately no "reuse cached addresses and skip the full
        scan" shortcut anymore: a stale cached slot that still validated
        used to return early and could starve every OTHER monster for the
        rest of the session (1.0.1 report: "killed one monster, afterwards
        all scans show 0 damage, must restart"). The full scan is only a
        few seconds and runs at most every few seconds, so just do it.
        """
        added = 0

        # Eden path: full AOB scan
        if has_scanmodule() and self.eden_base:
            try:
                addresses = find_monster_hp(self.process_handle, self.eden_base)
                if addresses:
                    for addr in addresses:
                        if addr not in found_addresses:
                            self.tracker.add_monster(addr)
                            found_addresses.add(addr)
                            added += 1
                            try:
                                info = describe_monster(self.process_handle, addr)
                                mname = MONSTER_NAMES.get(info[0], '?') if info else '?'
                                _log(f'Monster tracked: 0x{addr:X} ({mname})')
                            except Exception:
                                _log(f'Monster tracked: 0x{addr:X}')
            except Exception as e:
                _log(f'AOB scan error: {e}')
            return added

        # If scanmodule available but base not found, retry getting base
        if has_scanmodule() and not self.eden_base:
            self.eden_base = get_game_region(self.pid, self.config.scanner.emulator_process)
            if self.eden_base:
                _log(f'Game region found on retry: 0x{self.eden_base:X}')
                return added

        # Fallback path
        if not self.scanner:
            return added

        patterns = self.config.scanner.aob_patterns
        region_start = self.config.scanner.scan_region_start
        region_end = self.config.scanner.scan_region_end

        try:
            addresses = self.scanner.find_monster_hp_addresses(
                aob_patterns=patterns,
                region_start=region_start,
                region_end=region_end,
            )
            for addr in addresses:
                if addr not in found_addresses:
                    monster_id = self.tracker.add_monster(addr)
                    if monster_id >= 0:
                        found_addresses.add(addr)
                        added += 1
        except Exception as e:
            _log(f'Find monsters error: {e}')
        return added

    def run(self):
        """Main entry point."""
        _log('=' * 50)
        _log('Eden MHGU Damage Overlay starting...')
        _log('=' * 50)

        # Try to find emulator; if not found, wait in a loop
        emulator_found = False
        try:
            emulator_found = self.find_emulator()
        except Exception as e:
            _log(f'find_emulator crashed: {e}\n{traceback.format_exc()}')
            raise

        if not emulator_found:
            _log('Emulator not found. Entering wait loop...')
            # Wait for emulator - poll every 3 seconds
            while True:
                try:
                    time.sleep(3)
                    if self.find_emulator():
                        emulator_found = True
                        break
                except KeyboardInterrupt:
                    _log('KeyboardInterrupt in wait loop.')
                    return
                except Exception as e:
                    _log(f'Wait loop error: {e}')
                    time.sleep(3)

        if not emulator_found:
            _log('Never found emulator, exiting.')
            return

        # Initialize components
        _log('Initializing scanner and overlay...')
        try:
            self.init_scanner()
        except Exception as e:
            _log(f'Scanner init failed: {e}\n{traceback.format_exc()}')
            raise

        if getattr(self, 'no_overlay', False):
            # Console-only mode: scan and log damage without the overlay window
            _log('Console-only mode (--no-overlay), skipping overlay init.')
            self.running = True
            self._scan_thread = threading.Thread(target=self.scan_loop, daemon=True)
            self._scan_thread.start()
            _log('Scan thread started.')
            try:
                while self.running:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                _log('KeyboardInterrupt in console loop.')
            finally:
                self.shutdown()
            return

        try:
            self.init_overlay()
        except Exception as e:
            _log(f'Overlay init failed: {e}\n{traceback.format_exc()}')
            raise

        # Start background scanner thread
        self.running = True
        self._scan_thread = threading.Thread(target=self.scan_loop, daemon=True)
        self._scan_thread.start()
        _log('Scan thread started.')

        _log('Entering render loop...')
        try:
            if self.renderer:
                self.renderer.render_loop(fps=60)
        except KeyboardInterrupt:
            _log('KeyboardInterrupt in render loop.')
        except Exception as e:
            _log(f'Render loop error: {e}\n{traceback.format_exc()}')
        finally:
            self.shutdown()

    def shutdown(self):
        """Clean shutdown."""
        _log('Shutting down...')
        self.running = False

        if self.renderer:
            try:
                self.renderer.shutdown()
            except Exception as e:
                _log(f'Renderer shutdown error: {e}')

        if self.process_handle:
            try:
                ProcessManager.close_handle(self.process_handle)
            except Exception as e:
                _log(f'Close handle error: {e}')
            self.process_handle = None

        _log('Shutdown complete.')


def main():
    """Entry point function."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Eden Switch Emulator - MHGU Damage Overlay"
    )
    parser.add_argument('--version', action='version',
                        version='%(prog)s v' + __version__)
    parser.add_argument('--config', '-c', default=None, help='Path to config.ini')
    parser.add_argument('--emulator', '-e', default=None, help='Emulator process name')
    parser.add_argument('--no-overlay', action='store_true', help='Console-only mode')

    args = parser.parse_args()

    try:
        overlay = MHGUDamageOverlay(config_path=args.config)
        overlay.no_overlay = args.no_overlay
        if args.emulator:
            overlay.config.scanner.emulator_process = args.emulator
        overlay.run()
    except Exception as e:
        _log(f'FATAL: {e}\n{traceback.format_exc()}')
        # Also try to show a message box so the user sees the error
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, str(e), "Eden MHGU Damage Overlay - Error", 0x10)
        except Exception:
            pass
        sys.exit(1)


if __name__ == '__main__':
    main()
