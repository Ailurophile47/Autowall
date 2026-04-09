"""
build_exe.py
Run this script once to:
  1. Convert assets/logo.png → assets/logo.ico  (multi-size Windows icon)
  2. Invoke PyInstaller to produce dist/Autowall.exe

Usage:
    py build_exe.py
"""
import os
import sys
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
PNG  = os.path.join(ROOT, "assets", "logo.png")
ICO  = os.path.join(ROOT, "assets", "logo.ico")


def make_ico():
    from PIL import Image
    img = Image.open(PNG).convert("RGBA")
    sizes = [16, 32, 48, 64, 128, 256]
    icons = [img.resize((s, s), Image.LANCZOS) for s in sizes]
    icons[0].save(ICO, format="ICO", sizes=[(s, s) for s in sizes],
                  append_images=icons[1:])
    print(f"[ok] icon written → {ICO}")


def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name", "Autowall",
        "--icon", ICO,
        # pystray needs its win32 backend bundled explicitly
        "--hidden-import", "pystray._win32",
        "--hidden-import", "PIL._tkinter_finder",
        # collect the whole pystray + PIL packages to avoid missing-module errors
        "--collect-all", "pystray",
        "--collect-all", "PIL",
        os.path.join(ROOT, "main.py"),
    ]
    print("[build] running PyInstaller …")
    subprocess.check_call(cmd, cwd=ROOT)
    exe = os.path.join(ROOT, "dist", "Autowall.exe")
    print(f"\n[done] executable → {exe}")


if __name__ == "__main__":
    if not os.path.exists(PNG):
        sys.exit(
            "ERROR: assets/logo.png not found.\n"
            "Save the Autowall logo PNG to assets/logo.png and re-run."
        )
    make_ico()
    build()
