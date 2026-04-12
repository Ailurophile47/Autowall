"""
ui/settings.py
Settings window. Saves to config/config.json and handles autostart registry.
"""
import os
import sys
import tkinter as tk
from tkinter import ttk
import winreg

from core.manager import load_config, save_config

BG     = "#101418"
BG2    = "#161c24"
FG     = "#dbe4ee"
FG_DIM = "#6b7a8d"
ACC    = "#6fcf97"

APP_NAME = "Autowall"

BIAS_PRESETS = [("Balanced", 50), ("Recommended", 70), ("Strong", 85), ("Maximum", 100)]

ALL_CATEGORIES = [
    "nature", "dark", "minimal", "space", "cyberpunk", "landscape",
    "architecture", "travel", "cityscape", "astrophotography", "aesthetics",
    "sea", "mountains", "forest", "sunset", "sunrise", "abstract",
    "artistic", "vintage", "retro",
]

INTERVALS = [("Every hour", 1), ("Every 6 hours", 6),
             ("Every 12 hours", 12), ("Daily", 24)]

HOURS   = [f"{h:02d}" for h in range(24)]
MINUTES = [f"{m:02d}" for m in range(0, 60, 5)]

RESOLUTIONS = [("1080p (1920×1080)", "1080p"),
               ("2K (2560×1440)", "2K"),
               ("4K (3840×2160)", "4K")]


def _get_autostart():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False


def _set_autostart(enable):
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    exe = sys.executable
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if enable:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe}"')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


class _Settings:
    def __init__(self, root):
        self.root = root
        self.root.title("Autowall — Settings")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        w, h = 520, 780
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x  = (sw - w) // 2
        y  = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        self.cfg = load_config()
        self._build_ui()

    def _label(self, parent, text, bold=False):
        font = ("Segoe UI", 10, "bold") if bold else ("Segoe UI", 10)
        tk.Label(parent, text=text, fg=FG, bg=BG, font=font).pack(anchor="w", pady=(10, 2))

    def _section(self, text):
        tk.Label(self.root, text=text, fg=ACC, bg=BG,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=20, pady=(14, 2))

    def _build_ui(self):
        canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        scroll = tk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        frame  = tk.Frame(canvas, bg=BG)

        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        def section(text):
            tk.Label(frame, text=text, fg=ACC, bg=BG,
                     font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=20, pady=(14, 2))

        def label(text):
            tk.Label(frame, text=text, fg=FG_DIM, bg=BG,
                     font=("Segoe UI", 9)).pack(anchor="w", padx=20)

        # ── Change Interval ────────────────────────────────────────────────────
        section("Change Interval")
        self._interval_var = tk.IntVar(value=self.cfg.get("interval_hours", 24))
        row = tk.Frame(frame, bg=BG)
        row.pack(anchor="w", padx=30)
        for text, hours in INTERVALS:
            tk.Radiobutton(row, text=text, variable=self._interval_var, value=hours,
                           fg=FG, bg=BG, selectcolor=BG2, activebackground=BG,
                           activeforeground=FG, font=("Segoe UI", 10)).pack(anchor="w")

        # ── Scheduled Time ─────────────────────────────────────────────────────
        section("Scheduled Change Time  (optional)")
        label("Change wallpaper at a fixed time every day:")

        saved_time = self.cfg.get("change_time", "")
        self._use_time_var = tk.BooleanVar(value=bool(saved_time))

        time_row = tk.Frame(frame, bg=BG)
        time_row.pack(anchor="w", padx=30, pady=(4, 0))

        tk.Checkbutton(
            time_row, text="Enable scheduled time",
            variable=self._use_time_var,
            fg=FG, bg=BG, selectcolor=BG2, activebackground=BG,
            activeforeground=FG, font=("Segoe UI", 10),
            command=self._toggle_time_picker,
        ).pack(anchor="w")

        self._time_picker_frame = tk.Frame(frame, bg=BG)
        self._time_picker_frame.pack(anchor="w", padx=46, pady=(4, 0))

        hh = saved_time[:2] if len(saved_time) == 5 else "08"
        mm_raw = saved_time[3:] if len(saved_time) == 5 else "00"
        # snap minute to nearest 5-min slot
        mm = f"{(int(mm_raw) // 5) * 5:02d}"

        self._hour_var   = tk.StringVar(value=hh)
        self._minute_var = tk.StringVar(value=mm)

        tk.Label(self._time_picker_frame, text="Hour:", fg=FG_DIM, bg=BG,
                 font=("Segoe UI", 9)).pack(side="left")
        self._hour_spin = tk.Spinbox(
            self._time_picker_frame, values=HOURS, textvariable=self._hour_var,
            width=4, bg=BG2, fg=FG, buttonbackground=BG2, relief="flat",
            font=("Segoe UI", 10), state="readonly",
            readonlybackground=BG2, disabledbackground=BG,
            disabledforeground=FG_DIM,
        )
        self._hour_spin.pack(side="left", padx=(4, 10))

        tk.Label(self._time_picker_frame, text="Minute:", fg=FG_DIM, bg=BG,
                 font=("Segoe UI", 9)).pack(side="left")
        self._min_spin = tk.Spinbox(
            self._time_picker_frame, values=MINUTES, textvariable=self._minute_var,
            width=4, bg=BG2, fg=FG, buttonbackground=BG2, relief="flat",
            font=("Segoe UI", 10), state="readonly",
            readonlybackground=BG2, disabledbackground=BG,
            disabledforeground=FG_DIM,
        )
        self._min_spin.pack(side="left", padx=(4, 0))

        tk.Label(self._time_picker_frame, text="(24-hr)", fg=FG_DIM, bg=BG,
                 font=("Segoe UI", 8)).pack(side="left", padx=(8, 0))

        self._toggle_time_picker()   # set initial enabled/disabled state

        # ── Minimum Resolution ─────────────────────────────────────────────────
        section("Minimum Resolution")
        self._res_var = tk.StringVar(value=self.cfg.get("min_resolution", "1080p"))
        row = tk.Frame(frame, bg=BG)
        row.pack(anchor="w", padx=30)
        for text, val in RESOLUTIONS:
            tk.Radiobutton(row, text=text, variable=self._res_var, value=val,
                           fg=FG, bg=BG, selectcolor=BG2, activebackground=BG,
                           activeforeground=FG, font=("Segoe UI", 10)).pack(anchor="w")

        section("Recommendation Bias")
        label("How strongly likes and dislikes should affect fetches and wallpaper rotation:")
        self._bias_var = tk.IntVar(value=int(self.cfg.get("preference_bias_percent", 70)))
        row = tk.Frame(frame, bg=BG)
        row.pack(anchor="w", padx=30)
        for text, value in BIAS_PRESETS:
            tk.Radiobutton(
                row, text=f"{text} ({value}/{100 - value})",
                variable=self._bias_var, value=value,
                fg=FG, bg=BG, selectcolor=BG2, activebackground=BG,
                activeforeground=FG, font=("Segoe UI", 10),
            ).pack(anchor="w")

        # ── Categories ─────────────────────────────────────────────────────────
        section("Categories")
        label("Select which themes to download from Unsplash:")
        active = set(self.cfg.get("categories", []))
        self._cat_vars = {}
        cat_frame = tk.Frame(frame, bg=BG)
        cat_frame.pack(anchor="w", padx=30)
        cols = 3
        for i, cat in enumerate(ALL_CATEGORIES):
            var = tk.BooleanVar(value=cat in active)
            self._cat_vars[cat] = var
            tk.Checkbutton(cat_frame, text=cat, variable=var,
                           fg=FG, bg=BG, selectcolor=BG2, activebackground=BG,
                           activeforeground=FG, font=("Segoe UI", 9)
                           ).grid(row=i // cols, column=i % cols, sticky="w", padx=6, pady=1)

        # ── Toggles ────────────────────────────────────────────────────────────
        section("Options")
        self._fav_var   = tk.BooleanVar(value=self.cfg.get("favorites_only", False))
        self._auto_var  = tk.BooleanVar(value=_get_autostart())

        tog_frame = tk.Frame(frame, bg=BG)
        tog_frame.pack(anchor="w", padx=30)
        tk.Checkbutton(tog_frame, text="Favorites Only Mode",
                       variable=self._fav_var,
                       fg=FG, bg=BG, selectcolor=BG2, activebackground=BG,
                       activeforeground=FG, font=("Segoe UI", 10)).pack(anchor="w")
        tk.Checkbutton(tog_frame, text="Start automatically with Windows",
                       variable=self._auto_var,
                       fg=FG, bg=BG, selectcolor=BG2, activebackground=BG,
                       activeforeground=FG, font=("Segoe UI", 10)).pack(anchor="w")

        # ── Unsplash Key ───────────────────────────────────────────────────────
        section("Unsplash API Key")
        label("Your Access Key (not the Secret Key):")
        key_frame = tk.Frame(frame, bg=BG)
        key_frame.pack(anchor="w", padx=20, pady=(4, 0), fill="x")
        self._key_var = tk.StringVar(value=self.cfg.get("unsplash_key", ""))
        tk.Entry(key_frame, textvariable=self._key_var, width=52,
                 bg=BG2, fg=FG, insertbackground=FG, relief="flat",
                 font=("Consolas", 9)).pack(anchor="w", ipady=5, padx=2)

        # ── Save button ────────────────────────────────────────────────────────
        tk.Frame(frame, bg=BG, height=10).pack()
        tk.Button(frame, text="Save Settings", command=self._save,
                  bg=ACC, fg="#101418", activebackground="#52b380",
                  font=("Segoe UI", 11, "bold"), relief="flat",
                  cursor="hand2", padx=20, pady=8).pack(pady=(8, 20))

        self._saved_label = tk.Label(frame, text="", fg=ACC, bg=BG, font=("Segoe UI", 10))
        self._saved_label.pack()

    def _toggle_time_picker(self):
        state = "readonly" if self._use_time_var.get() else "disabled"
        self._hour_spin.config(state=state)
        self._min_spin.config(state=state)
        fg = FG if self._use_time_var.get() else FG_DIM
        for w in self._time_picker_frame.winfo_children():
            try:
                w.config(fg=fg)
            except Exception:
                pass

    def _save(self):
        self.cfg["interval_hours"]  = self._interval_var.get()
        self.cfg["min_resolution"]  = self._res_var.get()
        self.cfg["preference_bias_percent"] = self._bias_var.get()
        self.cfg["categories"]      = [c for c, v in self._cat_vars.items() if v.get()]
        self.cfg["favorites_only"]  = self._fav_var.get()
        self.cfg["unsplash_key"]    = self._key_var.get().strip()
        if self._use_time_var.get():
            self.cfg["change_time"] = f"{self._hour_var.get()}:{self._minute_var.get()}"
        else:
            self.cfg["change_time"] = ""

        save_config(self.cfg)
        _set_autostart(self._auto_var.get())

        self._saved_label.config(text="✓  Settings saved")
        self.root.after(2000, lambda: self._saved_label.config(text=""))


def run_settings():
    root = tk.Tk()
    _Settings(root)
    root.mainloop()


if __name__ == "__main__":
    run_settings()
