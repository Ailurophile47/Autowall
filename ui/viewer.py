"""
ui/viewer.py
Image review window — Like / Favorite / Dislike / Skip.
Called standalone via main.py --viewer or directly.
"""
import os
import random
import shutil
import sys
import tkinter as tk
from PIL import Image, ImageTk

from core.manager import (
    INBOX, FAV,
    load_meta, save_meta, get_unique_path, register_file,
    load_config, update_preference, remove_from_recent,
)
from core import downloader, wallpaper

PREVIEW_MAX = (940, 540)

BG      = "#101418"
FG      = "#dbe4ee"
FG_DIM  = "#6b7a8d"
BTN_LIKE = {"bg": "#1a3d28", "fg": "#6fcf97", "activebackground": "#255c3a", "activeforeground": "#6fcf97"}
BTN_FAV  = {"bg": "#3d2e00", "fg": "#f2c94c", "activebackground": "#5a4400", "activeforeground": "#f2c94c"}
BTN_SKIP = {"bg": "#1c2530", "fg": "#8da0b3", "activebackground": "#273545", "activeforeground": "#8da0b3"}
BTN_DIS  = {"bg": "#3d1a1a", "fg": "#eb5757", "activebackground": "#5c2828", "activeforeground": "#eb5757"}


def _build_preview(path):
    """Returns (PhotoImage, orig_w, orig_h)."""
    with Image.open(path) as img:
        orig_w, orig_h = img.size
        img.thumbnail(PREVIEW_MAX, Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
    return photo, orig_w, orig_h


class _App:
    def __init__(self, root):
        self.root = root
        self.root.title("Wallpaper Reviewer")
        self.root.geometry("1000x700")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        self.meta = load_meta()
        recent_set = set(self.meta.get("__recent__", []))

        unreviewed = [
            h for h, info in self.meta.items()
            if isinstance(info, dict)
            and os.path.exists(info.get("path", ""))
            and not info.get("reviewed", False)
            and h not in recent_set
        ]
        random.shuffle(unreviewed)

        # Recent wallpapers go at the front so user sees them first
        recent_valid = [
            h for h in self.meta.get("__recent__", [])
            if isinstance(self.meta.get(h), dict)
            and os.path.exists(self.meta[h].get("path", ""))
        ]
        recent_valid.reverse()   # most recent first

        self.files = recent_valid + unreviewed
        self.index = 0
        self.tk_img = None

        self.status   = tk.Label(root, text="", fg=FG_DIM, bg=BG, font=("Segoe UI", 10))
        self.status.pack(pady=(10, 0))

        self.info     = tk.Label(root, text="", fg=FG, bg=BG, font=("Segoe UI", 11, "bold"))
        self.info.pack(pady=(4, 4))

        self.label    = tk.Label(root, bg=BG)
        self.label.pack()

        self.feedback = tk.Label(root, text="", fg="#6fcf97", bg=BG, font=("Segoe UI", 12, "bold"))
        self.feedback.pack(pady=(6, 0))

        self.btn_frame = tk.Frame(root, bg=BG)
        self.btn_frame.pack(pady=10)
        btn_frame = self.btn_frame

        btn_cfg = {
            "font": ("Segoe UI", 11), "width": 13, "relief": "flat",
            "cursor": "hand2", "pady": 7, "borderwidth": 0,
        }
        tk.Button(btn_frame, text="♥  Like",     command=self.like,     **btn_cfg, **BTN_LIKE).pack(side="left", padx=7)
        tk.Button(btn_frame, text="★  Favorite", command=self.favorite, **btn_cfg, **BTN_FAV ).pack(side="left", padx=7)
        tk.Button(btn_frame, text="⏭  Skip",     command=self.skip,     **btn_cfg, **BTN_SKIP).pack(side="left", padx=7)
        tk.Button(btn_frame, text="✕  Dislike",  command=self.dislike,  **btn_cfg, **BTN_DIS ).pack(side="left", padx=7)

        root.bind("l", lambda e: self.like())
        root.bind("f", lambda e: self.favorite())
        root.bind("s", lambda e: self.skip())
        root.bind("d", lambda e: self.dislike())

        self.show_image()

    def flash(self, text, color="#6fcf97"):
        self.feedback.config(text=text, fg=color)
        self.root.after(700, lambda: self.feedback.config(text=""))

    def current_hash(self):
        return self.files[self.index] if self.index < len(self.files) else None

    def show_image(self):
        h = self.current_hash()
        if h is None:
            self._show_done()
            return

        path = self.meta[h]["path"]
        if not os.path.exists(path):
            self.files.pop(self.index)
            self.show_image()
            return

        try:
            self.tk_img, ow, oh = _build_preview(path)
        except OSError:
            self._discard(fetch=False)
            return

        recent_set = set(self.meta.get("__recent__", []))
        tag = "  [Recent]" if h in recent_set else ""
        self.label.config(image=self.tk_img, text="")
        self.info.config(text=f"{ow} × {oh}  |  {os.path.basename(path)}{tag}")
        self.status.config(text=f"{self.index + 1} of {len(self.files)}")

    def _show_done(self):
        self.btn_frame.pack_forget()
        for key in ("l", "f", "s", "d"):
            self.root.unbind(key)
        self.label.config(image="", text="You're all caught up  🎉",
                          fg=FG, font=("Segoe UI", 20, "bold"))
        self.info.config(text="")
        self.status.config(text="")
        self.feedback.config(text="")
        self.root.after(1000, self.root.destroy)

    def like(self):
        h = self.current_hash()
        if h is None:
            return
        category = self.meta[h].get("category", "general")
        self.meta[h]["liked"]    = True
        self.meta[h]["reviewed"] = True
        update_preference(self.meta, category, +2)
        save_meta(self.meta)
        self.flash("♥  Liked", "#6fcf97")
        self.index += 1
        self.show_image()

    def favorite(self):
        h = self.current_hash()
        if h is None:
            return
        path = self.meta[h]["path"]
        if not os.path.exists(path):
            self.index += 1
            self.show_image()
            return
        category = self.meta[h].get("category", "general")
        new_path = get_unique_path(FAV, os.path.basename(path))
        shutil.move(path, new_path)
        self.meta[h].update({"path": new_path, "favorite": True, "liked": True, "reviewed": True})
        wallpaper.refresh_current_wallpaper(load_config(), h, self.meta)
        update_preference(self.meta, category, +5)
        save_meta(self.meta)
        self.flash("★  Favorited", "#f2c94c")
        self.index += 1
        self.show_image()

    def skip(self):
        if self.current_hash() is None:
            return
        self.flash("⏭  Skipped", "#8da0b3")
        self.index += 1
        self.show_image()

    def dislike(self):
        self._discard(fetch=True)

    def _discard(self, fetch=True):
        h = self.current_hash()
        if h is None:
            return
        path = self.meta[h]["path"]
        # Score dislike BEFORE deleting the entry so category is still accessible
        category = self.meta[h].get("category", "general")
        update_preference(self.meta, category, -3)
        wallpaper.switch_away_from_current(load_config(), h, self.meta)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        remove_from_recent(self.meta, h)
        del self.meta[h]
        save_meta(self.meta)
        self.files.pop(self.index)
        self.flash("✕  Deleted", "#eb5757")
        if fetch:
            self._fetch_one()
        self.show_image()

    def _fetch_one(self):
        """Fetch one replacement image from Unsplash and insert it next."""
        old_hashes = {h for h in self.meta if isinstance(self.meta.get(h), dict)}
        cfg = load_config()
        downloader.fetch(
            count=1,
            queries=cfg.get("categories", ["nature"]),
            unsplash_key=cfg.get("unsplash_key", ""),
            min_width=1920,
            bias_ratio=max(0.0, min(1.0, cfg.get("preference_bias_percent", 70) / 100.0)),
        )
        for f in os.listdir(INBOX):
            fp = os.path.join(INBOX, f)
            if os.path.isfile(fp):
                register_file(fp)

        new_meta = load_meta()
        added = {h for h in new_meta if isinstance(new_meta[h], dict) and h not in old_hashes}
        self.meta = new_meta
        for h in added:
            if os.path.exists(new_meta[h].get("path", "")):
                self.files.insert(self.index, h)
                break


def run_viewer():
    meta = load_meta()
    recent_set = set(meta.get("__recent__", []))

    unreviewed = [
        h for h, info in meta.items()
        if isinstance(info, dict)
        and os.path.exists(info.get("path", ""))
        and not info.get("reviewed", False)
        and h not in recent_set
    ]
    recent_valid = [
        h for h in meta.get("__recent__", [])
        if isinstance(meta.get(h), dict)
        and os.path.exists(meta[h].get("path", ""))
    ]

    if not unreviewed and not recent_valid:
        root = tk.Tk()
        root.withdraw()
        import tkinter.messagebox as mb
        mb.showinfo("Wallpaper Reviewer", "No images to review.\nRun the fetcher first.")
        root.destroy()
        return

    root = tk.Tk()
    _App(root)
    root.mainloop()


if __name__ == "__main__":
    run_viewer()
