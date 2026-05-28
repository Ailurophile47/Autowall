"""
updater_main.py — Autowall Updater process.

Compiled into updater.exe by PyInstaller (--onefile --noconsole --name=updater).

IMPORTANT: This file has ZERO non-stdlib imports so the resulting binary
stays tiny (stdlib-only PyInstaller bundle ≈ 6 MB vs full app ≈ 50 MB).

Invocation (by the main app via subprocess.Popen before it exits):
    updater.exe
        --pid      <main_app_pid>          PID to wait for before replacing files
        --new-exe  <downloaded_exe_path>   Path to the verified new Autowall.exe
        --target   <installed_exe_path>    Autowall.exe to be replaced
        --backup   <backup_path>           Where to save Autowall.exe.bak
        --relaunch <exe_to_launch>         Usually same as --target
        --log-file <log_path>              Optional; defaults next to --target

Sequence:
    1. Wait up to 30 s for --pid to exit (WinAPI WaitForSingleObject)
    2. Back up --target → --backup
    3. shutil.move --new-exe → --target
    4. Relaunch --relaunch detached
    5. On any failure: restore --backup, show error dialog, relaunch old version
"""
import argparse
import ctypes
import ctypes.wintypes
import logging
import os
import shutil
import subprocess
import sys
import time


# ── Logging ───────────────────────────────────────────────────────────────────

def _setup_logging(log_path: str):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)-8s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8", mode="a"),
        ],
    )


# ── Windows process wait ──────────────────────────────────────────────────────

def _wait_for_pid(pid: int, timeout_ms: int = 30_000) -> bool:
    """
    Block until `pid` exits using WinAPI WaitForSingleObject.

    Opens with SYNCHRONIZE-only rights (no admin required).
    If OpenProcess returns NULL the process has already exited — return True.
    """
    SYNCHRONIZE   = 0x00100000
    WAIT_OBJECT_0 = 0x00000000
    WAIT_TIMEOUT  = 0x00000102

    k32    = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = k32.OpenProcess(SYNCHRONIZE, False, pid)

    if handle == 0:
        logging.info("OpenProcess(%d) returned NULL — process already gone.", pid)
        return True

    try:
        result = k32.WaitForSingleObject(handle, timeout_ms)
        if result == WAIT_OBJECT_0:
            logging.info("Process %d exited cleanly.", pid)
            return True
        if result == WAIT_TIMEOUT:
            logging.warning("Timed out waiting for process %d.", pid)
            return False
        logging.error("WaitForSingleObject → 0x%X for pid %d.", result, pid)
        return False
    finally:
        k32.CloseHandle(handle)


# ── Error dialog (no tkinter dependency) ─────────────────────────────────────

def _msgbox(message: str):
    """Show a Windows error dialog. Falls back silently if ctypes call fails."""
    try:
        ctypes.windll.user32.MessageBoxW(
            0, message, "Autowall Updater", 0x10  # MB_ICONERROR
        )
    except Exception:
        pass


# ── File replacement ──────────────────────────────────────────────────────────

def _replace(new_exe: str, target: str, backup: str) -> bool:
    """
    Safely replace `target` with `new_exe`.

    Step 1 — copy target → backup (rollback point).
    Step 2 — shutil.move new_exe → target.
    On step-2 failure, restore from backup.
    Returns True on full success.
    """
    if os.path.exists(target):
        try:
            shutil.copy2(target, backup)
            logging.info("Backed up %s → %s", target, backup)
        except OSError as e:
            logging.error("Backup failed: %s", e)
            return False

    try:
        shutil.move(new_exe, target)
        logging.info("Installed new exe at %s", target)
        return True
    except OSError as e:
        logging.error("Replace failed: %s", e)
        # Rollback
        if os.path.exists(backup):
            try:
                shutil.copy2(backup, target)
                logging.info("Rolled back from backup.")
            except OSError as re:
                logging.error("Rollback also failed: %s", re)
        return False


# ── Relaunch ──────────────────────────────────────────────────────────────────

def _relaunch(exe_path: str):
    try:
        subprocess.Popen(
            [exe_path],
            creationflags=subprocess.DETACHED_PROCESS | 0x08000000,  # CREATE_NO_WINDOW
            close_fds=True,
        )
        logging.info("Relaunched %s.", exe_path)
    except OSError as e:
        logging.error("Relaunch failed: %s", e)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Autowall updater")
    parser.add_argument("--pid",      type=int, required=True)
    parser.add_argument("--new-exe",  required=True)
    parser.add_argument("--target",   required=True)
    parser.add_argument("--backup",   required=True)
    parser.add_argument("--relaunch", required=True)
    parser.add_argument("--log-file", default=None)
    args = parser.parse_args()

    log_file = args.log_file or os.path.join(
        os.path.dirname(args.target), "logs", "updater.log"
    )
    _setup_logging(log_file)
    logging.info(
        "=== Updater started | pid=%d | new=%s | target=%s ===",
        args.pid, args.new_exe, args.target,
    )

    # 1 — Wait for main app to exit
    if not _wait_for_pid(args.pid, timeout_ms=30_000):
        msg = (
            f"Autowall (PID {args.pid}) did not exit within 30 s.\n"
            "Please close Autowall manually, then run it again to apply the update."
        )
        logging.error(msg)
        _msgbox(msg)
        sys.exit(1)

    # Brief pause to allow the OS to release file handles
    time.sleep(0.75)

    # 2 — Verify downloaded file exists
    if not os.path.exists(args.new_exe):
        msg = f"Downloaded update not found:\n{args.new_exe}"
        logging.error(msg)
        _msgbox(msg)
        if os.path.exists(args.target):
            _relaunch(args.target)
        sys.exit(1)

    # 3 — Perform replacement
    if not _replace(args.new_exe, args.target, args.backup):
        _msgbox(
            "Update failed — the previous version has been restored.\n"
            f"See log for details:\n{log_file}"
        )
        for candidate in (args.target, args.backup):
            if os.path.exists(candidate):
                _relaunch(candidate)
                break
        sys.exit(1)

    # 4 — Clean up any leftover temp files
    for leftover in (args.new_exe, args.new_exe + ".tmp"):
        try:
            if os.path.exists(leftover):
                os.remove(leftover)
        except OSError:
            pass

    # 5 — Relaunch the updated app
    _relaunch(args.relaunch)
    logging.info("=== Update complete ===")
    sys.exit(0)


if __name__ == "__main__":
    main()
