"""
core/wallpaper.py
Sets the Windows desktop wallpaper. Picks the next candidate from metadata.
"""
import ctypes
import os
import random
import winreg
from datetime import datetime

from core import manager

_STYLE_MAP = {
    "Fill":    ("10", "0"),
    "Fit":     ("6",  "0"),
    "Stretch": ("2",  "0"),
    "Center":  ("0",  "0"),
    "Span":    ("22", "0"),
    "Tile":    ("0",  "1"),
}


def _set_style(style):
    ws, tw = _STYLE_MAP.get(style, _STYLE_MAP["Fill"])
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, "WallpaperStyle",  0, winreg.REG_SZ, ws)
        winreg.SetValueEx(key, "TileWallpaper",   0, winreg.REG_SZ, tw)


def set_wallpaper(path, style="Fill"):
    """Set `path` as the Windows desktop wallpaper."""
    _set_style(style)
    ctypes.windll.user32.SystemParametersInfoW(20, 0, path, 3)


def set_next(config):
    """
    Pick the next unused wallpaper and set it.
    Returns True if a wallpaper was set, False if no images are available.
    """
    meta           = manager.load_meta()
    favorites_only = config.get("favorites_only", False)
    style          = config.get("wallpaper_style", "Fill")

    candidates = manager.get_candidates(meta, favorites_only=favorites_only, exclude_recent=True)

    if not candidates:
        # All images used — reset the cycle
        manager.reset_used(meta)
        candidates = manager.get_candidates(meta, favorites_only=favorites_only, exclude_recent=True)

    if not candidates:
        # Still nothing — too few images for the recent window; clear it
        meta["__recent__"] = []
        candidates = manager.get_candidates(meta, favorites_only=favorites_only, exclude_recent=False)

    if not candidates:
        return False

    chosen_hash, chosen_path = random.choice(candidates)

    set_wallpaper(chosen_path, style)

    meta[chosen_hash]["used_as_wallpaper"] = True
    meta[chosen_hash]["last_set"]          = datetime.now().isoformat()
    manager.push_recent(meta, chosen_hash)
    manager.save_meta(meta)

    return True
