"""
core/manager.py
Handles all metadata.json and config.json operations.
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta

# ── Paths ──────────────────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INBOX = os.path.join(BASE_DIR, "Inbox")
FAV   = os.path.join(BASE_DIR, "Favorites")
META  = os.path.join(BASE_DIR, "metadata.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config", "config.json")

RECENT_LIMIT = 5

_DEFAULT_CONFIG = {
    "unsplash_key":    "K1f80wXotEuUEgIfNOuIwfxniCfMBuIoNGHnHAvv32I",
    "interval_hours":  24,
    "categories":      ["nature", "dark", "minimal", "space", "landscape"],
    "min_resolution":  "1080p",
    "wallpaper_style": "Fill",
    "favorites_only":  False,
    "autostart":       False,
}

# ── Config ─────────────────────────────────────────────────────────────────────

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return dict(_DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.loads(f.read().strip() or "{}")
        cfg = dict(_DEFAULT_CONFIG)
        cfg.update(data)
        return cfg
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULT_CONFIG)


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

# ── Metadata ───────────────────────────────────────────────────────────────────

def load_meta():
    if not os.path.exists(META):
        return {}
    try:
        with open(META, "r", encoding="utf-8") as f:
            data = json.loads(f.read().strip() or "{}")
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_meta(data):
    with open(META, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def hash_file(path):
    digest = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_unique_path(folder, filename):
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(folder, filename)
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{base}_{counter}{ext}")
        counter += 1
    return candidate


def register_file(path):
    """Add a file to metadata if not already tracked."""
    if not os.path.isfile(path):
        return
    meta = load_meta()
    file_hash = hash_file(path)
    if file_hash in meta:
        if meta[file_hash].get("path") != path:
            meta[file_hash]["path"] = path
            save_meta(meta)
        return
    meta[file_hash] = {
        "path":             path,
        "date":             datetime.now().isoformat(),
        "liked":            False,
        "favorite":         False,
        "reviewed":         False,
        "used_as_wallpaper": False,
    }
    save_meta(meta)


def register_all_inbox():
    """Register every image in Inbox that isn't tracked yet."""
    for f in os.listdir(INBOX):
        p = os.path.join(INBOX, f)
        if os.path.isfile(p) and f.lower().endswith((".jpg", ".jpeg", ".png")):
            register_file(p)


def cleanup():
    """Delete Inbox images older than 15 days and remove their metadata entries."""
    meta = load_meta()
    now = datetime.now()
    changed = False

    for file_hash, info in list(meta.items()):
        if not isinstance(info, dict):
            continue
        if info.get("favorite"):
            continue
        path, date_text = info.get("path"), info.get("date")
        if not path or not date_text:
            del meta[file_hash]
            changed = True
            continue
        try:
            created = datetime.fromisoformat(date_text)
        except ValueError:
            created = now - timedelta(days=16)
        if now - created > timedelta(days=15):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    continue
            del meta[file_hash]
            changed = True

    if changed:
        save_meta(meta)

# ── Wallpaper candidate selection ──────────────────────────────────────────────

def get_recent(meta):
    return list(meta.get("__recent__", []))


def push_recent(meta, file_hash):
    recent = get_recent(meta)
    if file_hash in recent:
        recent.remove(file_hash)
    recent.append(file_hash)
    meta["__recent__"] = recent[-RECENT_LIMIT:]


def get_candidates(meta, favorites_only=False, exclude_recent=True):
    """Return eligible (hash, path) pairs for wallpaper selection."""
    if favorites_only:
        allowed = (os.path.normcase(FAV),)
    else:
        allowed = (os.path.normcase(FAV), os.path.normcase(INBOX))

    recent = set(get_recent(meta)) if exclude_recent else set()
    candidates = []

    for file_hash, info in meta.items():
        if not isinstance(info, dict):
            continue
        path = info.get("path", "")
        if not path or not os.path.exists(path):
            continue
        if not any(os.path.normcase(path).startswith(d) for d in allowed):
            continue
        if info.get("used_as_wallpaper", False):
            continue
        if file_hash in recent:
            continue
        candidates.append((file_hash, path))

    return candidates


def reset_used(meta):
    """Reset used_as_wallpaper flag for all Inbox + Favorites images."""
    allowed = (os.path.normcase(FAV), os.path.normcase(INBOX))
    for info in meta.values():
        if not isinstance(info, dict):
            continue
        if any(os.path.normcase(info.get("path", "")).startswith(d) for d in allowed):
            info["used_as_wallpaper"] = False


def res_to_min_width(label):
    return {"1080p": 1920, "2K": 2560, "4K": 3840}.get(label, 1920)


def ensure_setup():
    os.makedirs(INBOX, exist_ok=True)
    os.makedirs(FAV, exist_ok=True)
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    if not os.path.exists(META):
        save_meta({})
    if not os.path.exists(CONFIG_FILE):
        save_config(_DEFAULT_CONFIG)
