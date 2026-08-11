"""
Configuration management for Eden MHGU Damage Overlay.
INI format with [Renderer] / [Logic] / [Scanner] sections.
"""

import os
import sys
import configparser
from dataclasses import dataclass, field


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
        r.font_size = parser.getint('Renderer', 'FontSize', fallback=r.font_size)
        r.show_damage_numbers = parser.getboolean('Renderer', 'ShowDamageNumbers', fallback=r.show_damage_numbers)
        r.damage_color_low = parser.get('Renderer', 'DamageColorLow', fallback=r.damage_color_low)
        r.damage_color_mid = parser.get('Renderer', 'DamageColorMid', fallback=r.damage_color_mid)
        r.damage_color_high = parser.get('Renderer', 'DamageColorHigh', fallback=r.damage_color_high)
        r.damage_threshold_mid = parser.getint('Renderer', 'DamageThresholdMid', fallback=r.damage_threshold_mid)
        r.damage_threshold_high = parser.getint('Renderer', 'DamageThresholdHigh', fallback=r.damage_threshold_high)
        r.anchor_x_ratio = parser.getfloat('Renderer', 'AnchorXRatio', fallback=r.anchor_x_ratio)
        r.anchor_y_ratio = parser.getfloat('Renderer', 'AnchorYRatio', fallback=r.anchor_y_ratio)
        r.small_font_scale = parser.getfloat('Renderer', 'SmallFontScale', fallback=r.small_font_scale)
        r.small_opacity = parser.getfloat('Renderer', 'SmallOpacity', fallback=r.small_opacity)
        r.damage_shadow_enabled = parser.getboolean('Renderer', 'DamageShadowEnabled', fallback=r.damage_shadow_enabled)
        r.damage_shadow_color = parser.get('Renderer', 'DamageShadowColor', fallback=r.damage_shadow_color)
        r.damage_shadow_offset_x = parser.getint('Renderer', 'DamageShadowOffsetX', fallback=r.damage_shadow_offset_x)
        r.damage_shadow_offset_y = parser.getint('Renderer', 'DamageShadowOffsetY', fallback=r.damage_shadow_offset_y)
        r.damage_shadow_thickness = parser.getint('Renderer', 'DamageShadowThickness', fallback=r.damage_shadow_thickness)

    # [Logic]
    if parser.has_section('Logic'):
        l = cfg.logic
        l.lifetime = parser.getint('Logic', 'Lifetime', fallback=l.lifetime)
        l.fade_time = parser.getint('Logic', 'FadeTime', fallback=l.fade_time)
        l.x_stagger_step = parser.getint('Logic', 'XStaggerStep', fallback=l.x_stagger_step)
        l.overlap_max = parser.getint('Logic', 'OverlapMax', fallback=l.overlap_max)

    # [Scanner]
    if parser.has_section('Scanner'):
        s = cfg.scanner
        s.hp_max_limit = parser.getint('Scanner', 'HpMaxLimit', fallback=s.hp_max_limit)
        s.scan_interval_ms = parser.getint('Scanner', 'ScanIntervalMs', fallback=s.scan_interval_ms)
        s.emulator_process = parser.get('Scanner', 'EmulatorProcess', fallback=s.emulator_process)
        patterns_str = parser.get('Scanner', 'AobPatterns', fallback='')
        if patterns_str:
            s.aob_patterns = [p.strip() for p in patterns_str.split('\n') if p.strip()]
        s.scan_region_start = parser.getint('Scanner', 'ScanRegionStart', fallback=s.scan_region_start)
        s.scan_region_end = parser.getint('Scanner', 'ScanRegionEnd', fallback=s.scan_region_end)

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
