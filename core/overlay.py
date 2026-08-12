"""
Transparent overlay renderer for floating damage numbers.
Uses UpdateLayeredWindow + Pillow/FreeType rendering + numpy compositing.

Render core: Pillow (FreeType) renders each damage number once into a
premultiplied-BGRA sprite; the frame loop composites sprites into the
window buffer with per-number opacity fade.  True antialiasing, real
font loading (FontPath now honored), window follow/sync included.
"""

import ctypes, ctypes.wintypes, time, random, threading, numpy as np
import os
from typing import List, Optional
from dataclasses import dataclass, field
from PIL import Image, ImageDraw, ImageFont
from .config import OverlayConfig, hex_to_rgba

# ── Windows API setup ──────────────────────────────────────────────────
user32, gdi32, kernel32 = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32

kernel32.GetModuleHandleW.restype = ctypes.wintypes.HMODULE
user32.GetDC.restype = ctypes.wintypes.HDC; user32.GetDC.argtypes = [ctypes.wintypes.HWND]
user32.ReleaseDC.restype = ctypes.c_int; user32.ReleaseDC.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HDC]
user32.GetWindowTextLengthW.restype = ctypes.c_int; user32.GetWindowTextLengthW.argtypes = [ctypes.wintypes.HWND]
user32.GetWindowTextW.restype = ctypes.c_int; user32.GetWindowTextW.argtypes = [ctypes.wintypes.HWND, ctypes.c_void_p, ctypes.c_int]
user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD; user32.GetWindowThreadProcessId.argtypes = [ctypes.wintypes.HWND, ctypes.c_void_p]
gdi32.CreateSolidBrush.restype = ctypes.wintypes.HGDIOBJ; gdi32.CreateSolidBrush.argtypes = [ctypes.wintypes.COLORREF]
user32.FillRect.restype = ctypes.c_int; user32.FillRect.argtypes = [ctypes.wintypes.HDC, ctypes.c_void_p, ctypes.wintypes.HBRUSH]
user32.GetSystemMetrics.restype = ctypes.c_int; user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetWindowRect.restype = ctypes.c_bool; user32.GetWindowRect.argtypes = [ctypes.wintypes.HWND, ctypes.c_void_p]
user32.IsWindowVisible.restype = ctypes.c_bool; user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
user32.IsWindow.restype = ctypes.c_bool; user32.IsWindow.argtypes = [ctypes.wintypes.HWND]
user32.SetWindowPos.restype = ctypes.c_bool
user32.SetWindowPos.argtypes = [
    ctypes.wintypes.HWND, ctypes.wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.wintypes.UINT]
user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD
user32.RegisterClassW.restype = ctypes.wintypes.ATOM; user32.RegisterClassW.argtypes = [ctypes.c_void_p]
user32.CreateWindowExW.restype = ctypes.wintypes.HWND
user32.CreateWindowExW.argtypes = [
    ctypes.wintypes.DWORD, ctypes.wintypes.LPCWSTR, ctypes.wintypes.LPCWSTR,
    ctypes.wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.wintypes.HWND, ctypes.wintypes.HMENU, ctypes.wintypes.HANDLE,
    ctypes.wintypes.LPVOID]
user32.ShowWindow.restype = ctypes.c_bool; user32.ShowWindow.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
user32.DestroyWindow.restype = ctypes.c_bool; user32.DestroyWindow.argtypes = [ctypes.wintypes.HWND]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
user32.UpdateLayeredWindow.restype = ctypes.c_bool
user32.UpdateLayeredWindow.argtypes = [
    ctypes.wintypes.HWND, ctypes.wintypes.HDC, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.wintypes.HDC, ctypes.c_void_p, ctypes.wintypes.COLORREF,
    ctypes.c_void_p, ctypes.wintypes.DWORD]
user32.PeekMessageW.restype = ctypes.c_bool
user32.PeekMessageW.argtypes = [ctypes.c_void_p, ctypes.wintypes.HWND, ctypes.wintypes.UINT, ctypes.wintypes.UINT, ctypes.wintypes.UINT]
user32.TranslateMessage.restype = ctypes.c_bool; user32.TranslateMessage.argtypes = [ctypes.c_void_p]
user32.DispatchMessageW.restype = ctypes.wintypes.LPARAM; user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
user32.EnumWindows.restype = ctypes.c_bool
user32.EnumWindows.argtypes = [ctypes.c_void_p, ctypes.wintypes.LPARAM]
gdi32.CreateCompatibleDC.restype = ctypes.wintypes.HDC; gdi32.CreateCompatibleDC.argtypes = [ctypes.wintypes.HDC]
gdi32.DeleteDC.restype = ctypes.c_bool; gdi32.DeleteDC.argtypes = [ctypes.wintypes.HDC]
gdi32.SelectObject.restype = ctypes.wintypes.HGDIOBJ; gdi32.SelectObject.argtypes = [ctypes.wintypes.HDC, ctypes.wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = ctypes.c_bool; gdi32.DeleteObject.argtypes = [ctypes.wintypes.HGDIOBJ]
gdi32.CreateDIBSection.restype = ctypes.wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [ctypes.wintypes.HDC, ctypes.c_void_p, ctypes.wintypes.UINT, ctypes.c_void_p, ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
gdi32.GetStockObject.restype = ctypes.wintypes.HGDIOBJ; gdi32.GetStockObject.argtypes = [ctypes.c_int]

# ── Constants ──────────────────────────────────────────────────────────
WS_EX_LAYERED=0x80000; WS_EX_TRANSPARENT=0x20; WS_EX_TOPMOST=0x8; WS_EX_TOOLWINDOW=0x80; WS_POPUP=0x80000000
ULW_ALPHA=0x2; AC_SRC_OVER=0; AC_SRC_ALPHA=1
DIB_RGB_COLORS=0; PM_REMOVE=1
SWP_NOACTIVATE=0x10; SWP_NOOWNERZORDER=0x200; HWND_TOPMOST=-1

# ── Structs ────────────────────────────────────────────────────────────
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize",ctypes.wintypes.DWORD),("biWidth",ctypes.c_int),("biHeight",ctypes.c_int),("biPlanes",ctypes.wintypes.WORD),("biBitCount",ctypes.wintypes.WORD),("biCompression",ctypes.wintypes.DWORD),("biSizeImage",ctypes.wintypes.DWORD),("biXPelsPerMeter",ctypes.c_int),("biYPelsPerMeter",ctypes.c_int),("biClrUsed",ctypes.wintypes.DWORD),("biClrImportant",ctypes.wintypes.DWORD)]
class BITMAPINFO(ctypes.Structure): _fields_ = [("bmiHeader",BITMAPINFOHEADER)]
class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp",ctypes.c_byte),("BlendFlags",ctypes.c_byte),("SourceConstantAlpha",ctypes.c_byte),("AlphaFormat",ctypes.c_byte)]
class POINT(ctypes.Structure): _fields_ = [("x",ctypes.c_int),("y",ctypes.c_int)]
class SIZE(ctypes.Structure): _fields_ = [("cx",ctypes.c_int),("cy",ctypes.c_int)]
class RECT(ctypes.Structure): _fields_ = [("left",ctypes.c_int),("top",ctypes.c_int),("right",ctypes.c_int),("bottom",ctypes.c_int)]
class MSG(ctypes.Structure): _fields_ = [("hwnd",ctypes.wintypes.HWND),("message",ctypes.wintypes.UINT),("wParam",ctypes.c_size_t),("lParam",ctypes.c_ssize_t),("time",ctypes.wintypes.DWORD),("pt",POINT)]
class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style",ctypes.wintypes.UINT),("lpfnWndProc",ctypes.c_void_p),("cbClsExtra",ctypes.c_int),("cbWndExtra",ctypes.c_int),("hInstance",ctypes.wintypes.HINSTANCE),("hIcon",ctypes.wintypes.HANDLE),("hCursor",ctypes.wintypes.HANDLE),("hbrBackground",ctypes.wintypes.HANDLE),("lpszMenuName",ctypes.wintypes.LPCWSTR),("lpszClassName",ctypes.wintypes.LPCWSTR)]
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.wintypes.HWND, ctypes.wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t)
ENUMWNDPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

# ── FloatingNumber ─────────────────────────────────────────────────────
@dataclass
class FloatingNumber:
    damage: int; x: float; y: float; spawn_time: float
    lifetime: float=90; fade_time: float=30; elapsed: float=0.0; opacity: float=1.0
    stagger_x: float=0.0  # fixed horizontal offset (no drift)
    small: bool = False   # small-monster hit: smaller sprite, dimmer
    color: tuple = None   # (R,G,B,A) straight color, chosen by damage tier
    sprite_rgba: object = None  # straight RGBA ndarray (for scaling)
    sprite_bgra: object = None  # premultiplied BGRA ndarray (for ULW)


class OverlayRenderer:
    """Transparent overlay window that follows the emulator window."""

    def __init__(self, config: OverlayConfig):
        self.config = config; self.hwnd = None; self.width = self.height = 0
        self._window_x = self._window_y = 0; self.running = False
        self.floating_numbers: List[FloatingNumber] = []
        self._lock = threading.Lock()
        self._pil_fonts = {}  # font size -> cached ImageFont
        self._wndproc_cb = None; self._enum_cb = None
        c = config.renderer
        self._dc_low = hex_to_rgba(c.damage_color_low)
        self._dc_mid = hex_to_rgba(c.damage_color_mid)
        self._dc_high = hex_to_rgba(c.damage_color_high)
        self._th_mid = c.damage_threshold_mid
        self._th_high = c.damage_threshold_high
        self._sc = hex_to_rgba(c.damage_shadow_color)  # (R,G,B,A) straight
        self._stagger_positions: List[float] = []  # Track Y positions for X-stagger
        self._target_hwnd = None     # emulator window we follow
        self._last_sync = 0.0        # last time we checked target window rect

    def init_window(self, target_hwnd=None):
        self._target_hwnd = target_hwnd or None
        if target_hwnd:
            r = RECT(); user32.GetWindowRect(target_hwnd, ctypes.byref(r))
            self.width = max(r.right-r.left, 200); self.height = max(r.bottom-r.top, 200)
            self._window_x, self._window_y = r.left, r.top
        else:
            self.width = user32.GetSystemMetrics(0); self.height = user32.GetSystemMetrics(1)
            self._window_x = self._window_y = 0

        cn = "MHGUDamageV3"
        @WNDPROC
        def wp(hwnd, msg, w, l):
            return 0 if msg == 0x2 else user32.DefWindowProcW(hwnd, msg, w, l)
        self._wndproc_cb = wp
        wc = WNDCLASSW(); wc.lpfnWndProc = ctypes.cast(wp, ctypes.c_void_p)
        wc.hInstance = kernel32.GetModuleHandleW(None); wc.lpszClassName = cn
        wc.hbrBackground = gdi32.GetStockObject(0)
        user32.RegisterClassW(ctypes.byref(wc))
        ex = WS_EX_LAYERED|WS_EX_TRANSPARENT|WS_EX_TOPMOST|WS_EX_TOOLWINDOW
        self.hwnd = user32.CreateWindowExW(ex, cn, "", WS_POPUP,
            self._window_x, self._window_y, self.width, self.height,
            0, 0, kernel32.GetModuleHandleW(None), None)
        if not self.hwnd: raise RuntimeError("CreateWindowExW failed")
        user32.ShowWindow(self.hwnd, 1)

    def _sync_with_target(self):
        """Follow the emulator window: reposition/resize overlay if it moved,
        changed size, or toggled fullscreen. Called periodically from render_loop."""
        if not self.hwnd: return
        now = time.time()
        if now - self._last_sync < 0.25: return
        self._last_sync = now

        # Re-acquire target if it vanished (e.g. fullscreen toggle recreated it)
        if not self._target_hwnd or not user32.IsWindow(self._target_hwnd):
            try:
                self._target_hwnd = self.find_emulator_window(
                    self.config.scanner.emulator_process)
            except Exception:
                self._target_hwnd = None
            if not self._target_hwnd: return

        r = RECT()
        if not user32.GetWindowRect(self._target_hwnd, ctypes.byref(r)): return
        x, y = r.left, r.top
        w, h = r.right - r.left, r.bottom - r.top
        if w < 200 or h < 200: return  # minimized or transitioning
        if (x, y, w, h) == (self._window_x, self._window_y, self.width, self.height):
            return
        self._window_x, self._window_y, self.width, self.height = x, y, w, h
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, w, h,
            SWP_NOACTIVATE | SWP_NOOWNERZORDER)

    # ── Pillow font / sprite machinery ────────────────────────────────
    def _get_font(self, size: int = None):
        """Lazily load the configured font (FontPath) at the given size,
        falling back to Bahnschrift. Fonts are cached per size."""
        if size is None:
            size = self.config.renderer.font_size
        if size in self._pil_fonts:
            return self._pil_fonts[size]
        candidates = [self.config.renderer.font_path,
                      r"C:\Windows\Fonts\bahnschrift.ttf"]
        for path in candidates:
            if path and os.path.exists(path):
                try:
                    font = ImageFont.truetype(path, size)
                    try:  # match old GDI weight 700 (variable fonts)
                        font.set_variation_by_axes([700])
                    except Exception:
                        pass
                    self._pil_fonts[size] = font
                    return font
                except Exception:
                    continue
        font = ImageFont.load_default()
        self._pil_fonts[size] = font
        return font

    @staticmethod
    def _premultiply(arr: np.ndarray) -> np.ndarray:
        """straight RGBA -> premultiplied BGRA (UpdateLayeredWindow needs it)."""
        a = arr[:, :, 3].astype(np.float64)
        pre = arr[:, :, :3].astype(np.float64) * (a / 255.0)[:, :, None]
        out = np.empty(arr.shape, dtype=np.uint8)
        out[:, :, 0] = np.clip(pre[:, :, 2] + 0.5, 0, 255).astype(np.uint8)  # B
        out[:, :, 1] = np.clip(pre[:, :, 1] + 0.5, 0, 255).astype(np.uint8)  # G
        out[:, :, 2] = np.clip(pre[:, :, 0] + 0.5, 0, 255).astype(np.uint8)  # R
        out[:, :, 3] = arr[:, :, 3]  # alpha unchanged
        return out

    def _make_sprite(self, text: str, color: tuple, size: int = None):
        """Render one damage number with Pillow: 3-pass offset shadow +
        main text in the given color. Returns (straight RGBA, premultiplied
        BGRA); the RGBA copy is kept so the sprite can be scaled with true
        antialiasing for the pop-in animation."""
        cfg = self.config.renderer
        font = self._get_font(size)
        l, t, r, b = font.getbbox(text)
        extra = cfg.damage_shadow_offset_x + cfg.damage_shadow_thickness + 3
        w = (r - l) + extra * 2
        h = (b - t) + extra * 2
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        cx, cy = w // 2, h // 2
        if cfg.damage_shadow_enabled:
            for t2 in range(cfg.damage_shadow_thickness):
                d.text((cx + cfg.damage_shadow_offset_x + t2,
                        cy + cfg.damage_shadow_offset_y + t2),
                       text, font=font, fill=self._sc, anchor="mm")
        d.text((cx, cy), text, font=font, fill=color, anchor="mm")
        rgba = np.array(img)  # (h, w, 4) straight RGBA
        return rgba, self._premultiply(rgba)

    def _resize_sprite(self, rgba: np.ndarray, scale: float) -> np.ndarray:
        """Scale a straight-RGBA sprite (LANCZOS, true antialiasing) and
        return the premultiplied-BGRA result."""
        img = Image.fromarray(rgba, "RGBA")
        img = img.resize((max(1, round(img.width * scale)),
                          max(1, round(img.height * scale))), Image.LANCZOS)
        return self._premultiply(np.array(img))

    def _blit_sprite(self, buf, sprite, cx, cy, opacity):
        """Composite a premultiplied-BGRA sprite into the window buffer,
        centered on (cx, cy), with per-number fade opacity."""
        H, W = buf.shape[:2]
        h, w = sprite.shape[:2]
        x0 = int(cx) - w // 2
        y0 = int(cy) - h // 2
        if x0 >= W or y0 >= H or x0 + w <= 0 or y0 + h <= 0:
            return
        sx0 = max(0, -x0); sy0 = max(0, -y0)
        dx0 = max(0, x0);  dy0 = max(0, y0)
        sw = min(w - sx0, W - dx0); sh = min(h - sy0, H - dy0)
        if sw <= 0 or sh <= 0:
            return
        spr = sprite[sy0:sy0 + sh, sx0:sx0 + sw]
        region = buf[dy0:dy0 + sh, dx0:dx0 + sw]
        # Premultiplied source-over with per-number opacity. Never a plain
        # overwrite: an opaque blit would erase (zero the alpha of) any
        # number already composited underneath. Fading scales BOTH the rgb
        # and alpha of the source, otherwise the premultiplied invariant
        # breaks and fading numbers get a bright halo.
        sa = spr[:, :, 3].astype(np.float64) * opacity
        inv = (1.0 - sa / 255.0)
        region[:, :, 3] = np.clip(sa + region[:, :, 3] * inv + 0.5, 0, 255).astype(np.uint8)
        rgb = spr[:, :, :3].astype(np.float64) * opacity \
            + region[:, :, :3].astype(np.float64) * inv[:, :, None]
        region[:, :, :3] = np.clip(rgb + 0.5, 0, 255).astype(np.uint8)

    # ── Frame render ──────────────────────────────────────────────────
    def _render_frame(self):
        if not self.hwnd: return
        w, h = self.width, self.height
        hdc_screen = user32.GetDC(0); hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        bmi = BITMAPINFO(); bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w; bmi.bmiHeader.biHeight = -h
        bmi.bmiHeader.biPlanes = 1; bmi.bmiHeader.biBitCount = 32; bmi.bmiHeader.biCompression = 0
        pixels_ptr = ctypes.c_void_p()
        hbm = gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(pixels_ptr), 0, 0)
        if not hbm: gdi32.DeleteDC(hdc_mem); user32.ReleaseDC(0, hdc_screen); return
        old_bmp = gdi32.SelectObject(hdc_mem, hbm)

        pc = w*h*4; buf_t = ctypes.c_byte*pc
        pixels = buf_t.from_address(pixels_ptr.value)
        px = np.frombuffer(pixels, dtype=np.uint8).reshape(h, w, 4)
        px.fill(0)

        now = time.time()
        cfg = self.config.renderer
        with self._lock:
            survivors = []
            for fn in self.floating_numbers:
                fn.elapsed = now - fn.spawn_time
                total = (fn.lifetime + fn.fade_time)/60.0
                if fn.elapsed > total: continue
                survivors.append(fn)
                if fn.sprite_rgba is None:
                    fs = cfg.font_size
                    size = max(8, int(fs * cfg.small_font_scale)) if fn.small else fs
                    fn.sprite_rgba, fn.sprite_bgra = self._make_sprite(
                        str(int(fn.damage)), fn.color or self._dc_high, size=size)
                if fn.sprite_bgra is None: continue

                # Fade: hold then ease-out
                life_s = fn.lifetime/60.0
                fade_s = fn.fade_time/60.0 if fn.fade_time > 0 else 0.001
                fn.opacity = 1.0 if fn.elapsed < life_s else max(0.0, 1.0-(fn.elapsed-life_s)/fade_s)

                # Pop-in: rise ~0.6 * font_size px over 0.22s ease-out, then hold
                rise_s = 0.22
                r = min(fn.elapsed/rise_s, 1.0)
                rise = cfg.font_size * 0.6 * (1.0 - (1.0-r)*(1.0-r))
                tx = int(fn.x + fn.stagger_x)
                ty = int(fn.y - rise)

                # Pop-scale: 0.8 -> 1.0 with easeOutBack overshoot bounce
                c1 = 1.70158; c3 = c1 + 1
                eob = 1.0 + c3 * (r-1.0)**3 + c1 * (r-1.0)**2
                scale = 0.8 + 0.2 * eob

                # Small-monster hits render dimmer (configurable max opacity)
                opacity = fn.opacity * (cfg.small_opacity if fn.small else 1.0)

                if abs(scale - 1.0) < 0.001:
                    spr = fn.sprite_bgra
                else:
                    spr = self._resize_sprite(fn.sprite_rgba, scale)
                self._blit_sprite(px, spr, tx, ty, opacity)
            self.floating_numbers = survivors

        blend = BLENDFUNCTION(); blend.BlendOp = AC_SRC_OVER
        blend.SourceConstantAlpha = 255; blend.AlphaFormat = AC_SRC_ALPHA
        pt_src = POINT(); pt_dst = POINT(self._window_x, self._window_y); sz = SIZE(w, h)
        user32.UpdateLayeredWindow(self.hwnd, hdc_screen,
            ctypes.byref(pt_dst), ctypes.byref(sz), hdc_mem, ctypes.byref(pt_src),
            0, ctypes.byref(blend), ULW_ALPHA)

        gdi32.SelectObject(hdc_mem, old_bmp); gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(hdc_mem); user32.ReleaseDC(0, hdc_screen)

    def _tier_color(self, damage: int) -> tuple:
        """White < mid threshold < yellow < high threshold < orange."""
        if damage < self._th_mid:
            return self._dc_low
        if damage < self._th_high:
            return self._dc_mid
        return self._dc_high

    def spawn_damage_number(self, damage: int, is_small: bool = False):
        if not self.config.renderer.show_damage_numbers:
            return
        with self._lock:
            cfg = self.config
            fs = cfg.renderer.font_size
            # Spawn around the configurable anchor (AnchorXRatio/AnchorYRatio),
            # with random spread scaled to window size so numbers stay inside
            # even when the window is squashed.
            axr = min(1.0, max(0.0, cfg.renderer.anchor_x_ratio))
            ayr = min(1.0, max(0.0, cfg.renderer.anchor_y_ratio))
            ax = int(self.width * axr)
            ay = int(self.height * ayr)
            spread_x = min(120, max(0, self.width//2 - 160))
            cx = ax + (random.randint(-spread_x, spread_x) if spread_x else 0)
            up_hi = min(250, max(90, self.height//2 - fs*2))
            up_lo = min(80, up_hi)
            cy = ay - random.randint(up_lo, up_hi)
            # Clamp into the visible area (leave room for the pop-up rise)
            cy = max(fs, min(cy, self.height - fs))

            # X-stagger: check for overlapping numbers and offset horizontally
            stagger_x = 0
            for pos in self._stagger_positions:
                if abs(cy - pos) < 60:  # Numbers close vertically
                    stagger_x += cfg.logic.x_stagger_step * (1 if random.random() > 0.5 else -1)
            self._stagger_positions.append(cy)
            if len(self._stagger_positions) > cfg.logic.overlap_max:
                self._stagger_positions.pop(0)

            fn = FloatingNumber(damage=damage, x=cx, y=cy, spawn_time=time.time(),
                lifetime=cfg.logic.lifetime, fade_time=cfg.logic.fade_time,
                stagger_x=stagger_x, small=is_small,
                color=self._tier_color(damage))
            self.floating_numbers.append(fn)
            while len(self.floating_numbers) > cfg.logic.overlap_max:
                self.floating_numbers.pop(0)

    def render_loop(self, fps=60):
        self.running = True; ft = 1.0/fps
        while self.running:
            start = time.time()
            self._sync_with_target()
            if self.hwnd: self._render_frame()
            msg = MSG()
            while user32.PeekMessageW(ctypes.byref(msg), self.hwnd or 0, 0, 0, PM_REMOVE):
                user32.TranslateMessage(ctypes.byref(msg)); user32.DispatchMessageW(ctypes.byref(msg))
            elapsed = time.time()-start
            if elapsed < ft: time.sleep(ft-elapsed)

    def shutdown(self):
        self.running = False
        if self.hwnd: user32.DestroyWindow(self.hwnd); self.hwnd = None

    def find_emulator_window(self, process_name="eden.exe"):
        from .scanner import ProcessManager
        pid = ProcessManager.find_process_by_name(process_name)
        if not pid:
            try: pid = ProcessManager.find_process_by_title("eden")
            except: pass
        if not pid: return None
        result = []
        @ENUMWNDPROC
        def cb(hwnd, _):
            wp = ctypes.wintypes.DWORD(); user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wp))
            if wp.value == pid and user32.IsWindowVisible(hwnd): result.append(hwnd); return False
            return True
        self._enum_cb = cb; user32.EnumWindows(cb, 0)
        return result[0] if result else None
