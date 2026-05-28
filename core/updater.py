"""
core/updater.py
Background update checker and download manager.

Responsibilities:
  - Poll GitHub Releases API on a daemon thread every CHECK_INTERVAL_HOURS
  - Parse semantic versions (MAJOR.MINOR.PATCH)
  - Stream-download new Autowall.exe to a temp path with progress callbacks
  - Verify SHA256 integrity against SHA256SUMS.txt published alongside release
  - Orchestrate the handoff to updater.exe for atomic file replacement
  - Coordinate graceful shutdown of the main app before updater takes over

This module does NOT touch files on disk directly — that is updater.exe's job.
"""
import hashlib
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import requests

log = logging.getLogger(__name__)

CHECK_INTERVAL_HOURS = 4    # hours between GitHub polls after the first check
DOWNLOAD_TIMEOUT_S   = 120  # seconds before giving up on a stalled download chunk
_STARTUP_DELAY_S     = 90   # seconds after launch before first update check


# ── Data container ────────────────────────────────────────────────────────────

@dataclass
class UpdateInfo:
    version:         str
    download_url:    str
    sha256_url:      Optional[str] = None
    release_notes:   str           = ""
    expected_sha256: Optional[str] = None  # filled after fetching SHA256SUMS.txt


# ── Semantic version parsing ──────────────────────────────────────────────────

def parse_version(s: str) -> tuple:
    """
    Parse 'v2.1.0' or '2.1.0' into (2, 1, 0).
    Pads missing components with 0.  Returns (0, 0, 0) on parse error.
    """
    s = s.lstrip("v").strip()
    try:
        parts = [int(x) for x in s.split(".")]
    except ValueError:
        return (0, 0, 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _ver_str(t: tuple) -> str:
    return ".".join(str(x) for x in t)


# ── GitHub Releases API ───────────────────────────────────────────────────────

def _fetch_release(repo: str, timeout: int = 10) -> Optional[dict]:
    url     = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {
        "User-Agent": "Autowall-Updater/1.0",
        "Accept":     "application/vnd.github.v3+json",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 403:
            log.warning("GitHub API rate-limited; skipping update check.")
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        log.debug("GitHub API error: %s", e)
        return None


def _fetch_sha256sums(url: str) -> dict:
    """
    Download and parse SHA256SUMS.txt.
    Standard sha256sum format: '<hash>  <filename>'.
    Returns {lowercase_filename: lowercase_hash}.
    """
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        result = {}
        for line in resp.text.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2:
                result[parts[-1].lower()] = parts[0].lower()
        return result
    except requests.RequestException as e:
        log.debug("Failed to fetch SHA256SUMS.txt: %s", e)
        return {}


def check_for_update(repo: str, current_version: str,
                     allow_prerelease: bool = False) -> Optional[UpdateInfo]:
    """
    Query GitHub and return UpdateInfo if a newer version exists.
    Returns None if already up-to-date, offline, or on any error.
    """
    data = _fetch_release(repo)
    if not data:
        return None

    if data.get("prerelease") and not allow_prerelease:
        log.debug("Latest release is a prerelease — skipping.")
        return None

    tag     = data.get("tag_name", "")
    latest  = parse_version(tag)
    current = parse_version(current_version)

    if latest <= current:
        log.debug("Already up to date (current=%s, remote=%s).", current_version, tag)
        return None

    log.info("Update available: %s → %s", current_version, tag)

    exe_url    = None
    sha256_url = None
    for asset in data.get("assets", []):
        name = asset.get("name", "").lower()
        if name == "autowall.exe":
            exe_url = asset["browser_download_url"]
        elif name == "sha256sums.txt":
            sha256_url = asset["browser_download_url"]

    if not exe_url:
        log.warning("No Autowall.exe asset in release %s.", tag)
        return None

    info = UpdateInfo(
        version=_ver_str(latest),
        download_url=exe_url,
        sha256_url=sha256_url,
        release_notes=data.get("body", ""),
    )

    if sha256_url:
        sums = _fetch_sha256sums(sha256_url)
        info.expected_sha256 = sums.get("autowall.exe")
        if info.expected_sha256:
            log.debug("Expected SHA256 for Autowall.exe: %s", info.expected_sha256)
        else:
            log.warning("SHA256SUMS.txt present but no Autowall.exe entry found.")

    return info


# ── Download + integrity verification ────────────────────────────────────────

def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def download_update(url: str, dest: str,
                    progress_cb: Optional[Callable[[float], None]] = None) -> bool:
    """
    Stream-download `url` to `dest`.

    Writes to `dest + '.tmp'` first; renames on completion (corruption-safe).
    Cleans up the .tmp file on failure.
    `progress_cb(fraction)` is called with 0.0–1.0 during transfer.
    Returns True on success.
    """
    tmp = dest + ".tmp"
    try:
        resp = requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT_S)
        resp.raise_for_status()
        total      = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb and total:
                        try:
                            progress_cb(downloaded / total)
                        except Exception:
                            pass

        if os.path.exists(dest):
            os.remove(dest)
        os.rename(tmp, dest)
        log.info("Downloaded %d bytes → %s", downloaded, dest)
        return True

    except Exception as e:
        log.error("Download failed: %s", e)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False


def verify_integrity(path: str, expected: Optional[str]) -> bool:
    """
    Verify SHA256 of file at `path`.
    If no expected hash is provided, logs a warning and returns True
    so that updates without a published checksum still proceed.
    """
    if not os.path.exists(path):
        log.error("Integrity check: file not found: %s", path)
        return False
    if not expected:
        log.warning("No SHA256 checksum available — proceeding without verification.")
        return True
    actual = _sha256_file(path)
    if actual == expected.lower():
        log.info("Integrity OK: %s", actual)
        return True
    log.error("Integrity FAIL  expected=%s  actual=%s", expected, actual)
    return False


# ── Updater handoff ───────────────────────────────────────────────────────────

def _find_updater_exe() -> Optional[str]:
    from core.migration import get_install_dir
    path = os.path.join(get_install_dir(), "updater.exe")
    return path if os.path.exists(path) else None


def get_temp_download_path() -> str:
    """Stable temp-dir path for the downloaded update. Same across calls."""
    return os.path.join(tempfile.gettempdir(), "Autowall_update.exe")


def launch_updater_and_exit(state: dict, new_exe_path: str) -> None:
    """
    Spawn updater.exe with all required arguments, then shut the main app down.

    updater.exe will:
      1. Wait for our PID to disappear.
      2. Back up the current Autowall.exe.
      3. Move new_exe_path over Autowall.exe.
      4. Relaunch Autowall.exe.
      5. On failure: restore backup, show error dialog.

    This function signals all threads and destroys the UI; callers should
    not perform any further work after calling it.
    """
    from core.migration import get_install_dir
    install_dir = get_install_dir()
    updater_exe = _find_updater_exe()

    if not updater_exe:
        log.error("updater.exe not found in %s — cannot apply update.", install_dir)
        return

    target  = os.path.join(install_dir, "Autowall.exe")
    backup  = os.path.join(install_dir, "Autowall.exe.bak")
    logfile = os.path.join(install_dir, "logs", "updater.log")

    cmd = [
        updater_exe,
        "--pid",      str(os.getpid()),
        "--new-exe",  new_exe_path,
        "--target",   target,
        "--backup",   backup,
        "--relaunch", target,
        "--log-file", logfile,
    ]
    log.info("Launching updater: %s", " ".join(cmd))

    try:
        subprocess.Popen(
            cmd,
            creationflags=subprocess.DETACHED_PROCESS | 0x08000000,  # CREATE_NO_WINDOW
            close_fds=True,
        )
    except OSError as e:
        log.error("Failed to launch updater.exe: %s", e)
        return

    # Signal all threads to stop
    state["quitting"] = True
    state["stop"].set()

    # Destroy GUI (must be called on the main tkinter thread)
    root = state.get("root")
    if root:
        try:
            root.after(0, root.destroy)
        except Exception:
            pass

    # Stop the tray icon
    icon = state.get("icon")
    if icon:
        try:
            icon.stop()
        except Exception:
            pass


# ── Background update checker ─────────────────────────────────────────────────

class UpdateChecker:
    """
    Daemon thread that periodically checks GitHub for newer releases,
    silently downloads and verifies the update, then notifies the UI.

    Status machine:
        idle             → no update found; waiting until next poll interval
        checking         → querying GitHub API
        update_available → newer version found; download starting
        downloading      → transfer in progress
        ready            → verified exe on disk; waiting for user to install
        error            → last operation failed; will retry next cycle
    """

    def __init__(self, state: dict, repo: str, current_version: str,
                 on_update_available: Optional[Callable] = None):
        self._state           = state
        self._repo            = repo
        self._current_version = current_version
        self._on_update       = on_update_available   # optional UI callback
        self._info: Optional[UpdateInfo] = None
        self._dl_path: Optional[str]    = None
        self._status          = "idle"
        self._lock            = threading.Lock()

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def update_info(self) -> Optional[UpdateInfo]:
        with self._lock:
            return self._info

    @property
    def downloaded_path(self) -> Optional[str]:
        with self._lock:
            return self._dl_path

    def start(self):
        t = threading.Thread(target=self._loop, daemon=True, name="update-checker")
        t.start()

    def apply_update(self):
        """Call from UI (tray menu) to perform the install handoff immediately."""
        with self._lock:
            path = self._dl_path
        if path and os.path.exists(path):
            launch_updater_and_exit(self._state, path)
        else:
            log.warning("apply_update: no ready download — triggering fresh check.")
            threading.Thread(target=self._check_cycle, daemon=True).start()

    # ── Internal loop ────────────────────────────────────────────────────────

    def _set_status(self, s: str):
        with self._lock:
            self._status = s
        log.debug("UpdateChecker → %s", s)

    def _loop(self):
        # Wait after startup so the main app has time to settle
        for _ in range(_STARTUP_DELAY_S):
            if self._state.get("quitting"):
                return
            time.sleep(1)

        while not self._state.get("quitting"):
            try:
                self._check_cycle()
            except Exception:
                log.exception("Unhandled error in update checker.")
                self._set_status("error")

            # Sleep between polls, checking for quit signal every 60 s
            for _ in range(CHECK_INTERVAL_HOURS * 60):
                if self._state.get("quitting"):
                    return
                time.sleep(60)

    def _check_cycle(self):
        self._set_status("checking")
        info = check_for_update(self._repo, self._current_version)
        if info is None:
            self._set_status("idle")
            return

        with self._lock:
            self._info = info
        self._set_status("update_available")

        # Notify UI (on tkinter main thread if possible)
        if self._on_update:
            self._on_main(lambda: self._on_update(info))

        # Tray notification: download starting
        self._on_main(lambda: self._tray_notify(
            f"Autowall v{info.version} available — downloading in background.",
            "Autowall Update",
        ))

        self._download_and_verify(info)

    def _download_and_verify(self, info: UpdateInfo):
        self._set_status("downloading")
        dest = get_temp_download_path()

        ok = download_update(
            info.download_url, dest,
            progress_cb=lambda f: log.debug("Download: %.0f%%", f * 100),
        )
        if not ok:
            self._set_status("error")
            return

        if not verify_integrity(dest, info.expected_sha256):
            try:
                os.remove(dest)
            except OSError:
                pass
            self._set_status("error")
            return

        with self._lock:
            self._dl_path = dest
        self._set_status("ready")
        log.info("Update v%s ready at %s", info.version, dest)

        # Tray notification: ready to install
        self._on_main(lambda: self._tray_notify(
            f"Autowall v{info.version} ready — click 'Install Update & Restart' in the tray.",
            "Autowall Update",
        ))

    def _tray_notify(self, message: str, title: str):
        icon = self._state.get("icon")
        if icon:
            try:
                icon.notify(message, title)
            except Exception:
                pass

    def _on_main(self, fn: Callable):
        """Schedule fn() on the tkinter main thread; fall back to direct call."""
        root = self._state.get("root")
        if root:
            try:
                root.after(0, fn)
                return
            except Exception:
                pass
        try:
            fn()
        except Exception:
            pass
