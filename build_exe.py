"""
build_exe.py
Build script for Autowall release artifacts.

Produces (in dist/):
    updater.exe      — tiny standalone updater process (stdlib-only, ~6 MB)
    Autowall.exe     — main app with updater.exe bundled inside (~50 MB)
    SHA256SUMS.txt   — checksums for the GitHub release page

Usage:
    py build_exe.py            # full build (converts logo.png → logo.ico first)
    py build_exe.py --skip-ico # skip PNG→ICO conversion (use existing logo.ico)

Build order matters: updater.exe must exist before Autowall.exe is built,
because Autowall.exe bundles updater.exe via --add-data so that migration.py
can extract it from sys._MEIPASS on the user's machine at first run.
"""
import argparse
import hashlib
import os
import subprocess
import sys

ROOT        = os.path.dirname(os.path.abspath(__file__))
ASSETS      = os.path.join(ROOT, "assets")
PNG         = os.path.join(ASSETS, "logo.png")
ICO         = os.path.join(ASSETS, "logo.ico")
DIST        = os.path.join(ROOT, "dist")
UPDATER_SRC = os.path.join(ROOT, "updater_main.py")
UPDATER_EXE = os.path.join(DIST, "updater.exe")
MAIN_EXE    = os.path.join(DIST, "Autowall.exe")
SHA256_OUT  = os.path.join(DIST, "SHA256SUMS.txt")

# PyInstaller on Windows uses ';' as the source:dest separator in --add-data
_SEP = ";" if sys.platform == "win32" else ":"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_pyinstaller(*args):
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", *args]
    print(f"\n[pyinstaller] {' '.join(args[:6])} …")
    subprocess.check_call(cmd, cwd=ROOT)


def _size_mb(path: str) -> str:
    return f"{os.path.getsize(path) / 1024 / 1024:.1f} MB"


# ── Steps ─────────────────────────────────────────────────────────────────────

def make_ico():
    """Convert assets/logo.png to a multi-size assets/logo.ico."""
    from PIL import Image
    img   = Image.open(PNG).convert("RGBA")
    sizes = [16, 32, 48, 64, 128, 256]
    icons = [img.resize((s, s), Image.LANCZOS) for s in sizes]
    icons[0].save(ICO, format="ICO", sizes=[(s, s) for s in sizes],
                  append_images=icons[1:])
    print(f"[ok] {ICO}")


def build_updater():
    """
    Build dist/updater.exe from updater_main.py.

    No PIL, pystray, or requests — purely stdlib.
    This keeps the binary small and the update process dependency-free.
    """
    _run_pyinstaller(
        "--onefile",
        "--noconsole",
        "--name", "updater",
        "--icon", ICO,
        UPDATER_SRC,
    )
    if not os.path.exists(UPDATER_EXE):
        sys.exit("ERROR: dist/updater.exe was not produced — check PyInstaller output above.")
    print(f"[ok] {UPDATER_EXE}  ({_size_mb(UPDATER_EXE)})")


def build_main():
    """
    Build dist/Autowall.exe from main.py.

    Bundles updater.exe as internal data (--add-data) so the user only needs
    to download one file.  migration.py extracts it to LOCALAPPDATA\\Autowall\\
    on first run via sys._MEIPASS.
    """
    if not os.path.exists(UPDATER_EXE):
        sys.exit(
            "ERROR: dist/updater.exe not found.\n"
            "Run build_updater() (or the full build) before build_main()."
        )

    _run_pyinstaller(
        "--onefile",
        "--noconsole",
        "--name", "Autowall",
        "--icon", ICO,
        # Bundle updater.exe — extracted to sys._MEIPASS root at runtime
        "--add-data", f"dist{os.sep}updater.exe{_SEP}.",
        # Bundle logo assets for window/tray icon
        "--add-data", f"assets{os.sep}logo.ico{_SEP}assets",
        "--add-data", f"assets{os.sep}logo.png{_SEP}assets",
        # pystray needs its win32 backend collected explicitly
        "--hidden-import", "pystray._win32",
        "--hidden-import", "PIL._tkinter_finder",
        "--collect-all", "pystray",
        "--collect-all", "PIL",
        os.path.join(ROOT, "main.py"),
    )
    if not os.path.exists(MAIN_EXE):
        sys.exit("ERROR: dist/Autowall.exe was not produced — check PyInstaller output above.")
    print(f"[ok] {MAIN_EXE}  ({_size_mb(MAIN_EXE)})")


def write_sha256sums():
    """
    Write dist/SHA256SUMS.txt in standard sha256sum format.
    Upload this file alongside Autowall.exe to the GitHub Release so the
    in-app updater can verify downloads before installing them.
    """
    lines = []
    for name, path in [("Autowall.exe", MAIN_EXE), ("updater.exe", UPDATER_EXE)]:
        if os.path.exists(path):
            lines.append(f"{_sha256(path)}  {name}")

    with open(SHA256_OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\n[ok] {SHA256_OUT}")
    for line in lines:
        print(f"     {line}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Build Autowall release artifacts")
    parser.add_argument(
        "--skip-ico", action="store_true",
        help="Skip PNG→ICO conversion and use the existing assets/logo.ico",
    )
    args = parser.parse_args()

    if not args.skip_ico:
        if not os.path.exists(PNG):
            sys.exit("ERROR: assets/logo.png not found.  Add your logo and re-run.")
        make_ico()
    else:
        if not os.path.exists(ICO):
            sys.exit("ERROR: assets/logo.ico not found.  Run without --skip-ico first.")

    build_updater()
    build_main()
    write_sha256sums()

    print("\n=== Release artifacts ===")
    for name in ("Autowall.exe", "updater.exe", "SHA256SUMS.txt"):
        p = os.path.join(DIST, name)
        if os.path.exists(p):
            size = f"  ({_size_mb(p)})" if name.endswith(".exe") else ""
            print(f"  dist/{name}{size}")

    print("\nUpload Autowall.exe and SHA256SUMS.txt to GitHub Releases.")
    print("The in-app updater will verify the download against SHA256SUMS.txt.")


if __name__ == "__main__":
    main()
