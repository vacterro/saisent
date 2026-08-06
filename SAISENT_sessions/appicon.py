"""The app's face: window, taskbar and tray, from one source image.

The tray code in the core sets `NIF_MESSAGE | NIF_TIP` and no `NIF_ICON`, so
the notification area got an entry with nothing drawn in it -- present, but
invisible unless you knew where to hover. Fixed here rather than in the core,
which is shared with the legacy console.

A `.ico` is generated from the source PNG once and rebuilt only when the PNG
is newer, because Windows wants a real multi-resolution icon file and Tk's
`iconbitmap` wants a path, not a bitmap.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

# Sizes Windows actually asks for: tray and small title bar at the bottom,
# alt-tab and the taskbar in the middle, shell previews at the top.
ICON_SIZES = ((16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256))

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040


def ensure_ico(source: str | os.PathLike, target: str | os.PathLike) -> str:
    """Build `target` from `source` when needed; return the usable path.

    Returns "" when the source is missing or Pillow cannot read it -- a missing
    icon is a cosmetic problem and must never stop the app from starting.
    """
    source_path = Path(source)
    target_path = Path(target)
    if not source_path.exists():
        return str(target_path) if target_path.exists() else ""
    try:
        fresh = (
            target_path.exists()
            and target_path.stat().st_mtime >= source_path.stat().st_mtime
        )
    except OSError:
        fresh = False
    if fresh:
        return str(target_path)
    try:
        from PIL import Image

        image = Image.open(source_path).convert("RGBA")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(target_path, format="ICO", sizes=list(ICON_SIZES))
    except Exception:
        return str(target_path) if target_path.exists() else ""
    return str(target_path)


def load_hicon(ico_path: str | os.PathLike, size: int = 16):
    """An HICON at the requested size, or None."""
    if not ico_path or not Path(ico_path).exists() or os.name != "nt":
        return None
    user32 = ctypes.windll.user32
    user32.LoadImageW.restype = ctypes.c_void_p
    handle = user32.LoadImageW(
        None, str(ico_path), IMAGE_ICON, int(size), int(size), LR_LOADFROMFILE
    )
    return handle or None


def apply_window_icon(window, ico_path: str | os.PathLike) -> bool:
    """Title bar, alt-tab and taskbar. False when it could not be set."""
    if not ico_path or not Path(ico_path).exists():
        return False
    try:
        window.iconbitmap(default=str(ico_path))
    except Exception:
        try:
            window.iconbitmap(str(ico_path))
        except Exception:
            return False
    return True


def make_tray_class(base):
    """A `TrayIcon` that actually draws something.

    Subclassed instead of edited in place: the core module is shared with the
    legacy console, and this only adds the `NIF_ICON` the original omits.
    """

    class TrayIconWithImage(base):
        NIF_ICON = 0x00000002

        def __init__(self, *args, ico_path: str = "", **kwargs):
            super().__init__(*args, **kwargs)
            self.ico_path = ico_path
            self._hicon = load_hicon(ico_path, 16)

        def _nid(self):
            nid = super()._nid()
            if self._hicon:
                nid.uFlags |= self.NIF_ICON
                nid.hIcon = self._hicon
            return nid

    return TrayIconWithImage
