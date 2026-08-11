"""Task #1: Render comparison — GDI (current) vs Pillow (FreeType).

Draws the same damage number three ways and composes them into one image:
  [1] GDI exactly as the current overlay renders it (3-pass offset shadow,
      CLEARTYPE, "nonzero => alpha 255" post-processing)  — 现状复刻
  [2] Pillow, same Bahnschrift font, same colors/logic      — 新引擎同字体
  [3] Pillow + Orbitron (备用字体评估)                       — 新引擎换字体测试

Output: tools/render_compare.png  (original size + 3x pixel-zoom strip)
"""

import ctypes
import ctypes.wintypes
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import sys, os
# Walk up from this file until we find the project root (contains core/)
_root = os.path.dirname(os.path.abspath(__file__))
while _root and not os.path.isdir(os.path.join(_root, 'core')):
    _root = os.path.dirname(_root)
sys.path.insert(0, _root)
from core.config import hex_to_rgba

# ── GDI plumbing (mirrors core/overlay.py) ──────────────────────────────
user32, gdi32, kernel32 = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32
user32.GetDC.restype = ctypes.wintypes.HDC; user32.GetDC.argtypes = [ctypes.wintypes.HWND]
user32.ReleaseDC.restype = ctypes.c_int; user32.ReleaseDC.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HDC]
gdi32.CreateCompatibleDC.restype = ctypes.wintypes.HDC; gdi32.CreateCompatibleDC.argtypes = [ctypes.wintypes.HDC]
gdi32.DeleteDC.restype = ctypes.c_bool; gdi32.DeleteDC.argtypes = [ctypes.wintypes.HDC]
gdi32.SelectObject.restype = ctypes.wintypes.HGDIOBJ; gdi32.SelectObject.argtypes = [ctypes.wintypes.HDC, ctypes.wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = ctypes.c_bool; gdi32.DeleteObject.argtypes = [ctypes.wintypes.HGDIOBJ]
gdi32.SetBkMode.restype = ctypes.c_int; gdi32.SetBkMode.argtypes = [ctypes.wintypes.HDC, ctypes.c_int]
gdi32.SetTextColor.restype = ctypes.wintypes.COLORREF; gdi32.SetTextColor.argtypes = [ctypes.wintypes.HDC, ctypes.wintypes.COLORREF]
gdi32.CreateFontIndirectW.restype = ctypes.wintypes.HFONT; gdi32.CreateFontIndirectW.argtypes = [ctypes.c_void_p]
gdi32.CreateDIBSection.restype = ctypes.wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [ctypes.wintypes.HDC, ctypes.c_void_p, ctypes.wintypes.UINT, ctypes.c_void_p, ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
gdi32.GetStockObject.restype = ctypes.wintypes.HGDIOBJ; gdi32.GetStockObject.argtypes = [ctypes.c_int]
user32.DrawTextW.restype = ctypes.c_int
user32.DrawTextW.argtypes = [ctypes.wintypes.HDC, ctypes.wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p, ctypes.wintypes.UINT]

class LOGFONTW(ctypes.Structure):
    _fields_ = [("lfHeight",ctypes.c_int),("lfWidth",ctypes.c_int),("lfEscapement",ctypes.c_int),("lfOrientation",ctypes.c_int),("lfWeight",ctypes.c_int),("lfItalic",ctypes.c_byte),("lfUnderline",ctypes.c_byte),("lfStrikeOut",ctypes.c_byte),("lfCharSet",ctypes.c_byte),("lfOutPrecision",ctypes.c_byte),("lfClipPrecision",ctypes.c_byte),("lfQuality",ctypes.c_byte),("lfPitchAndFamily",ctypes.c_byte),("lfFaceName",ctypes.c_wchar*32)]
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize",ctypes.wintypes.DWORD),("biWidth",ctypes.c_int),("biHeight",ctypes.c_int),("biPlanes",ctypes.wintypes.WORD),("biBitCount",ctypes.wintypes.WORD),("biCompression",ctypes.wintypes.DWORD),("biSizeImage",ctypes.wintypes.DWORD),("biXPelsPerMeter",ctypes.c_int),("biYPelsPerMeter",ctypes.c_int),("biClrUsed",ctypes.wintypes.DWORD),("biClrImportant",ctypes.wintypes.DWORD)]
class BITMAPINFO(ctypes.Structure): _fields_ = [("bmiHeader",BITMAPINFOHEADER)]
class RECT(ctypes.Structure): _fields_ = [("left",ctypes.c_int),("top",ctypes.c_int),("right",ctypes.c_int),("bottom",ctypes.c_int)]

CLEARTYPE_QUALITY = 5
DT_CENTER, DT_VCENTER, DT_NOCLIP = 1, 4, 0x100
DIB_RGB_COLORS = 0
Bahnschrift = r"C:\Windows\Fonts\bahnschrift.ttf"
# Optional: Orbitron (OFL). Not shipped with this repo; if you download it
# into the system fonts folder it is used for the third comparison column.
Orbitron = r"C:\Windows\Fonts\Orbitron-VariableFont_wght.ttf"


def gdi_render(text: str, size: int = 70, face: str = "Bahnschrift",
               weight: int = 700) -> np.ndarray:
    """Replicate core/overlay.py._draw_gdi exactly, return cropped RGBA array.

    - LOGFONTW(height=size, weight=700, CLEARTYPE_QUALITY, face)
    - 3-pass offset shadow (DamageShadowThickness=3, offset 2,2)
    - main text in damage color
    - alpha post-process: any pixel with RGB => alpha 255  ← the jaggies
    """
    dc_color = (0xE4, 0x91, 0x24)     # DamageColor #E49124
    dc_shadow = (0x00, 0x00, 0x00)     # DamageShadowColor #000000D9 (A lost by GDI pass)
    thick, ox, oy = 3, 2, 2

    canvas = size * 8
    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = canvas
    bmi.bmiHeader.biHeight = -canvas
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    pixels_ptr = ctypes.c_void_p()
    hbm = gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), DIB_RGB_COLORS,
                                 ctypes.byref(pixels_ptr), 0, 0)
    gdi32.SelectObject(hdc_mem, hbm)
    px = np.frombuffer((ctypes.c_byte * (canvas*canvas*4)).from_address(pixels_ptr.value),
                       dtype=np.uint8).reshape(canvas, canvas, 4)
    px.fill(0)

    lf = LOGFONTW()
    lf.lfHeight = size; lf.lfWeight = weight; lf.lfCharSet = 1
    lf.lfQuality = CLEARTYPE_QUALITY; lf.lfFaceName = face
    hfont = gdi32.CreateFontIndirectW(ctypes.byref(lf))
    gdi32.SelectObject(hdc_mem, hfont)
    gdi32.SetBkMode(hdc_mem, 1)  # TRANSPARENT

    cx = cy = canvas // 2
    shadow_ref = (dc_shadow[2] << 16) | (dc_shadow[1] << 8) | dc_shadow[0]
    gdi32.SetTextColor(hdc_mem, shadow_ref)
    for t in range(thick):
        r = RECT(cx + ox + t - 150, cy + oy + t - 60, cx + ox + t + 150, cy + oy + t + 60)
        user32.DrawTextW(hdc_mem, text, len(text), ctypes.byref(r), DT_CENTER | DT_VCENTER | DT_NOCLIP)
    main_ref = (dc_color[2] << 16) | (dc_color[1] << 8) | dc_color[0]
    gdi32.SetTextColor(hdc_mem, main_ref)
    r = RECT(cx - 150, cy - 60, cx + 150, cy + 60)
    user32.DrawTextW(hdc_mem, text, len(text), ctypes.byref(r), DT_CENTER | DT_VCENTER | DT_NOCLIP)
    gdi32.GdiFlush()

    # alpha post-process: exactly like the overlay does
    has_color = (px[:, :, 0].astype(np.int32) + px[:, :, 1].astype(np.int32) + px[:, :, 2].astype(np.int32)) > 0
    px[:, :, 3] = np.where(has_color, 255, 0).astype(np.uint8)

    # copy BEFORE deleting the DIB — px is a view into GDI-owned memory
    out = _crop(px).copy()
    gdi32.DeleteObject(hfont); gdi32.DeleteObject(hbm)
    gdi32.DeleteDC(hdc_mem); user32.ReleaseDC(0, hdc_screen)
    return out


def _crop(px: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(px[:, :, 3] > 0)
    if len(xs) == 0: return px[:1, :1]
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    pad = 4
    return px[max(0, y0-pad):min(px.shape[0], y1+pad), max(0, x0-pad):min(px.shape[1], x1+pad)]


def pillow_render(text: str, font_path: str, size: int = 70,
                  weight: int = 700) -> Image.Image:
    """Same colors/logic but FreeType-rendered with real antialiasing.

    Shadow drawn with #000000D9 (alpha 217) — translucent, edges graded.
    """
    font = ImageFont.truetype(font_path, size)
    try:  # both fonts are variable; set the weight axis to match GDI 700
        font.set_variation_by_axes([weight])
    except Exception:
        pass
    probe = font.getbbox(text)
    w = probe[2] - probe[0] + 80; h = probe[3] - probe[1] + 80
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, h // 2
    for t in range(3):  # same 3-pass offset shadow, now with alpha
        d.text((cx + 2 + t, cy + 2 + t), text, font=font, fill=(0, 0, 0, 217), anchor="mm")
    d.text((cx, cy), text, font=font, fill=(0xE4, 0x91, 0x24, 255), anchor="mm")
    return img.crop(img.getbbox())


def paste_center(canvas: Image.Image, img: Image.Image, cx: int, cy: int):
    canvas.alpha_composite(img, (cx - img.width // 2, cy - img.height // 2))


def label_font(size: int = 26):
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc"):
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except Exception: pass
    return ImageFont.load_default()


def main():
    os.makedirs(os.path.dirname(os.path.abspath(__file__)), exist_ok=True)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "render_compare.png")

    text = "487"
    gdi_img = Image.fromarray(gdi_render(text), "RGBA")
    pil_same = pillow_render(text, Bahnschrift)
    orbi_font = Orbitron if os.path.exists(Orbitron) else Bahnschrift
    pil_orbi = pillow_render(text, orbi_font, weight=700)

    zoom = 3
    W = 1560; H = 880
    canvas = Image.new("RGBA", (W, H), (0x14, 0x14, 0x1A, 255))
    lf = label_font(30); lf_small = label_font(20)
    d = ImageDraw.Draw(canvas)

    d.text((W // 2, 34), "Damage number render comparison  (FontSize=70, Color=#E49124)",
           font=lf, fill=(0xCC, 0xCC, 0xCC, 255), anchor="mm")
    cols = [
        ("GDI 现状  (当前插件)", "3-pass shadow + CLEARTYPE, alpha=255 硬边", gdi_img),
        ("Pillow 同字体  (Bahnschrift)", "FreeType 抗锯齿 + 半透明阴影", pil_same),
        ("Pillow + Orbitron  (字体评估)", "同上 + 现代粗体字型", pil_orbi),
    ]
    colw = W // 3
    for i, (title, sub, img) in enumerate(cols):
        cx = colw // 2 + i * colw
        d.text((cx, 92), title, font=lf, fill=(0xFF, 0xFF, 0xFF, 255), anchor="mm")
        d.text((cx, 128), sub, font=lf_small, fill=(0x88, 0x88, 0x88, 255), anchor="mm")
        paste_center(canvas, img, cx, 220)
        d.text((cx, 330), "3x 放大 (看边缘):", font=lf_small, fill=(0xAA, 0xAA, 0xAA, 255), anchor="mm")
        # zoom: nearest-neighbour so pixel structure stays visible
        z = img.resize((img.width * zoom, img.height * zoom), Image.NEAREST)
        paste_center(canvas, z, cx, 600)

    canvas.convert("RGB").save(out, optimize=True)
    print("saved:", out)
    print("gdi size:", gdi_img.size, "| pillow same:", pil_same.size, "| pillow orbitron:", pil_orbi.size)


if __name__ == "__main__":
    main()
