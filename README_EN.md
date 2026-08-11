# Eden MHGU Damage Overlay

> **Note:** English isn't my first language — I had AI help with this translation, and I don't want that to cause any confusion or offense. If anything reads oddly, the [Chinese version](README.md) is the authoritative one.

Floating damage numbers for **Monster Hunter Generations Ultimate** (MHGU) on the **Eden Switch emulator** — the kind of damage pop-ups you're used to from World/Rise, for the game that never got them.

I'm not a professional developer — I'm sure there are plenty of conventions I don't know, so if I'm doing something wrong, please point it out.

When I got into this game, it really bothered me that the older Monster Hunter titles have no damage display. I'm grateful to the veterans who pointed me in the right direction and let me try building one. It was made for my own use; with AI's help I'm sharing it in the hope that it helps other GU hunters.

I haven't tested how things behave on MHXX in the Eden emulator. Bug fixes may come slowly — and if a bug is too hard to fix and doesn't affect gameplay, I may not fix it. I'll do my best.

## How it works

It AOB-scans eden.exe's process memory to find each monster's HP address, then keeps reading the HP value. **Every HP drop is damage** — the plugin renders those drops as floating numbers on screen.

## Features

- Damage numbers for monsters and small critters alike (small critters are toned down by default: smaller font, lower opacity, so they don't clutter the screen)
- Tiered colors — white for small hits, yellow for medium, orange for big ones (thresholds are configurable)

## Usage

**Order matters: launch the game first, then the plugin.**

1. Start Eden (`eden.exe`) and load MHGU.
2. Start the plugin — either way:
   - **Option A (no Python needed):** double-click `MHGUDamageOverlay.exe`
   - **Option B (run from source):**
     ```
     cd <plugin folder>
     pip install -r requirements.txt     # first time only (pywin32 + numpy + Pillow)
     python mhgu_damage_overlay.py
     ```
3. It finds and tracks monsters within seconds to tens of seconds — land a hit and the numbers show up.
4. To close: just close the plugin window. The game is unaffected.

### Command-line options (source mode)

- `--no-overlay`: console-only mode — logs damage numbers without the overlay window (debugging)
- `--config <path>`: use a different config.ini
- `--emulator <process name>`: attach to a different emulator process (default: eden.exe)

### FAQ

- **No numbers showing?** Make sure you're in a scene with monsters (a quest or the arena) — the plugin only starts after it detects a monster. Check `overlay_error.log` for a `Monster tracked` line.
- **Do I need admin rights?** Usually not — same-user permissions are enough to read Eden's memory. If the log shows `access denied`, run the plugin as administrator.
- **Log file:** `overlay_error.log` sits next to the plugin — check it first when something seems off.
- **Rebuilding the exe:** after editing the source, run `python -m PyInstaller --onefile --name MHGUDamageOverlay --clean --noconfirm --add-binary "core/scanmodule.pyd;core" --version-file dev/version_info.txt mhgu_damage_overlay.py` (the `--add-binary` part is required — it packs the core scanning module into the exe), then copy `dist\MHGUDamageOverlay.exe` back to the plugin folder.

## Configuration (config.ini)

`config.ini` ships with Chinese comments on every setting. Key settings:

| Setting | Key(s) | Default |
|---|---|---|
| Damage tier colors | `DamageColorLow / Mid / High` (white / yellow / orange) | `#FFFFFF / #FFD93B / #E49124` |
| Tier thresholds | `DamageThresholdMid / High` | `40 / 80` (white &lt;40, orange ≥80) |
| Number anchor point | `AnchorXRatio / AnchorYRatio` (screen ratio 0–1) | `0.5 / 0.5` (center) |
| Small-monster scaling | `SmallFontScale` (font size ratio), `SmallOpacity` (max opacity) | `0.6 / 0.65` |
| Font & size | `FontPath`, `FontSize` | System Bahnschrift / `70` |
| Shadow | `DamageShadowEnabled / Color / OffsetX / OffsetY / Thickness` | On / black / 2,2 / 3 |
| Number timing | `[Logic]`: hold frames, fade frames, stagger distance, max on-screen | 90 / 30 / 45 / 10 |
| Scanning | `[Scanner]`: HP cap, scan interval, emulator process | 70000 / 50ms / eden.exe |

## Known limitations

- **Can't tell your damage from your Palico's** — the game memory only holds the monster's total HP, with no info about the source of a hit.
- **No crit detection** — same reason: there's no crit flag in memory, only HP deltas.
- **Numbers don't appear at the hit spot** — the plugin can't read the monster's 3D position or the camera matrix, so numbers spawn at a configurable anchor (center of the screen by default).
- A sleeping monster's natural HP regen shows up as an HP *increase* — correctly, it is not shown as damage.
- Small-monster numbers don't distinguish species — just the large/small tiering.

## Credits

**First and foremost, thanks to Alexander-Lancellott's [MHGU-MHXX-HP-Overlay-For-Switch-Emulator](https://github.com/Alexander-Lancellott/MHGU-MHXX-HP-Overlay-For-Switch-Emulator) (GPL v3).**

**How the two tools fit together:** that tool shows monster HP; this plugin only shows damage numbers (it doesn't display HP). They don't conflict — you can run both at the same time.

The core memory part of this plugin is entirely that author's work:

- The AOB patterns and the memory offsets for current/max HP, the monster ID, and the visibility byte
- How to locate Eden's emulated-RAM region (0x9BBF000 etc.)
- The `scanmodule` C extension for fast region enumeration and AOB scanning — `core/scanmodule.pyd` in this repo is its compiled artifact, and the corresponding C source is kept in the repo as `modules/scanmodule.c`
- Windows API documentation (MSDN) for `UpdateLayeredWindow`, `ReadProcessMemory`, and friends

**Without that author's open tool and source, this plugin couldn't exist.** Thanks to the author and to every open-source contributor.

## License

This project is released under **GPL v3** — the same license as the reference tool.

- Under GPL v3, this project is a derivative work of the reference tool (also GPL v3)
- This repo ships: all source code, `LICENSE` (the full GPL v3 text), and the scanmodule C source (`modules/scanmodule.c`, from the reference tool)
- You may distribute the exe freely, but you must provide the source and the license alongside it
- If you distribute modified versions, they must also be GPL v3

> The `dev/` folder holds dev-time helper scripts (diagnostics, render comparison, regression tests) — unrelated to the plugin itself. Feel free to delete it or poke around.
