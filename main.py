"""
main.py — Entry point for Wallpaper App.

Modes (argv flags):
  --viewer    Open the image review window and exit
  --settings  Open the settings window and exit
  (none)      Start main window + tray + background engine

The background thread runs every 60 s, changes the wallpaper on schedule,
and fetches new images once per day.
The tray icon runs on a daemon thread alongside the main window.
The main window (taskbar-visible) runs on the main thread.
"""
import sys
import os
import threading
from datetime import datetime, timedelta

# Ensure project root is on the path when run as a script from any cwd
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import manager, downloader, wallpaper


# ── Background loop ────────────────────────────────────────────────────────────

def _background_loop(state):
    """
    Runs on a daemon thread.
    Every 60 seconds checks whether to change the wallpaper or fetch new ones.
    """
    while not state["stop"].wait(60):
        if state["paused"]:
            continue

        try:
            cfg      = manager.load_config()
            now      = datetime.now()
            interval = timedelta(hours=cfg.get("interval_hours", 24))
            bias_ratio = manager.get_preference_bias_ratio(cfg)

            # ── Change wallpaper on interval or scheduled time ─────────────────
            last_change   = state.get("last_change")
            change_time   = cfg.get("change_time", "")   # e.g. "08:00" or ""
            do_change     = False

            if change_time and len(change_time) == 5:
                # Scheduled time mode: fire once per day at HH:MM
                current_hhmm  = now.strftime("%H:%M")
                last_sched    = state.get("last_scheduled_date")
                if current_hhmm == change_time and last_sched != now.date():
                    do_change = True
                    state["last_scheduled_date"] = now.date()
            else:
                # Interval mode
                if last_change is None or (now - last_change) >= interval:
                    do_change = True

            if do_change:
                changed = wallpaper.set_next(cfg)
                if changed:
                    state["last_change"] = now
                    root = state.get("root")
                    if root:
                        try:
                            root.after(0, lambda: _refresh_app(state))
                        except Exception:
                            pass
                    # Tray notification
                    icon = state.get("icon")
                    if icon:
                        try:
                            icon.notify("New wallpaper applied", "Autowall")
                        except Exception:
                            pass

            # ── Fetch new wallpapers once per 24 h ────────────────────────────
            last_fetch = state.get("last_fetch")
            if last_fetch is None or (now - last_fetch) >= timedelta(hours=24):
                min_w = manager.res_to_min_width(cfg.get("min_resolution", "1080p"))
                meta_for_prefs = manager.load_meta()
                prefs = meta_for_prefs.get("__preferences__", {})
                downloader.fetch(
                    count=5,
                    queries=cfg.get("categories", ["nature"]),
                    unsplash_key=cfg.get("unsplash_key", ""),
                    min_width=min_w,
                    prefs=prefs,
                    bias_ratio=bias_ratio,
                )
                cat_hints = downloader.get_and_clear_fetched_categories()
                manager.register_all_inbox(category_hints=cat_hints)
                state["last_fetch"] = now

        except Exception:
            pass   # never crash the background thread


def _refresh_app(state):
    """Refresh main window grid if the app reference is stored in state."""
    app = state.get("app")
    if app:
        try:
            app.refresh()
        except Exception:
            pass


# ── First-run fetch ────────────────────────────────────────────────────────────

def _first_run_fetch():
    """Called once on startup if inbox is empty."""
    try:
        inbox_imgs = [
            f for f in os.listdir(manager.INBOX)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ]
        if inbox_imgs:
            return

        cfg   = manager.load_config()
        min_w = manager.res_to_min_width(cfg.get("min_resolution", "1080p"))
        bias_ratio = manager.get_preference_bias_ratio(cfg)
        downloader.fetch(
            count=5,
            queries=cfg.get("categories", ["nature"]),
            unsplash_key=cfg.get("unsplash_key", ""),
            min_width=min_w,
            bias_ratio=bias_ratio,
        )
        cat_hints = downloader.get_and_clear_fetched_categories()
        manager.register_all_inbox(category_hints=cat_hints)
    except Exception:
        pass


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    # ── Mode dispatch ──────────────────────────────────────────────────────────
    if "--viewer" in sys.argv:
        from ui.viewer import run_viewer
        run_viewer()
        return

    if "--settings" in sys.argv:
        from ui.settings import run_settings
        run_settings()
        return

    # ── Full app mode ──────────────────────────────────────────────────────────
    manager.ensure_setup()

    # Fetch on first launch so the library shows images immediately
    _first_run_fetch()

    state = {
        "paused":      False,
        "last_change": None,
        "last_fetch":  datetime.now(),   # already fetched above
        "stop":                 threading.Event(),
        "quitting":             False,
        "last_scheduled_date":  None,
        "root":        None,   # set by run_app
        "icon":        None,   # set by run_tray
        "app":         None,   # set by run_app
    }

    # Set first wallpaper immediately
    try:
        cfg = manager.load_config()
        wallpaper.set_next(cfg)
        state["last_change"] = datetime.now()
    except Exception:
        pass

    # Start background wallpaper loop
    threading.Thread(target=_background_loop, args=(state,), daemon=True).start()

    # Start tray icon on a daemon thread (non-blocking for main thread)
    from ui.tray import run_tray
    threading.Thread(target=run_tray, args=(state,), daemon=True).start()

    # Run main window on main thread (blocks until window is closed)
    from ui.app_window import run_app
    run_app(state)

    # Clean shutdown
    state["stop"].set()


if __name__ == "__main__":
    main()
