"""
ui/app_window.py
Main application window.
Layout: top-bar nav → hero "Now Active" card → scrollable 4-col library grid.
Dark dashboard + music-player + minimal card aesthetic.
"""
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image, ImageDraw, ImageTk

from core import manager, wallpaper, downloader

# ── Palette ───────────────────────────────────────────────────────────────────
BG        = "#0e1117"
BG2       = "#161b22"
BG3       = "#1c2230"
CARD      = "#161b22"
CARD_HOV  = "#1f2937"
FG        = "#e6edf3"
FG_DIM    = "#8b949e"
FG_MUT    = "#3d444d"
ACC       = "#6fcf97"
ACC_DIM   = "#2d6a4f"
GOLD      = "#f2c94c"
RED       = "#f85149"
BORDER    = "#21262d"

WIN_W     = 980
WIN_H     = 700
COLS      = 4
GAP       = 10
H_PAD     = 18
HERO_H    = 210
TOPBAR_H  = 52


# ── Subprocess helper ─────────────────────────────────────────────────────────

def _open_subprocess(flag):
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, flag]
    else:
        main_py = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "main.py")
        )
        cmd = [sys.executable, main_py, flag]
    subprocess.Popen(cmd, creationflags=0x00000008)


# ── Small icon button (top bar) ───────────────────────────────────────────────

class _IconBtn(tk.Label):
    def __init__(self, parent, text, tip, command, accent=False):
        super().__init__(
            parent, text=text,
            font=("Segoe UI Symbol", 13 if not accent else 11),
            fg=ACC if accent else FG_DIM,
            bg=BG, cursor="hand2", padx=8, pady=4,
        )
        self.bind("<Button-1>", lambda e: command())
        self.bind("<Enter>",    lambda e: self.config(fg=FG))
        self.bind("<Leave>",    lambda e: self.config(fg=ACC if accent else FG_DIM))
        if tip:
            self._tip_text = tip
            self.bind("<Enter>", self._show_tip, add="+")
            self.bind("<Leave>", self._hide_tip, add="+")
        self._tip = None

    def _show_tip(self, e):
        x = self.winfo_rootx() + self.winfo_width() // 2
        y = self.winfo_rooty() + self.winfo_height() + 4
        self._tip = tk.Toplevel(self)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self._tip, text=self._tip_text,
                 bg=BG3, fg=FG_DIM, font=("Segoe UI", 8),
                 padx=6, pady=3, relief="flat").pack()

    def _hide_tip(self, _):
        if self._tip:
            self._tip.destroy()
            self._tip = None


# ── Tab button ────────────────────────────────────────────────────────────────

class _TabBtn(tk.Label):
    def __init__(self, parent, text, key, on_select):
        super().__init__(
            parent, text=text,
            font=("Segoe UI", 10), fg=FG_DIM,
            bg=BG, cursor="hand2", padx=14, pady=4,
        )
        self._key       = key
        self._on_select = on_select
        self._active    = False
        self.bind("<Button-1>", lambda e: on_select(key))
        self.bind("<Enter>",    lambda e: self.config(fg=FG) if not self._active else None)
        self.bind("<Leave>",    lambda e: self.config(fg=FG if self._active else FG_DIM))

    def set_active(self, active):
        self._active = active
        self.config(
            fg=FG if active else FG_DIM,
            font=("Segoe UI", 10, "bold") if active else ("Segoe UI", 10),
        )


# ── Thumbnail card ────────────────────────────────────────────────────────────

class _Card(tk.Canvas):
    def __init__(self, parent, file_hash, info, tw, th, on_action):
        super().__init__(
            parent, width=tw, height=th,
            bg=CARD, highlightthickness=1,
            highlightbackground=BORDER, cursor="hand2",
        )
        self.file_hash = file_hash
        self.info      = info
        self.on_action = on_action
        self._photo    = None
        self._tw       = tw
        self._th       = th

        self.bind("<Button-1>", lambda e: on_action(file_hash, "set"))
        self.bind("<Button-3>", self._ctx)
        self.bind("<Enter>",    self._on_enter)
        self.bind("<Leave>",    self._on_leave)

    def set_photo(self, photo):
        self._photo = photo
        self.delete("all")
        self.create_image(0, 0, anchor="nw", image=photo)
        self._draw_badges()

    def _draw_badges(self):
        tw = self._tw
        info = self.info
        if info.get("favorite"):
            self.create_text(tw - 7, 7, text="★", anchor="ne",
                             fill=GOLD, font=("Segoe UI", 9, "bold"))
        elif info.get("liked"):
            self.create_text(tw - 7, 7, text="♥", anchor="ne",
                             fill=ACC, font=("Segoe UI", 9, "bold"))

    def _on_enter(self, _):
        tw, th = self._tw, self._th
        self.create_rectangle(0, th - 22, tw, th,
                              fill="#000000", stipple="gray50",
                              outline="", tags="hov")
        self.create_text(tw // 2, th - 11, text="Set as wallpaper",
                         fill=FG_DIM, font=("Segoe UI", 7), tags="hov")
        self.config(highlightbackground=ACC)

    def _on_leave(self, _):
        self.delete("hov")
        self.config(highlightbackground=BORDER)

    def _ctx(self, e):
        info  = self.info
        liked = info.get("liked", False)
        fav   = info.get("favorite", False)
        m = tk.Menu(self, tearoff=0, bg=BG2, fg=FG,
                    activebackground=CARD_HOV, activeforeground=FG,
                    font=("Segoe UI", 9), bd=0, relief="flat")
        m.add_command(label="  Set as Wallpaper",
                      command=lambda: self.on_action(self.file_hash, "set"))
        m.add_separator()
        m.add_command(label=("♥  Unlike" if liked else "♥  Like"),
                      command=lambda: self.on_action(self.file_hash, "like"))
        m.add_command(
            label=("★  Remove from Favorites" if fav else "★  Add to Favorites"),
            command=lambda: self.on_action(self.file_hash, "favorite"),
        )
        m.add_separator()
        m.add_command(label="✕  Delete", foreground=RED, activeforeground=RED,
                      command=lambda: self.on_action(self.file_hash, "delete"))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()


# ── Main window ───────────────────────────────────────────────────────────────

class WallpaperApp:
    def __init__(self, root, state):
        self.root    = root
        self.state   = state
        self._tab    = "all"
        self._cards  = []
        self._photos = []          # thumbnail PhotoImage refs
        self._hero_photo = None    # hero PhotoImage ref
        self._fetching   = False
        self._render_tok = 0
        self._last_grid_w  = 0
        self._resize_after = None

        root.title("Autowall")
        root.configure(bg=BG)
        root.resizable(True, True)
        root.minsize(640, 500)

        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{WIN_W}x{WIN_H}+{(sw-WIN_W)//2}+{(sh-WIN_H)//2}")
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_topbar()
        self._build_hero()
        self._build_library()

        root.after_idle(self.refresh)

    # ── Top bar ───────────────────────────────────────────────────────────────

    def _build_topbar(self):
        bar = tk.Frame(self.root, bg=BG, height=TOPBAR_H)
        bar.pack(fill="x", padx=H_PAD)
        bar.pack_propagate(False)

        # Left: logo + title
        left = tk.Frame(bar, bg=BG)
        left.pack(side="left", fill="y")
        tk.Label(left, text="◈", font=("Segoe UI Symbol", 16),
                 fg=ACC, bg=BG).pack(side="left", pady=0)
        tk.Label(left, text="  Wallpaper App",
                 font=("Segoe UI", 13, "bold"), fg=FG, bg=BG).pack(side="left")

        # Right: icon actions
        right = tk.Frame(bar, bg=BG)
        right.pack(side="right", fill="y")

        _IconBtn(right, "⚙", "Settings",
                 lambda: _open_subprocess("--settings")).pack(side="right")
        _IconBtn(right, "⟳", "Fetch new wallpapers",
                 self._fetch_new, accent=True).pack(side="right")
        _IconBtn(right, "◱", "Open Reviewer",
                 lambda: _open_subprocess("--viewer")).pack(side="right")

        # Center: tabs
        center = tk.Frame(bar, bg=BG)
        center.pack(side="left", fill="y", padx=32)

        self._tabs = {}
        for label, key in [("Library", "all"), ("Favorites", "favorites"), ("Recent", "recent")]:
            btn = _TabBtn(center, label, key, self._switch_tab)
            btn.pack(side="left")
            self._tabs[key] = btn

        self._tabs["all"].set_active(True)

        # Separator line
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

    # ── Hero card ─────────────────────────────────────────────────────────────

    def _build_hero(self):
        self._hero_frame = tk.Frame(self.root, bg=BG, height=HERO_H)
        self._hero_frame.pack(fill="x", padx=H_PAD, pady=(14, 0))
        self._hero_frame.pack_propagate(False)

        self._hero_cv = tk.Canvas(self._hero_frame, bg=BG2,
                                  highlightthickness=1,
                                  highlightbackground=BORDER,
                                  cursor="hand2")
        self._hero_cv.pack(fill="both", expand=True)
        self._hero_cv.bind("<Button-1>",  lambda e: self._hero_action("set"))
        self._hero_cv.bind("<Configure>", lambda e: self._redraw_hero())

        # Action buttons — solid BG3 frame placed over canvas in _redraw_hero
        btn_frame = tk.Frame(self._hero_cv, bg=BG3)
        self._hero_btn_frame = btn_frame

        bcfg = dict(font=("Segoe UI", 9), relief="flat", cursor="hand2",
                    padx=10, pady=4, bd=0)
        self._hero_like_btn = tk.Button(btn_frame, text="♥  Like", **bcfg,
                                        bg=BG3, fg=FG, activebackground=CARD_HOV,
                                        command=lambda: self._hero_action("like"))
        self._hero_like_btn.pack(side="left", padx=(0, 4))

        tk.Button(btn_frame, text="★  Fav", **bcfg,
                  bg=BG3, fg=GOLD, activebackground=CARD_HOV,
                  command=lambda: self._hero_action("favorite")).pack(side="left", padx=(0, 4))

        tk.Button(btn_frame, text="Set Now", **bcfg,
                  bg=ACC, fg=BG, activebackground="#52b380",
                  command=lambda: self._hero_action("set")).pack(side="left", padx=(0, 4))

        tk.Button(btn_frame, text="✕", **bcfg,
                  bg=BG3, fg=RED, activebackground=CARD_HOV,
                  command=lambda: self._hero_action("delete")).pack(side="left")

        self._hero_hash      = None
        self._hero_img_cache = None
        self._hero_name_text = ""
        self._hero_res_text  = ""

    def _update_hero(self, meta):
        """Pick the most recent wallpaper to display in the hero card."""
        recent = list(meta.get("__recent__", []))
        h = None
        for candidate in reversed(recent):
            info = meta.get(candidate)
            if isinstance(info, dict) and os.path.exists(info.get("path", "")):
                h = candidate
                break

        if h is None:
            # Fallback: any image
            for candidate, info in meta.items():
                if isinstance(info, dict) and os.path.exists(info.get("path", "")):
                    h = candidate
                    break

        self._hero_hash = h
        if h is None:
            self._hero_cv.delete("all")
            self._hero_cv.create_text(
                self._hero_cv.winfo_width() // 2 or 400,
                HERO_H // 2,
                text="No wallpapers yet — click ⟳ to fetch",
                fill=FG_DIM, font=("Segoe UI", 11),
            )
            return

        path = meta[h]["path"]
        liked = meta[h].get("liked", False)
        self._hero_like_btn.config(text="♥  Unlike" if liked else "♥  Like")
        self._hero_name_text = os.path.basename(path)
        try:
            with Image.open(path) as img:
                self._hero_res_text = f"{img.width} × {img.height}"
        except Exception:
            self._hero_res_text = ""

        # Load hero image in background
        threading.Thread(target=self._load_hero_img, args=(path,), daemon=True).start()

    def _load_hero_img(self, path):
        try:
            with Image.open(path) as img:
                img = img.convert("RGB")
                self._hero_img_cache = (path, img.copy())
        except Exception:
            self._hero_img_cache = None
        self.root.after(0, self._redraw_hero)

    def _redraw_hero(self):
        cv = self._hero_cv
        cv.update_idletasks()
        cw = cv.winfo_width()
        ch = cv.winfo_height()
        if cw < 2 or ch < 2:
            return

        cv.delete("all")

        if self._hero_img_cache:
            _, pil_img = self._hero_img_cache
            # Fill canvas, crop-center
            ratio = max(cw / pil_img.width, ch / pil_img.height)
            nw = int(pil_img.width * ratio)
            nh = int(pil_img.height * ratio)
            resized = pil_img.resize((nw, nh), Image.LANCZOS)
            x0 = (nw - cw) // 2
            y0 = (nh - ch) // 2
            cropped = resized.crop((x0, y0, x0 + cw, y0 + ch))

            # Dark gradient overlay at bottom
            grad = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            draw = ImageDraw.Draw(grad)
            for i in range(ch):
                alpha = int(200 * (i / ch) ** 2)
                draw.line([(0, i), (cw, i)], fill=(14, 17, 23, alpha))
            blended = Image.alpha_composite(cropped.convert("RGBA"), grad).convert("RGB")
            self._hero_photo = ImageTk.PhotoImage(blended)
            cv.create_image(0, 0, anchor="nw", image=self._hero_photo)

        # "NOW ACTIVE" badge top-left
        cv.create_rectangle(10, 10, 96, 26, fill=ACC_DIM, outline="")
        cv.create_text(53, 18, text="NOW ACTIVE", fill=ACC,
                       font=("Segoe UI", 7, "bold"))

        # Filename + resolution drawn as canvas text (no alpha issues)
        pad = 12
        if self._hero_name_text:
            cv.create_text(pad, ch - 48, text=self._hero_name_text,
                           anchor="sw", fill=FG, font=("Segoe UI", 11, "bold"))
        if self._hero_res_text:
            cv.create_text(pad, ch - 30, text=self._hero_res_text,
                           anchor="sw", fill=FG_DIM, font=("Segoe UI", 9))

        # Buttons placed via place — solid BG3 background, no transparency needed
        self._hero_btn_frame.place(x=cw - 8, y=ch - 10, anchor="se")

    def _hero_action(self, action):
        if self._hero_hash:
            self._on_action(self._hero_hash, action)

    # ── Library section ───────────────────────────────────────────────────────

    def _build_library(self):
        # Section header
        hdr = tk.Frame(self.root, bg=BG)
        hdr.pack(fill="x", padx=H_PAD, pady=(16, 6))

        self._lib_title = tk.Label(hdr, text="Library",
                                   font=("Segoe UI", 11, "bold"), fg=FG, bg=BG)
        self._lib_title.pack(side="left")

        self._count_lbl = tk.Label(hdr, text="",
                                   font=("Segoe UI", 9), fg=FG_MUT, bg=BG)
        self._count_lbl.pack(side="right")

        # Tab underline bar
        self._underline = tk.Canvas(self.root, bg=BG, height=2, highlightthickness=0)
        self._underline.pack(fill="x", padx=H_PAD)

        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x", pady=(4, 0))

        # Scrollable grid
        wrap = tk.Frame(self.root, bg=BG)
        wrap.pack(fill="both", expand=True)

        self._cv = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(wrap, orient="vertical", command=self._cv.yview)
        self._cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._cv.pack(side="left", fill="both", expand=True)

        self._grid = tk.Frame(self._cv, bg=BG)
        self._win_id = self._cv.create_window((0, 0), window=self._grid, anchor="nw")
        self._last_grid_w  = 0
        self._resize_after = None

        self._grid.bind("<Configure>",
                        lambda e: self._cv.configure(scrollregion=self._cv.bbox("all")))
        self._cv.bind("<Configure>", self._on_canvas_configure)
        self._cv.bind_all("<MouseWheel>",
                          lambda e: self._cv.yview_scroll(-1 * (e.delta // 120), "units"))

    def _on_canvas_configure(self, e):
        self._cv.itemconfig(self._win_id, width=e.width)
        if abs(e.width - self._last_grid_w) > 4:
            self._last_grid_w = e.width
            if self._resize_after:
                self.root.after_cancel(self._resize_after)
            self._resize_after = self.root.after(150, self.refresh)

    # ── Tab switching ─────────────────────────────────────────────────────────

    def _switch_tab(self, key):
        self._tab = key
        for k, btn in self._tabs.items():
            btn.set_active(k == key)
        titles = {"all": "Library", "favorites": "Favorites", "recent": "Recent"}
        self._lib_title.config(text=titles[key])
        self.refresh()

    # ── Data + render ─────────────────────────────────────────────────────────

    def refresh(self):
        meta   = manager.load_meta()
        recent = list(meta.get("__recent__", []))

        if self._tab == "all":
            recent_set = set(recent)
            items = [
                (h, info) for h, info in meta.items()
                if isinstance(info, dict) and os.path.exists(info.get("path", ""))
            ]
            items.sort(key=lambda x: (0 if x[0] in recent_set else 1,
                                      x[1].get("date", "")), reverse=True)
            items.sort(key=lambda x: 0 if x[0] in recent_set else 1)

        elif self._tab == "favorites":
            fav_norm = os.path.normcase(manager.FAV)
            items = [
                (h, info) for h, info in meta.items()
                if isinstance(info, dict)
                and os.path.exists(info.get("path", ""))
                and os.path.normcase(info.get("path", "")).startswith(fav_norm)
            ]

        else:  # recent
            items = [
                (h, meta[h]) for h in reversed(recent)
                if h in meta and isinstance(meta[h], dict)
                and os.path.exists(meta[h].get("path", ""))
            ]

        n = len(items)
        self._count_lbl.config(text=f"{n} item{'s' if n != 1 else ''}")
        self._update_hero(meta)
        self._render_grid(items)

    def _render_grid(self, items):
        self._render_tok += 1
        tok = self._render_tok

        for w in self._grid.winfo_children():
            w.destroy()
        self._cards.clear()
        self._photos.clear()

        if not items:
            tk.Label(self._grid, text="Nothing here yet.",
                     font=("Segoe UI", 11), fg=FG_DIM, bg=BG).pack(pady=40)
            return

        self._cv.update_idletasks()
        cw = self._cv.winfo_width() or (WIN_W - 20)
        tw = max(80, (cw - 2 * H_PAD - (COLS - 1) * GAP) // COLS)
        th = int(tw * 9 / 16)

        for row_i in range(0, len(items), COLS):
            row = tk.Frame(self._grid, bg=BG)
            row.pack(fill="x", padx=H_PAD, pady=(GAP, 0))
            for col_i in range(COLS):
                idx = row_i + col_i
                if idx >= len(items):
                    tk.Frame(row, bg=BG, width=tw, height=th).pack(
                        side="left", padx=(0, GAP if col_i < COLS - 1 else 0))
                    continue
                h, info = items[idx]
                card = _Card(row, h, info, tw, th, self._on_action)
                card.pack(side="left", padx=(0, GAP if col_i < COLS - 1 else 0))
                self._cards.append(card)

        threading.Thread(
            target=self._load_thumbs, args=(items, tw, th, tok),
            daemon=True,
        ).start()

    def _load_thumbs(self, items, tw, th, tok):
        card_map = {c.file_hash: c for c in self._cards}

        def load_one(h_info):
            h, info = h_info
            if tok != self._render_tok:
                return h, None
            path = info.get("path", "")
            if not os.path.exists(path):
                return h, None
            try:
                with Image.open(path) as img:
                    img = img.convert("RGB")
                    img.thumbnail((tw, th), Image.LANCZOS)
                    bg = Image.new("RGB", (tw, th), (22, 27, 34))
                    bg.paste(img, ((tw - img.width) // 2, (th - img.height) // 2))
                    return h, bg
            except Exception:
                return h, None

        with ThreadPoolExecutor(max_workers=8) as pool:
            for future in as_completed(pool.submit(load_one, item) for item in items):
                if tok != self._render_tok:
                    return
                h, pil_img = future.result()
                if pil_img is None:
                    continue
                card = card_map.get(h)
                if card:
                    self.root.after(0, lambda c=card, img=pil_img, t=tok:
                                    self._apply_pil(c, img, t))

    def _apply_pil(self, card, pil_img, tok):
        if tok != self._render_tok:
            return
        try:
            photo = ImageTk.PhotoImage(pil_img)
            self._photos.append(photo)
            card.set_photo(photo)
        except tk.TclError:
            pass

    # ── Fetch ─────────────────────────────────────────────────────────────────

    def _fetch_new(self):
        if self._fetching:
            return
        self._fetching = True
        self._count_lbl.config(text="Fetching…", fg=ACC)

        def _run():
            cfg   = manager.load_config()
            min_w = manager.res_to_min_width(cfg.get("min_resolution", "1080p"))
            count = downloader.fetch(
                count=5,
                queries=cfg.get("categories", ["nature"]),
                unsplash_key=cfg.get("unsplash_key", ""),
                min_width=min_w,
            )
            manager.register_all_inbox()
            self._fetching = False
            msg = (f"{count} fetched" if count > 0 else "Nothing new")
            self.root.after(0, lambda: self._count_lbl.config(text=msg, fg=ACC))
            self.root.after(0, self.refresh)
            self.root.after(3000, lambda: self._count_lbl.config(fg=FG_MUT))
            # Also notify via tray
            icon = self.state.get("icon")
            if icon and count > 0:
                try:
                    icon.notify(
                        f"{count} new wallpaper{'s' if count != 1 else ''} downloaded.",
                        "Wallpaper App",
                    )
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_action(self, file_hash, action):
        meta = manager.load_meta()
        info = meta.get(file_hash)
        if not isinstance(info, dict):
            return

        if action == "set":
            path = info.get("path", "")
            if os.path.exists(path):
                cfg = manager.load_config()
                wallpaper.set_wallpaper(path, cfg.get("wallpaper_style", "Fill"))
                meta[file_hash]["used_as_wallpaper"] = True
                manager.push_recent(meta, file_hash)
                manager.save_meta(meta)
                self._count_lbl.config(text="Wallpaper set!", fg=ACC)
                self.root.after(2000, self.refresh)

        elif action == "like":
            meta[file_hash]["liked"]    = not info.get("liked", False)
            meta[file_hash]["reviewed"] = True
            manager.save_meta(meta)
            self.refresh()

        elif action == "favorite":
            path = info.get("path", "")
            if info.get("favorite"):
                new_path = manager.get_unique_path(manager.INBOX, os.path.basename(path))
                if os.path.exists(path):
                    shutil.move(path, new_path)
                meta[file_hash].update({"path": new_path, "favorite": False})
            else:
                if os.path.exists(path):
                    new_path = manager.get_unique_path(manager.FAV, os.path.basename(path))
                    shutil.move(path, new_path)
                    meta[file_hash].update({
                        "path": new_path, "favorite": True,
                        "liked": True,    "reviewed": True,
                    })
            manager.save_meta(meta)
            self.refresh()

        elif action == "delete":
            path = info.get("path", "")
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            del meta[file_hash]
            manager.save_meta(meta)
            if self._hero_hash == file_hash:
                self._hero_hash = None
            self.refresh()

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def _on_close(self):
        # Hide to tray; only fully exit via tray → Exit
        self.root.withdraw()


def run_app(state):
    root = tk.Tk()
    state["root"] = root
    app = WallpaperApp(root, state)
    state["app"]  = app
    root.mainloop()
    state["root"] = None
    state["app"]  = None
