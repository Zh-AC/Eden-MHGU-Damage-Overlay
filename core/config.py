"""
Configuration management for Eden MHGU Damage Overlay.
INI format with [Renderer] / [Logic] / [Scanner] sections.
"""

import os
import sys
import configparser
from dataclasses import dataclass, field


# ── Robust config reading ──────────────────────────────────────────────
# Any bad value in config.ini must NOT crash the plugin: non-numeric
# values fall back to defaults, out-of-range values are clamped, and
# every correction is collected here so the main app can log it.

CONFIG_WARNINGS = []


def _warn(msg: str):
    CONFIG_WARNINGS.append(msg)


def take_config_warnings():
    """Return the warnings collected by the last load_config() and reset."""
    out = list(CONFIG_WARNINGS)
    CONFIG_WARNINGS.clear()
    return out


def _get_int(parser, section, key, default, lo, hi):
    try:
        raw = parser.get(section, key)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return default
    try:
        v = int(str(raw).strip())
    except ValueError:
        _warn(f'{key} = {raw!r} 不是整数, 已恢复默认值 {default}')
        return default
    if v < lo or v > hi:
        nv = max(lo, min(v, hi))
        _warn(f'{key} = {v} 超出安全范围 {lo}~{hi}, 已自动修正为 {nv}')
        return nv
    return v


def _get_float(parser, section, key, default, lo, hi):
    try:
        raw = parser.get(section, key)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return default
    try:
        v = float(str(raw).strip())
    except ValueError:
        _warn(f'{key} = {raw!r} 不是数字, 已恢复默认值 {default}')
        return default
    if v < lo or v > hi:
        nv = max(lo, min(v, hi))
        _warn(f'{key} = {v} 超出安全范围 {lo}~{hi}, 已自动修正为 {nv}')
        return nv
    return v


def _get_bool(parser, section, key, default):
    try:
        return parser.getboolean(section, key, fallback=default)
    except ValueError:
        _warn(f'{key} 的值无法识别(应为 0/1), 已恢复默认值 {int(default)}')
        return default


@dataclass
class RendererConfig:
    """Display/rendering settings."""
    font_path: str = "C:\\Windows\\Fonts\\bahnschrift.ttf"
    font_size: int = 70
    show_damage_numbers: bool = True
    damage_color_low: str = "#FFFFFF"    # small hits
    damage_color_mid: str = "#FFD93B"    # medium hits
    damage_color_high: str = "#E49124"   # big hits
    damage_threshold_mid: int = 40       # hits < 40 = white
    damage_threshold_high: int = 80      # hits >= 80 = orange
    anchor_x_ratio: float = 0.5          # where numbers spawn: 0=left edge, 1=right
    anchor_y_ratio: float = 0.5          # 0=top edge, 1=bottom
    small_font_scale: float = 0.6        # small-monster numbers: 60% size
    small_opacity: float = 0.65          # small-monster numbers: 65% max opacity
    damage_shadow_enabled: bool = True
    damage_shadow_color: str = "#000000D9"
    damage_shadow_offset_x: int = 2
    damage_shadow_offset_y: int = 2
    damage_shadow_thickness: int = 3


@dataclass
class LogicConfig:
    """Damage number animation/logic settings."""
    lifetime: int = 90        # frames before damage number starts fading
    fade_time: int = 30       # frames for fade-out animation
    x_stagger_step: int = 45  # horizontal spread between overlapping numbers
    overlap_max: int = 10     # max overlapping damage numbers



@dataclass
class ScannerConfig:
    """Memory scanner settings."""
    hp_max_limit: int = 70000          # ignore HP values above this
    scan_interval_ms: int = 100        # milliseconds between scans
    emulator_process: str = "eden.exe" # target emulator process name
    # AOB patterns for finding monster HP in MHGU memory
    # Format: semicolon-separated hex bytes, ?? = wildcard
    aob_patterns: list = field(default_factory=lambda: [
        # These patterns are specific to MHGU on Switch
        # Users should update these based on their game version
    ])
    # Memory region to scan (inclusive bounds, 0 = auto-detect)
    scan_region_start: int = 0
    scan_region_end: int = 0


@dataclass
class OverlayConfig:
    """Full overlay configuration."""
    renderer: RendererConfig = field(default_factory=RendererConfig)
    logic: LogicConfig = field(default_factory=LogicConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)


def hex_to_rgba(hex_color: str) -> tuple:
    """Convert hex color string to (R, G, B, A) tuple."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        return (r, g, b, 255)
    elif len(hex_color) == 8:
        r, g, b, a = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16), int(hex_color[6:8], 16)
        return (r, g, b, a)
    return (255, 255, 255, 255)


def _get_default_config_path() -> str:
    """Get the default path for config.ini, handling PyInstaller bundles."""
    # When running as PyInstaller onefile exe, sys._MEIPASS is the temp extract dir
    # We want config.ini next to the exe, not in the temp dir
    if getattr(sys, 'frozen', False):
        # Running as bundled exe - look next to the exe
        exe_dir = os.path.dirname(sys.executable)
        return os.path.join(exe_dir, 'config.ini')
    else:
        # Running as script - look in parent directory of core/
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.ini')


def load_config(config_path: str = None) -> OverlayConfig:
    """
    Load configuration from config.ini file.
    Falls back to defaults if file doesn't exist.
    """
    if config_path is None:
        config_path = _get_default_config_path()

    CONFIG_WARNINGS.clear()
    cfg = OverlayConfig()

    if not os.path.exists(config_path):
        save_config(cfg, config_path)
        return cfg

    parser = configparser.ConfigParser()
    parser.read(config_path, encoding='utf-8')

    # [Renderer]
    if parser.has_section('Renderer'):
        r = cfg.renderer
        r.font_path = parser.get('Renderer', 'FontPath', fallback=r.font_path)
        r.font_size = _get_int(parser, 'Renderer', 'FontSize', r.font_size, 8, 800)
        r.show_damage_numbers = _get_bool(parser, 'Renderer', 'ShowDamageNumbers', r.show_damage_numbers)
        r.damage_color_low = parser.get('Renderer', 'DamageColorLow', fallback=r.damage_color_low)
        r.damage_color_mid = parser.get('Renderer', 'DamageColorMid', fallback=r.damage_color_mid)
        r.damage_color_high = parser.get('Renderer', 'DamageColorHigh', fallback=r.damage_color_high)
        r.damage_threshold_mid = _get_int(parser, 'Renderer', 'DamageThresholdMid', r.damage_threshold_mid, 0, 1000000)
        r.damage_threshold_high = _get_int(parser, 'Renderer', 'DamageThresholdHigh', r.damage_threshold_high, 0, 1000000)
        if r.damage_threshold_mid > r.damage_threshold_high:
            _warn('DamageThresholdMid 大于 DamageThresholdHigh, 已自动对调')
            r.damage_threshold_mid, r.damage_threshold_high = r.damage_threshold_high, r.damage_threshold_mid
        r.anchor_x_ratio = _get_float(parser, 'Renderer', 'AnchorXRatio', r.anchor_x_ratio, 0.0, 1.0)
        r.anchor_y_ratio = _get_float(parser, 'Renderer', 'AnchorYRatio', r.anchor_y_ratio, 0.0, 1.0)
        r.small_font_scale = _get_float(parser, 'Renderer', 'SmallFontScale', r.small_font_scale, 0.1, 2.0)
        r.small_opacity = _get_float(parser, 'Renderer', 'SmallOpacity', r.small_opacity, 0.0, 1.0)
        r.damage_shadow_enabled = _get_bool(parser, 'Renderer', 'DamageShadowEnabled', r.damage_shadow_enabled)
        r.damage_shadow_color = parser.get('Renderer', 'DamageShadowColor', fallback=r.damage_shadow_color)
        r.damage_shadow_offset_x = _get_int(parser, 'Renderer', 'DamageShadowOffsetX', r.damage_shadow_offset_x, -500, 500)
        r.damage_shadow_offset_y = _get_int(parser, 'Renderer', 'DamageShadowOffsetY', r.damage_shadow_offset_y, -500, 500)
        r.damage_shadow_thickness = _get_int(parser, 'Renderer', 'DamageShadowThickness', r.damage_shadow_thickness, 0, 50)

    # [Logic]
    if parser.has_section('Logic'):
        l = cfg.logic
        l.lifetime = _get_int(parser, 'Logic', 'Lifetime', l.lifetime, 1, 3600)
        l.fade_time = _get_int(parser, 'Logic', 'FadeTime', l.fade_time, 0, 3600)
        l.x_stagger_step = _get_int(parser, 'Logic', 'XStaggerStep', l.x_stagger_step, 0, 500)
        l.overlap_max = _get_int(parser, 'Logic', 'OverlapMax', l.overlap_max, 1, 200)

    # [Scanner]
    if parser.has_section('Scanner'):
        s = cfg.scanner
        s.hp_max_limit = _get_int(parser, 'Scanner', 'HpMaxLimit', s.hp_max_limit, 1000, 1000000000)
        s.scan_interval_ms = _get_int(parser, 'Scanner', 'ScanIntervalMs', s.scan_interval_ms, 50, 5000)
        s.emulator_process = parser.get('Scanner', 'EmulatorProcess', fallback=s.emulator_process)
        patterns_str = parser.get('Scanner', 'AobPatterns', fallback='')
        if patterns_str:
            s.aob_patterns = [p.strip() for p in patterns_str.split('\n') if p.strip()]
        s.scan_region_start = _get_int(parser, 'Scanner', 'ScanRegionStart', s.scan_region_start, 0, 2**63 - 1)
        s.scan_region_end = _get_int(parser, 'Scanner', 'ScanRegionEnd', s.scan_region_end, 0, 2**63 - 1)


    return cfg


def save_config(cfg: OverlayConfig, config_path: str = None):
    """Save configuration to config.ini file."""
    if config_path is None:
        config_path = _get_default_config_path()

    parser = configparser.ConfigParser()

    # [Renderer]
    parser.add_section('Renderer')
    r = cfg.renderer
    parser.set('Renderer', 'FontPath', r.font_path)
    parser.set('Renderer', 'FontSize', str(r.font_size))
    parser.set('Renderer', 'ShowDamageNumbers', str(int(r.show_damage_numbers)))
    parser.set('Renderer', 'DamageColorLow', r.damage_color_low)
    parser.set('Renderer', 'DamageColorMid', r.damage_color_mid)
    parser.set('Renderer', 'DamageColorHigh', r.damage_color_high)
    parser.set('Renderer', 'DamageThresholdMid', str(r.damage_threshold_mid))
    parser.set('Renderer', 'DamageThresholdHigh', str(r.damage_threshold_high))
    parser.set('Renderer', 'AnchorXRatio', str(r.anchor_x_ratio))
    parser.set('Renderer', 'AnchorYRatio', str(r.anchor_y_ratio))
    parser.set('Renderer', 'SmallFontScale', str(r.small_font_scale))
    parser.set('Renderer', 'SmallOpacity', str(r.small_opacity))
    parser.set('Renderer', 'DamageShadowEnabled', str(int(r.damage_shadow_enabled)))
    parser.set('Renderer', 'DamageShadowColor', r.damage_shadow_color)
    parser.set('Renderer', 'DamageShadowOffsetX', str(r.damage_shadow_offset_x))
    parser.set('Renderer', 'DamageShadowOffsetY', str(r.damage_shadow_offset_y))
    parser.set('Renderer', 'DamageShadowThickness', str(r.damage_shadow_thickness))

    # [Logic]
    parser.add_section('Logic')
    l = cfg.logic
    parser.set('Logic', 'Lifetime', str(l.lifetime))
    parser.set('Logic', 'FadeTime', str(l.fade_time))
    parser.set('Logic', 'XStaggerStep', str(l.x_stagger_step))
    parser.set('Logic', 'OverlapMax', str(l.overlap_max))

    # [Scanner]
    parser.add_section('Scanner')
    s = cfg.scanner
    parser.set('Scanner', 'HpMaxLimit', str(s.hp_max_limit))
    parser.set('Scanner', 'ScanIntervalMs', str(s.scan_interval_ms))
    parser.set('Scanner', 'EmulatorProcess', s.emulator_process)
    parser.set('Scanner', 'AobPatterns', '\n'.join(s.aob_patterns))
    parser.set('Scanner', 'ScanRegionStart', str(s.scan_region_start))
    parser.set('Scanner', 'ScanRegionEnd', str(s.scan_region_end))


    # Add blank line before sections (configparser doesn't do this natively)
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write('[Renderer]\n')
        for key, value in parser.items('Renderer'):
            f.write(f'{key}={value}\n')
        f.write('\n[Logic]\n')
        for key, value in parser.items('Logic'):
            f.write(f'{key}={value}\n')
        f.write('\n[Scanner]\n')
        for key, value in parser.items('Scanner'):
            f.write(f'{key}={value}\n')
