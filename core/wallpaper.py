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


def get_current_hash(meta):
    """Return the hash of the most recently applied wallpaper, if tracked."""
    recent = manager.get_recent(meta)
    for file_hash in reversed(recent):
        if isinstance(meta.get(file_hash), dict):
            return file_hash
    return None


def _choose_candidate(meta, candidates):
    """Choose a wallpaper candidate with configurable preference bias."""
    if not candidates:
        return None

    prefs = meta.get("__preferences__", {})
    if not isinstance(prefs, dict):
        prefs = {}
    bias_ratio = manager.get_preference_bias_ratio(manager.load_config())

    try:
        if random.random() < bias_ratio:
            weights = []
            for file_hash, _path in candidates:
                info = meta.get(file_hash, {})
                category = info.get("category", "general")
                weights.append(max(prefs.get(category, 1), 1))
            return random.choices(candidates, weights=weights, k=1)[0]
    except Exception:
        pass

    return random.choice(candidates)


def _get_replacement_candidates(meta, favorites_only, exclude_hash):
    candidates = manager.get_candidates(
        meta, favorites_only=favorites_only, exclude_recent=True
    )
    candidates = [item for item in candidates if item[0] != exclude_hash]

    if not candidates:
        manager.reset_used(meta)
        candidates = manager.get_candidates(
            meta, favorites_only=favorites_only, exclude_recent=True
        )
        candidates = [item for item in candidates if item[0] != exclude_hash]

    if not candidates:
        manager.remove_from_recent(meta, exclude_hash)
        candidates = manager.get_candidates(
            meta, favorites_only=favorites_only, exclude_recent=False
        )
        candidates = [item for item in candidates if item[0] != exclude_hash]

    return candidates


def switch_away_from_current(config, target_hash, meta):
    """
    If `target_hash` is the currently applied wallpaper, switch to another one.

    Mutates `meta` in place but does not save it; callers should persist after
    their own metadata changes complete.
    """
    if get_current_hash(meta) != target_hash:
        return False

    favorites_only = config.get("favorites_only", False)
    style = config.get("wallpaper_style", "Fill")
    candidates = _get_replacement_candidates(meta, favorites_only, target_hash)
    chosen = _choose_candidate(meta, candidates)
    if not chosen:
        return False

    chosen_hash, chosen_path = chosen
    set_wallpaper(chosen_path, style)
    meta[chosen_hash]["used_as_wallpaper"] = True
    meta[chosen_hash]["last_set"] = datetime.now().isoformat()
    manager.push_recent(meta, chosen_hash)
    return True


def refresh_current_wallpaper(config, file_hash, meta):
    """Re-apply the current wallpaper after its tracked path changes."""
    if get_current_hash(meta) != file_hash:
        return False

    path = meta.get(file_hash, {}).get("path", "")
    if not path or not os.path.exists(path):
        return False

    set_wallpaper(path, config.get("wallpaper_style", "Fill"))
    return True


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

    chosen_hash, chosen_path = _choose_candidate(meta, candidates)

    set_wallpaper(chosen_path, style)

    meta[chosen_hash]["used_as_wallpaper"] = True
    meta[chosen_hash]["last_set"]          = datetime.now().isoformat()
    manager.push_recent(meta, chosen_hash)
    manager.save_meta(meta)

    return True


def skip_to_next(config):
    """
    Change the desktop wallpaper to the next candidate WITHOUT marking it as
    used.  The rotation cycle is therefore not advanced — the skipped image
    will still appear in future normal rotations.

    Returns True if a wallpaper was shown, False if no images are available.
    """
    meta           = manager.load_meta()
    favorites_only = config.get("favorites_only", False)
    style          = config.get("wallpaper_style", "Fill")

    candidates = manager.get_candidates(meta, favorites_only=favorites_only, exclude_recent=True)

    if not candidates:
        # Fall back to all images (including recent) without resetting used flags
        candidates = manager.get_candidates(meta, favorites_only=favorites_only, exclude_recent=False)

    if not candidates:
        return False

    chosen = _choose_candidate(meta, candidates)
    if not chosen:
        return False

    _, chosen_path = chosen
    set_wallpaper(chosen_path, style)
    return True
