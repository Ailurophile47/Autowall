# Autowall

A Windows desktop wallpaper manager with automatic scheduling, Unsplash fetching, a full taskbar GUI, and a system tray icon.

---

## Features

- **Auto wallpaper rotation** — changes wallpaper on a set interval (hourly, 6 h, 12 h, daily) or at a fixed time of day
- **Unsplash integration** — fetches high-resolution wallpapers by keyword category; guarantees at least one new image per fetch
- **Dark dashboard GUI** — taskbar-visible app window with hero preview, 4-column library grid, tab switching (All / Favorites / Recent)
- **System tray** — runs silently in the background; change wallpaper, fetch new ones, pause rotation, open viewer, or exit from the tray
- **Image reviewer** — swipe-style review window to like, favorite, or discard images; includes the 5 most recent wallpapers alongside unreviewed ones
- **Favorites system** — favorited images are moved to a dedicated folder and prioritized
- **No-repeat cycle** — wallpapers rotate without repeating until the full pool is exhausted, then the cycle resets
- **Minimum resolution filter** — download only 1080p, 2K, or 4K images (configurable)
- **Scheduled time support** — optionally set an exact HH:MM time (24-hr) for the daily wallpaper change
- **Autostart with Windows** — optional registry entry so Autowall launches at login
- **Close to tray** — closing the window keeps the app running; only the tray Exit button fully quits

---

## Project Structure

```
Autowall/
├── main.py                  # Entry point — starts background loop, tray, and main window
├── core/
│   ├── manager.py           # Config/metadata I/O, folder setup, candidate filtering
│   ├── downloader.py        # Unsplash API fetch with guaranteed-minimum logic
│   └── wallpaper.py         # Windows wallpaper setter via ctypes + winreg
├── ui/
│   ├── app_window.py        # Main taskbar window (hero card + library grid)
│   ├── viewer.py            # Image review window (like / favorite / dislike)
│   ├── settings.py          # Settings window (interval, schedule, categories, API key)
│   └── tray.py              # System tray icon and menu (pystray)
├── config/
│   └── config.json          # User settings — excluded from git (contains API key)
├── Inbox/                   # Downloaded wallpapers — excluded from git
├── Favorites/               # Favorited wallpapers — excluded from git
└── metadata.json            # Image state tracking — excluded from git
```

---

## Requirements

- Windows 10 or 11
- Python 3.9+
- Internet connection (for Unsplash fetching)
- A free [Unsplash Developer](https://unsplash.com/developers) Access Key

### Python dependencies

```powershell
py -m pip install requests pillow pystray
```

---

## Setup

1. **Clone the repository**

   ```powershell
   git clone https://github.com/Ailurophile47/Autowall.git
   cd Autowall
   ```

2. **Install dependencies**

   ```powershell
   py -m pip install requests pillow pystray
   ```

3. **Run**

   ```powershell
   py main.py
   ```

   On first launch, Autowall creates the `config/`, `Inbox/`, and `Favorites/` folders automatically and fetches an initial batch of wallpapers.

4. **Add your Unsplash API key**

   Open the Settings window (⚙ button or tray → Settings), paste your Unsplash Access Key, and click **Save Settings**. The key is stored in `config/config.json` which is excluded from version control.

---

## How It Works

### Startup

`main.py` runs three components simultaneously:

| Component | Thread | Role |
|---|---|---|
| Background loop | Daemon thread | Checks every 60 s whether to change the wallpaper or fetch new ones |
| Tray icon | Daemon thread | System tray menu for quick actions |
| Main window | Main thread | Full GUI; blocks until the process exits |

### Background loop

Every 60 seconds the loop checks:

- **Wallpaper change** — if the configured interval has elapsed, or if the scheduled HH:MM matches the current time (once per day), it calls `wallpaper.set_next()` and refreshes the GUI grid.
- **Daily fetch** — if 24 hours have passed since the last fetch, it downloads a new batch from Unsplash and registers the images.

### Unsplash fetching

`downloader.fetch()` shuffles the configured categories and tries each one until at least one image is successfully downloaded. This guarantees a result even if the first query returns only duplicates or images that fail the resolution filter.

### Wallpaper rotation

`wallpaper.set_next()` picks a random candidate from `metadata.json` that has not been used recently. Once all images are used, the cycle resets. A rolling "recent" window (last 5) prevents the same image appearing back-to-back across resets.

### Metadata

`metadata.json` tracks every image by its MD5 file hash:

```json
{
  "abc123...": {
    "path": "C:/...Inbox/photo.jpg",
    "date": "2025-01-01T12:00:00",
    "liked": false,
    "favorite": false,
    "reviewed": false,
    "used_as_wallpaper": true,
    "last_set": "2025-01-02T08:00:00"
  },
  "__recent__": ["abc123...", "def456..."]
}
```

---

## Settings Reference

| Setting | Description |
|---|---|
| Change Interval | How often to auto-rotate (1 h / 6 h / 12 h / 24 h) |
| Scheduled Change Time | Optional fixed HH:MM (24-hr) for the daily change |
| Minimum Resolution | Filter downloads to 1080p / 2K / 4K |
| Categories | Unsplash search keywords (nature, space, cyberpunk, etc.) |
| Favorites Only Mode | Rotate only through your favorited images |
| Start with Windows | Adds/removes the app from the Windows registry autostart |
| Unsplash API Key | Your Unsplash Access Key (stored locally, never committed) |

---

## GUI Overview

### Main window

- **Top bar** — logo, tab switcher (Library / Favorites / Recent), fetch button (⟳), reviewer shortcut (◱), settings (⚙)
- **Hero card** — large preview of the currently active wallpaper with Like, Fav, Set Now, and Delete actions
- **Library grid** — 4-column thumbnail grid; left-click to set as wallpaper, right-click for full context menu
- Resizes responsively; closing the window sends Autowall to the tray

### Viewer

Opened from the tray or the ◱ button. Shows unreviewed images and the 5 most recent wallpapers (marked `[Recent]`). Actions: Like (`L`), Favorite (`F`), Skip (`S`), Discard (`D`).

### Tray menu

| Item | Action |
|---|---|
| Show Window | Restore the main window |
| Change Wallpaper Now | Immediately rotate to the next wallpaper |
| Fetch New Wallpapers | Download a fresh batch from Unsplash |
| Open Viewer | Launch the image reviewer |
| Pause Auto Mode | Suspend the background rotation loop |
| Favorites Only | Toggle favorites-only rotation |
| Settings | Open the settings window |
| Exit | Fully quit Autowall |

---

## Wallpaper Styles

Configurable via `config.json` (`wallpaper_style` key). Options: `Fill`, `Fit`, `Stretch`, `Center`, `Span`, `Tile`. Default is `Fill`.

---

## Troubleshooting

**No wallpapers appear on first launch**
Ensure your Unsplash API key is set in Settings. Without a key, fetching is skipped.

**"No new wallpapers fetched" notification**
All images returned by the API were either already downloaded or below the minimum resolution. Try adding more categories in Settings.

**Autowall doesn't start with Windows**
Enable "Start automatically with Windows" in Settings and click Save. This writes an entry to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.

**Import errors on launch**
Run `py -m pip install requests pillow pystray` to install missing dependencies.

---

## Notes

- `config/config.json` and `metadata.json` are git-ignored — your API key and local image paths are never committed.
- `Inbox/` and `Favorites/` are also git-ignored — images are fetched fresh on each installation.
- The app uses only the Unsplash **Access Key** (not the Secret Key).
