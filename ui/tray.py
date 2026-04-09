"""
ui/tray.py
System tray icon + menu using pystray.
All non-GUI tray actions run directly; GUI windows are spawned as subprocesses.
"""
import os
import sys
import subprocess

import threading

import pystray
from PIL import Image, ImageDraw

from core import manager, wallpaper, downloader


def _create_icon_image():
    """Generate a 64×64 tray icon with PIL (no file needed)."""
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Dark background circle
    draw.ellipse([1, 1, 62, 62], fill=(16, 20, 24, 240))

    # Monitor body
    draw.rectangle([9, 13, 55, 41], fill=(22, 32, 44, 255),
                   outline=(109, 207, 151, 255), width=2)
    # Screen — sky
    draw.rectangle([11, 15, 53, 33], fill=(20, 70, 110, 255))
    # Screen — ground
    draw.rectangle([11, 33, 53, 39], fill=(55, 120, 70, 255))
    # Horizon glow
    draw.line([11, 33, 53, 33], fill=(220, 175, 90, 180), width=1)

    # Stand
    draw.rectangle([27, 41, 37, 49], fill=(109, 207, 151, 255))
    draw.rectangle([19, 49, 45, 53], fill=(109, 207, 151, 255))

    return img


def _open_subprocess(flag):
    """Open viewer or settings in a separate process."""
    if getattr(sys, "frozen", False):
        # Packaged exe — pass flag to itself
        cmd = [sys.executable, flag]
    else:
        # Running as script — find main.py one level up from ui/
        main_py = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "main.py")
        )
        cmd = [sys.executable, main_py, flag]

    subprocess.Popen(cmd, creationflags=0x00000008)  # DETACHED_PROCESS


def run_tray(state):
    """
    Create and run the system tray icon.
    Blocks until the user clicks Exit.
    `state` is shared with the background thread.
    """

    def on_change_now(icon, item):
        cfg = manager.load_config()
        wallpaper.set_next(cfg)

    def on_fetch_now(icon, item):
        def _fetch():
            cfg   = manager.load_config()
            min_w = manager.res_to_min_width(cfg.get("min_resolution", "1080p"))
            count = downloader.fetch(
                count=5,
                queries=cfg.get("categories", ["nature"]),
                unsplash_key=cfg.get("unsplash_key", ""),
                min_width=min_w,
            )
            manager.register_all_inbox()
            if count > 0:
                icon.notify(
                    f"{count} new wallpaper{'s' if count != 1 else ''} downloaded.",
                    "Autowall",
                )
            else:
                icon.notify("No new wallpapers fetched.", "Autowall")

        threading.Thread(target=_fetch, daemon=True).start()

    def on_open_viewer(icon, item):
        _open_subprocess("--viewer")

    def on_toggle_pause(icon, item):
        state["paused"] = not state["paused"]
        icon.title = "Autowall  [Paused]" if state["paused"] else "Autowall"

    def on_toggle_fav(icon, item):
        cfg = manager.load_config()
        cfg["favorites_only"] = not cfg.get("favorites_only", False)
        manager.save_config(cfg)

    def on_open_settings(icon, item):
        _open_subprocess("--settings")

    def on_show_window(icon, item):
        root = state.get("root")
        if root:
            try:
                root.after(0, lambda: _restore_window(root))
            except Exception:
                pass

    def on_exit(icon, item):
        state["quitting"] = True
        state["stop"].set()
        root = state.get("root")
        if root:
            try:
                root.after(0, root.destroy)
            except Exception:
                pass
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Show Window",           on_show_window, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Change Wallpaper Now",  on_change_now),
        pystray.MenuItem("Fetch New Wallpapers",  on_fetch_now),
        pystray.MenuItem("Open Viewer",           on_open_viewer),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "Pause Auto Mode", on_toggle_pause,
            checked=lambda item: state["paused"],
        ),
        pystray.MenuItem(
            "Favorites Only", on_toggle_fav,
            checked=lambda item: manager.load_config().get("favorites_only", False),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Settings", on_open_settings),
        pystray.MenuItem("Exit",     on_exit),
    )

    icon = pystray.Icon(
        "Autowall",
        _create_icon_image(),
        "Autowall",
        menu,
    )
    state["icon"] = icon
    icon.run()   # blocks this thread


def _restore_window(root):
    """Show the main app window again from the tray."""
    root.deiconify()
    root.withdraw()
    root.deiconify()
    root.lift()
    try:
        root.attributes("-topmost", True)
        root.after(150, lambda: root.attributes("-topmost", False))
    except Exception:
        pass
    root.focus_force()
