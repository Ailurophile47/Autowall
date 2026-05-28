"""
core/migration.py
Manages first-run installation into %LOCALAPPDATA%\\Autowall\\ and migration
from a portable executable. Called once at startup, before any UI initialises.

When frozen (Autowall.exe):
  - First run from a portable location → install to LOCALAPPDATA, relaunch, exit.
  - Subsequent runs from INSTALL_DIR → ensure dirs + updater exist, return.

When running as a script (dev mode) → no-op, returns immediately.
"""
import json
import logging
import os
import shutil
import subprocess
import sys

try:
    import winreg
    _WINREG = True
except ImportError:
    _WINREG = False

log = logging.getLogger(__name__)

APP_NAME    = "Autowall"
INSTALL_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP_NAME
)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


# ── Public path accessor ──────────────────────────────────────────────────────

def get_install_dir() -> str:
    return INSTALL_DIR


# ── Detection ─────────────────────────────────────────────────────────────────

def is_running_from_install_dir() -> bool:
    """Return True if already in INSTALL_DIR, or running as a dev script."""
    if not getattr(sys, "frozen", False):
        return True  # dev mode — treat as installed
    exe     = os.path.realpath(sys.executable)
    install = os.path.realpath(INSTALL_DIR)
    target  = os.path.join(install, "Autowall.exe")
    return exe == target or exe.startswith(install + os.sep)


# ── Directory setup ───────────────────────────────────────────────────────────

def _ensure_dirs():
    for sub in (
        "config",
        "Inbox",
        "Favorites",
        os.path.join("cache", "thumbnails"),
        "logs",
    ):
        os.makedirs(os.path.join(INSTALL_DIR, sub), exist_ok=True)


# ── updater.exe extraction from PyInstaller bundle ────────────────────────────

def _extract_updater():
    """
    Copy updater.exe from sys._MEIPASS (PyInstaller temp dir) to INSTALL_DIR.
    Idempotent: skips if already present and same size.
    No-op in dev mode (no _MEIPASS).
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    src = os.path.join(meipass, "updater.exe")
    dst = os.path.join(INSTALL_DIR, "updater.exe")
    if not os.path.exists(src):
        log.warning("updater.exe not found in PyInstaller bundle at %s", src)
        return
    if os.path.exists(dst):
        try:
            if os.path.getsize(src) == os.path.getsize(dst):
                return  # already up-to-date
        except OSError:
            pass
    try:
        shutil.copy2(src, dst)
        log.info("Extracted updater.exe → %s", dst)
    except OSError as e:
        log.warning("Could not extract updater.exe: %s", e)


# ── version.json ──────────────────────────────────────────────────────────────

def write_version_json(version_str: str):
    path = os.path.join(INSTALL_DIR, "version.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": version_str, "channel": "stable"}, f, indent=2)
    except OSError as e:
        log.warning("Could not write version.json: %s", e)


def read_installed_version() -> str:
    path = os.path.join(INSTALL_DIR, "version.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("version", "0.0.0")
    except (OSError, ValueError):
        return "0.0.0"


# ── User-data migration (portable → managed) ──────────────────────────────────

_MIGRATE = [
    ("config",        "config"),
    ("Inbox",         "Inbox"),
    ("Favorites",     "Favorites"),
    ("cache",         "cache"),
    ("metadata.json", "metadata.json"),
]


def _copy_user_data(src_base: str, dst_base: str):
    """
    Non-destructively merge user data from src_base into dst_base.
    Existing destination files are never overwritten.
    """
    for src_rel, dst_rel in _MIGRATE:
        src = os.path.join(src_base, src_rel)
        dst = os.path.join(dst_base, dst_rel)
        if not os.path.exists(src):
            continue
        try:
            if os.path.isdir(src):
                os.makedirs(dst, exist_ok=True)
                for name in os.listdir(src):
                    s = os.path.join(src, name)
                    d = os.path.join(dst, name)
                    if os.path.isfile(s) and not os.path.exists(d):
                        shutil.copy2(s, d)
            elif os.path.isfile(src) and not os.path.exists(dst):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
        except OSError as e:
            log.warning("Migration skipped %s: %s", src_rel, e)


# ── Autostart registry ────────────────────────────────────────────────────────

def update_autostart_path():
    """
    If an Autowall autostart entry exists in the registry, update its path
    to point at INSTALL_DIR so it remains valid across updates.
    """
    if not _WINREG:
        return
    new_exe = os.path.join(INSTALL_DIR, "Autowall.exe")
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        ) as key:
            try:
                val, _ = winreg.QueryValueEx(key, APP_NAME)
                if val and os.path.normcase(val) != os.path.normcase(new_exe):
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, new_exe)
                    log.info("Updated autostart registry → %s", new_exe)
            except FileNotFoundError:
                pass  # autostart not configured — nothing to update
    except OSError as e:
        log.debug("Could not update autostart registry: %s", e)


# ── Self-copy ─────────────────────────────────────────────────────────────────

def _copy_self(dst: str):
    """Copy the running exe (sys.executable) to dst. No-op in dev mode."""
    if not getattr(sys, "frozen", False):
        return
    try:
        shutil.copy2(sys.executable, dst)
        log.info("Copied self %s → %s", sys.executable, dst)
    except OSError as e:
        log.error("Failed to copy exe to install dir: %s", e)
        raise


# ── Public entry point ────────────────────────────────────────────────────────

def ensure_installed(version_str: str):
    """
    Call once at startup (before any UI or background threads).

    Already in INSTALL_DIR:
        Ensure directories + updater.exe exist; write version.json; return.

    Running portable (outside INSTALL_DIR):
        1. Create INSTALL_DIR structure.
        2. Copy self → INSTALL_DIR/Autowall.exe.
        3. Extract updater.exe from PyInstaller bundle.
        4. Migrate any existing user data from the portable location.
        5. Write version.json.
        6. Update autostart registry if previously configured.
        7. Relaunch from INSTALL_DIR then sys.exit() this process.
    """
    if is_running_from_install_dir():
        _ensure_dirs()
        _extract_updater()
        write_version_json(version_str)
        update_autostart_path()
        return

    # ── First-run: portable → managed install ─────────────────────────────
    log.info("First run — installing to %s", INSTALL_DIR)

    os.makedirs(INSTALL_DIR, exist_ok=True)
    _ensure_dirs()

    new_exe = os.path.join(INSTALL_DIR, "Autowall.exe")
    _copy_self(new_exe)
    _extract_updater()

    portable_base = os.path.dirname(sys.executable)
    _copy_user_data(portable_base, INSTALL_DIR)

    write_version_json(version_str)
    update_autostart_path()

    if os.path.exists(new_exe):
        log.info("Relaunching from %s", new_exe)
        subprocess.Popen(
            [new_exe],
            creationflags=subprocess.DETACHED_PROCESS | 0x08000000,  # CREATE_NO_WINDOW
            close_fds=True,
        )
    else:
        log.error("Install failed — %s not found after copy.", new_exe)

    sys.exit(0)
