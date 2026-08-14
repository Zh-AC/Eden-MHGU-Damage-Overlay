"""
MHGU memory addresses and AOB patterns for Switch emulators.

Data extracted from MHGU-MHXX-HP-Overlay v1.1.3 (Alexander-Lancellott).
These are the exact patterns/offsets used by the working HP overlay tool.

GAME VERSIONS:
- MHGU (USA/EUR) Title ID: 0100770008DD8000, versions 1.0, 1.4
"""

# Known emulator process names
EMULATOR_PROCESSES = {
    "eden": "eden.exe",
    "ryujinx": "ryujinx.exe",
    "yuzu": "yuzu.exe",
    "sudachi": "sudachi.exe",
    "suyu": "suyu.exe",
}

# ── Core AOB Patterns (from working HP overlay v1.1.3) ─────────────

# Main pattern: identifies the monster data array in emulated memory
# Format: space-separated hex bytes, ?? = wildcard
AOB_MONSTER_DATA = (
    "?? ?? 01 ?? ?? 18 00 00 ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? "
    "20 00 00 00 00 00 00 00"
)

# Pattern to find which monster the player is targeting (lock-on)
AOB_MONSTER_SELECTED = "28 00 00 00 D1"

# ── Memory Offsets ─────────────────────────────────────────────────

# Within each monster data entry (found via AOB), HP is at this offset
HP_OFFSET = 0x450  # 1104 bytes from AOB match

# Additional HP display value offsets (Current, Max, etc.)
HP_DISPLAY_OFFSETS = {
    "hp_0": 1103,   # HP field variant 0
    "hp_1": 1104,   # HP field variant 1 (primary current HP)
    "hp_2": 1105,   # HP field variant 2
    "hp_3": 1106,   # HP field variant 3
    "hp_4": 1107,   # HP field variant 4
    "hp_5": 1303,   # HP field variant 5 (likely max HP)
    "hp_6": 1323,   # HP field variant 6
    "hp_7": 1343,   # HP field variant 7
    "hp_8": 1351,   # HP field variant 8
}

# Offset to the currently-selected/locked-on monster indicator
SELECTED_MONSTER_OFFSET = 0x175D  # 5981 bytes from AOB match

# Stride between monster entries in the data array
MONSTER_ENTRY_STRIDE = 0x17A0  # 6048 bytes

# ── Status Effect Offsets (from monster data base) ─────────────────

STATUS_OFFSETS = {
    "Poison":    {"buildup": 0x5924, "threshold": 0x5930},
    "Sleep":     {"buildup": 0x5928, "threshold": 0x5926},
    "Paralysis": {"buildup": 0x593E, "threshold": 0x593C},
    "Dizzy":     {"buildup": 0x5A06, "threshold": 0x5A08},
    "Exhaust":   {"buildup": 0x5A12, "threshold": 0x5A14},
    "Jump":      {"buildup": 0x5A2A, "threshold": 0x5A2C},
    "Blast":     {"buildup": 0x5A3A, "threshold": 0x5A38},
    "Rage":      0x1A4,   # Rage timer (seconds remaining)
}

# ── Memory Region Configuration ────────────────────────────────────# Memory base addresses to try when locating game data
# These are virtual address offsets where Switch emulators map game RAM
MEMORY_BASE_ADDRESSES = [
    0xE955000,   # Primary region
    0x4052000,   # Fallback 1
    0x9BBF000,   # Fallback 2
    0x9BAE000,   # Fallback 3
]

# Size of the data region to scan after finding the AOB match
DATA_REGION_SIZE = 0x6000000  # ~96 MB - covers all monster data

# Maximum scan range for initial AOB search (from memory base)
MAX_SCAN_RANGE = 0x5000000  # ~80 MB

# ── Monster Name Database (ID -> Name) ─────────────────────────────

# Large monsters. IDs are the in-game monster IDs read from memory
# (OFF_NAME), taken verbatim from the reference HP overlay's models.py
# (Alexander-Lancellott / MHGU-MHXX-HP-Overlay-For-Switch-Emulator).
# NOTE: these are NOT sequential - the gaps are real.
LARGE_MONSTERS = {
    1: "Rathian", 2: "Rathalos", 3: "Khezu", 4: "Basarios",
    5: "Gravios", 7: "Diablos", 8: "Yian Kut-ku", 9: "Gypceros",
    10: "Plesioth", 11: "Kirin", 12: "Lao-Shan Lung",
    13: "Fatalis", 14: "Velocidrome", 15: "Gendrome",
    16: "Iodrome", 17: "Cephadrome", 18: "Yian Garuga",
    19: "Daimyo Hermitaur", 20: "Shogun Ceanataur",
    21: "Congalala", 22: "Blangonga", 23: "Rajang",
    24: "Kushala Daora", 25: "Chameleos", 27: "Teostra",
    30: "Bulldrome", 32: "Tigrex", 33: "Akantor",
    34: "Giadrome", 36: "Lavasioth", 37: "Nargacuga",
    38: "Ukanlos", 42: "Barioth", 43: "Deviljho",
    44: "Barroth", 45: "Uragaan", 46: "Lagiacrus",
    47: "Royal Ludroth", 49: "Agnaktor", 50: "Alatreon",
    55: "Duramboros", 56: "Niblesnarf", 57: "Zinogre",
    58: "Amatsu", 60: "Arzuros", 61: "Lagombi",
    62: "Volvidon", 63: "Brachydios", 65: "Kecha Wacha",
    66: "Tetsucabra", 67: "Zamtrios", 68: "Najarala",
    69: "Seltas Queen", 70: "Nerscylla", 71: "Gore Magala",
    72: "Shagaru Magala", 76: "Seltas", 77: "Seregios",
    79: "Malfestio", 80: "Glavenus", 81: "Astalos",
    82: "Mizutsune", 83: "Gammoth", 84: "Nakarkos",
    85: "Great Maccao", 86: "Valstrax", 87: "Ahtal-Neset",
    88: "Ahtal-Ka",
    # Special / Deviants (IDs are sparse, keep as-is from reference)
    269: "Crimson Fatalis", 513: "Gold Rathian", 514: "Silver Rathalos",
    525: "White Fatalis", 1025: "Dreadqueen Rathian",
    1026: "Dreadking Rathalos", 1031: "Bloodbath Diablos",
    1042: "Deadeye Yian Garuga", 1043: "Stonefist Hermitaur",
    1044: "Rustrazor Ceanataur", 1056: "Grimclaw Tigrex",
    1061: "Silverwind Nargacuga", 1069: "Crystalbeard Uragaan",
    1081: "Thunderlord Zinogre", 1084: "Redhelm Arzuros",
    1085: "Snowbaron Lagombi", 1090: "Drilltusk Tetsucabra",
    1103: "Nightcloak Malfestio", 1104: "Hellblade Glavenus",
    1105: "Boltreaver Astalos", 1106: "Soulseer Mizutsune",
    1107: "Elderfrost Gammoth", 1303: "Furious Rajang",
    1323: "Savage Deviljho", 1343: "Raging Brachydios",
    1351: "Chaotic Gore Magala",
}

# Small monsters (IDs 4097+)
SMALL_MONSTERS = {
    4097: "Aptonoth", 4098: "Apceros", 4099: "Kelbi",
    4100: "Mosswine", 4101: "Hornetaur", 4102: "Vespoid",
    4103: "Felyne", 4104: "Melynx", 4105: "Velociprey",
    4106: "Genprey", 4107: "Ioprey", 4108: "Cephalos",
    4109: "Bullfango", 4110: "Popo", 4111: "Giaprey",
    4112: "Anteka", 4113: "Great Thunderbug", 4115: "Remobra",
    4116: "Hermitaur", 4117: "Ceanataur", 4118: "Conga",
    4119: "Blango", 4121: "Rhenophlos", 4122: "Bnahabra",
    4123: "Altaroth", 4130: "Jaggi", 4131: "Jaggia",
    4135: "Ludroth", 4136: "Uroktor", 4137: "Slagtoth",
    4138: "Gargwa", 4140: "Zamite", 4141: "Konchu",
    4142: "Maccao", 4143: "Larinoth", 4144: "Moofah",
    4197: "Rock",
}

# Combined monster lookup
MONSTER_NAMES = {**LARGE_MONSTERS, **SMALL_MONSTERS}


def get_monster_name(monster_id: int) -> str:
    """Get monster name from ID."""
    return MONSTER_NAMES.get(monster_id, f"Monster #{monster_id}")
