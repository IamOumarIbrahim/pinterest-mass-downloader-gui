"""The desktop app."""

from __future__ import annotations

import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageGrab

from . import APP_NAME, __version__, library, settings
from .matching import MatchSettings, Palette, allowed_ranges, extract_palette
from .media import fetch_bytes
from . import scraper
from .scraper import is_url
from .worker import (KINDS, LABEL, Event, Job, Worker, follow_job, picks_job, safe_name,
                     similar_job)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:  # drag and drop is a nicety, not a requirement
    HAS_DND = False

# ── look & feel (light, dark) ───────────────────────────────────────────────
BG = ("#F3F3F6", "#0E0E11")
CARD = ("#FFFFFF", "#17171C")
CARD_2 = ("#F1F1F4", "#1F1F26")
BORDER = ("#E2E2E8", "#2A2A33")
TEXT = ("#121216", "#F2F2F5")
MUTED = ("#6A6A75", "#9C9CA8")
ACCENT = "#E60023"
ACCENT_HOVER = "#C2001E"
KIND_COLOR = {"image": "#3B82F6", "video": "#8B5CF6", "gif": "#14B8A6"}
KIND_ICON = {"image": "🖼", "video": "🎬", "gif": "✨"}
LOG_COLOR = {"info": None, "success": "#1DB954", "warning": "#E0A100", "error": "#FF4D4F"}
TILE = 132
FONT = "Segoe UI"

SIZES = {"Any size": 0, "600 px+": 600, "1000 px+": 1000, "1500 px+": 1500, "2000 px+": 2000}
SHAPE_NAMES = {"Any": "any", "Tall": "tall", "Wide": "wide", "Square": "square"}


def font(size=13, weight="normal"):
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


def describe_tolerance(v: float) -> str:
    if v < 15:
        return "Strict: same colors in almost the same amounts"
    if v < 40:
        return "Close: same colors, amounts may shift a little"
    if v < 70:
        return "Relaxed: same colors, amounts can change a lot"
    return "Loose: same colors in any amount"


def describe_closeness(v: float) -> str:
    if v < 25:
        return "Loosely related"
    if v < 60:
        return "Similar"
    if v < 85:
        return "Very similar"
    return "Nearly identical"


_Base = (ctk.CTk, TkinterDnD.DnDWrapper) if HAS_DND else (ctk.CTk,)


class Card(ctk.CTkFrame):
    def __init__(self, parent, title: str, subtitle: str = "", **kw):
        super().__init__(parent, fg_color=CARD, corner_radius=14, border_width=1,
                         border_color=BORDER, **kw)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(head, text=title, font=font(15, "bold"), text_color=TEXT).pack(side="left")
        if subtitle:
            ctk.CTkLabel(head, text=subtitle, font=font(12), text_color=MUTED).pack(
                side="left", padx=(8, 0), pady=(2, 0))
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="x", padx=16, pady=(0, 14))


class CountRow(ctk.CTkFrame):
    """Icon + name, slider, editable number."""

    def __init__(self, parent, kind: str, value: int, maximum: int):
        super().__init__(parent, fg_color="transparent")
        self.maximum = maximum
        self.var = ctk.StringVar(value=str(value))
        colour = KIND_COLOR[kind]
        badge = ctk.CTkLabel(self, text=KIND_ICON[kind], width=34, height=34, corner_radius=10,
                             fg_color=colour, text_color="white", font=font(15))
        badge.grid(row=0, column=0, padx=(0, 10))
        ctk.CTkLabel(self, text={"image": "Pictures", "video": "Videos", "gif": "GIFs"}[kind], font=font(13, "bold"),
                     text_color=TEXT, width=70, anchor="w").grid(row=0, column=1)
        self.slider = ctk.CTkSlider(self, from_=0, to=maximum, number_of_steps=maximum,
                                    progress_color=colour, button_color=colour,
                                    button_hover_color=colour, command=self._slid)
        self.slider.set(value)
        self.slider.grid(row=0, column=2, sticky="ew", padx=8)
        self.entry = ctk.CTkEntry(self, textvariable=self.var, width=56, justify="center",
                                  font=font(14, "bold"), border_color=BORDER, fg_color=CARD_2)
        self.entry.grid(row=0, column=3)
        self.entry.bind("<FocusOut>", self._typed)
        self.entry.bind("<Return>", self._typed)
        self.columnconfigure(2, weight=1)

    def _slid(self, v):
        self.var.set(str(int(round(v))))

    def _typed(self, _=None):
        self.slider.set(min(self.value, self.maximum))

    @property
    def value(self) -> int:
        try:
            return max(0, min(int(float(self.var.get() or 0)), 2000))
        except ValueError:
            return 0

    def set(self, v: int):
        self.var.set(str(v))
        self.slider.set(min(v, self.maximum))


class PhoneControl:
    """Lets the phone page start searches in this window's queue.

    The phone server calls these from its own threads; anything that touches
    the window is handed to the main thread through ui_q.
    """

    def __init__(self, app: "App"):
        self.app = app
        self.state = {"running": False, "query": "", "phase": "", "done": 0, "total": 0,
                      "waiting": 0, "finished": 0, "last": ""}

    def submit(self, query: str, counts: dict):
        from .remote import clean_counts
        query = " ".join(query.split())
        counts = clean_counts(counts)
        if not query:
            return "Type something to search for."
        if not any(counts.values()):
            return "Ask for at least one picture, video or GIF."
        self.app.ui_q.put(lambda: self.app.remote_search(query, counts))
        return None

    def status(self) -> dict:
        return dict(self.state)

    def stop(self):
        self.app.ui_q.put(self.app.stop)


class App(*_Base):
    def __init__(self):
        super().__init__()
        if HAS_DND:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
            except Exception:
                pass
        self.cfg = settings.load()
        ctk.set_appearance_mode(self.cfg.get("appearance", "System"))
        self.title(APP_NAME)
        icon = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except Exception:
                pass
        self.geometry("1320x860")
        self.minsize(1080, 700)
        self.configure(fg_color=BG)

        self.events: "queue.Queue[Event]" = queue.Queue()
        self.ui_q: queue.Queue = queue.Queue()
        self.thumbs = ThreadPoolExecutor(max_workers=3)
        self.worker: Worker | None = None
        self.queue_items: list[dict] = []
        self.current: dict | None = None
        self.running = False
        self.started = 0.0
        self.palette: Palette | None = None
        self.palette_edited = False
        self.tiles: list[ctk.CTkFrame] = []
        self.tile_images: list = []
        self.lib = library.shared()
        self.indexing = False
        self.cands: list[dict] = []        # preview candidates: {ev, tile, cap, picked}
        self.pick_job: Job | None = None   # the preview the candidates came from
        self.counters = {k: 0 for k in KINDS}
        self.phone = None
        self.phone_win = None
        self.closing = False
        self._lib_token = None
        self.remote = PhoneControl(self)
        if not self.cfg.get("phone_token"):
            from .phone import new_token
            self.cfg["phone_token"] = new_token()

        self._build()
        self._load_reference(self.cfg.get("reference") or "", quiet=True)
        if self.cfg.get("palette_edited") and self.cfg.get("palette"):
            self.palette = Palette.from_entries(self.cfg["palette"])
            self.palette_edited = True
            self._render_palette()
            self._refresh_match_ui()
        self.bind_all("<Control-v>", self._paste, add="+")
        self.bind("<Configure>", self._on_resize, add="+")
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(60, self._pump)
        if self.cfg.get("phone_autostart"):
            self.after(800, self._phone_start)
        if self.cfg.get("follow_autocheck", True):
            # at most once every few hours, so reopening the app doesn't hammer Pinterest
            self.after(1500, lambda: self.check_follows(older_than=3 * 3600))

    # ── layout ──────────────────────────────────────────────────────────
    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=64)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_propagate(False)
        logo = ctk.CTkLabel(header, text="P", width=38, height=38, corner_radius=19,
                            fg_color=ACCENT, text_color="white", font=font(20, "bold"))
        logo.pack(side="left", padx=(20, 12), pady=13)
        ctk.CTkLabel(header, text=APP_NAME, font=font(18, "bold"), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(header, text=f"v{__version__}", font=font(12), text_color=MUTED).pack(
            side="left", padx=8, pady=(4, 0))
        self.theme_btn = ctk.CTkSegmentedButton(
            header, values=["Light", "Dark", "System"], command=self._set_theme,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER, font=font(12))
        self.theme_btn.set(self.cfg.get("appearance", "System"))
        self.theme_btn.pack(side="right", padx=20)
        self.phone_btn = ctk.CTkButton(header, text="📱  Phone", width=110, height=34,
                                       corner_radius=17, font=font(13, "bold"), fg_color=CARD_2,
                                       hover_color=BORDER, text_color=TEXT, command=self.open_phone)
        self.phone_btn.pack(side="right")
        self.update_btn = ctk.CTkButton(header, text="", height=34, corner_radius=17,
                                        font=font(12, "bold"), fg_color="#1DB954",
                                        hover_color="#17a349", text_color="white")
        threading.Thread(target=self._check_update, daemon=True).start()

        self._build_left()
        self._build_right()

    def _build_left(self):
        left = ctk.CTkFrame(self, fg_color="transparent", width=460)
        left.grid(row=1, column=0, sticky="nsw", padx=(18, 8), pady=16)
        left.grid_rowconfigure(0, weight=1)
        left.grid_propagate(False)

        scroll = ctk.CTkScrollableFrame(left, fg_color="transparent", width=440,
                                        scrollbar_button_color=BORDER)
        scroll.grid(row=0, column=0, sticky="nsew")
        left.grid_columnconfigure(0, weight=1)
        self.left_scroll = scroll

        # Search
        c = Card(scroll, "What are you looking for?")
        c.pack(fill="x", pady=(0, 12))
        self.search = ctk.CTkEntry(c.body, height=46, corner_radius=12, font=font(15),
                                   placeholder_text="Try “fortnite”, or paste a board / pin link",
                                   border_color=BORDER, fg_color=CARD_2)
        self.search.pack(fill="x")
        self.search.bind("<Return>", lambda _: self.start())
        self.search.bind("<KeyRelease>", lambda _: self._update_mode_hint())
        self.mode_hint = ctk.CTkLabel(c.body, text="", font=font(12), text_color=MUTED, anchor="w",
                                      justify="left", wraplength=390)
        self.mode_hint.pack(fill="x", pady=(6, 0))
        self.recent_row = ctk.CTkFrame(c.body, fg_color="transparent", height=1)
        self._render_recent()
        self._update_mode_hint()

        # Counts
        c = Card(scroll, "How many?", "set any to 0 to skip it")
        c.pack(fill="x", pady=(0, 12))
        self.rows = {
            "image": CountRow(c.body, "image", self.cfg["image"], 300),
            "video": CountRow(c.body, "video", self.cfg["video"], 100),
            "gif": CountRow(c.body, "gif", self.cfg["gif"], 100),
        }
        for r in self.rows.values():
            r.pack(fill="x", pady=4)
        qrow = ctk.CTkFrame(c.body, fg_color="transparent")
        qrow.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(qrow, text="Shape", font=font(12), text_color=MUTED).pack(side="left")
        self.shape = ctk.CTkSegmentedButton(
            qrow, values=list(SHAPE_NAMES), font=font(12), selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER, height=28)
        self.shape.set(next((n for n, v in SHAPE_NAMES.items() if v == self.cfg.get("shape")), "Any"))
        self.shape.pack(side="left", padx=(8, 0))
        self.size = ctk.CTkOptionMenu(
            qrow, values=list(SIZES), width=110, height=28, font=font(12), fg_color=CARD_2,
            button_color=CARD_2, button_hover_color=BORDER, text_color=TEXT,
            dropdown_font=font(12))
        self.size.set(next((n for n, v in SIZES.items() if v == self.cfg.get("min_side")), "Any size"))
        self.size.pack(side="right")
        self.pick_first = ctk.BooleanVar(value=bool(self.cfg.get("pick_first")))
        ctk.CTkSwitch(c.body, text="Let me pick first", variable=self.pick_first,
                      progress_color=ACCENT, font=font(12, "bold"), text_color=TEXT,
                      command=self._update_go).pack(anchor="w", pady=(10, 0))
        ctk.CTkLabel(c.body, text="Shows small previews. You click the ones you want, and only "
                                  "those are downloaded.", font=font(11), text_color=MUTED,
                     anchor="w", justify="left", wraplength=390).pack(fill="x", pady=(2, 0))

        # Reference matching
        c = Card(scroll, "Match a picture", "optional")
        c.pack(fill="x", pady=(0, 12))
        self._build_reference(c.body)

        # Folder
        c = Card(scroll, "Save to")
        c.pack(fill="x", pady=(0, 12))
        row = ctk.CTkFrame(c.body, fg_color="transparent")
        row.pack(fill="x")
        self.folder = ctk.StringVar(value=self.cfg["folder"])
        ctk.CTkEntry(row, textvariable=self.folder, height=36, border_color=BORDER,
                     fg_color=CARD_2, font=font(12)).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="Browse", width=80, height=36, fg_color=CARD_2,
                      hover_color=BORDER, text_color=TEXT, command=self._browse).pack(
            side="left", padx=(8, 0))
        self.subfolders = ctk.BooleanVar(value=self.cfg["subfolders"])
        ctk.CTkSwitch(c.body, text="Put each search in its own folder", variable=self.subfolders,
                      progress_color=ACCENT, font=font(12), text_color=TEXT).pack(
            anchor="w", pady=(10, 0))
        self.skip_owned = ctk.BooleanVar(value=bool(self.cfg.get("skip_owned", True)))
        ctk.CTkSwitch(c.body, text="Skip pictures I already have (in any folder)",
                      variable=self.skip_owned, progress_color=ACCENT, font=font(12),
                      text_color=TEXT).pack(anchor="w", pady=(8, 0))

        # Account
        c = Card(scroll, "Pinterest login", "optional")
        c.pack(fill="x", pady=(0, 12))
        self.login_lbl = ctk.CTkLabel(c.body, text="", font=font(12), text_color=MUTED,
                                      anchor="w", justify="left", wraplength=390)
        self.login_lbl.pack(fill="x")
        row = ctk.CTkFrame(c.body, fg_color="transparent")
        row.pack(fill="x", pady=(8, 0))
        ctk.CTkButton(row, text="Use cookies file…", height=30, corner_radius=15, font=font(12),
                      fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                      command=self._login_file).pack(side="left")
        self.logout_btn = ctk.CTkButton(row, text="Sign out", height=30, width=80, corner_radius=15,
                                        font=font(12), fg_color="transparent", hover_color=BORDER,
                                        text_color=MUTED, command=lambda: self._set_login(None))
        self._set_login(settings.load_cookies(), quiet=True)

        # Advanced
        c = Card(scroll, "Speed")
        c.pack(fill="x", pady=(0, 4))
        row = ctk.CTkFrame(c.body, fg_color="transparent")
        row.pack(fill="x")
        self.threads = ctk.IntVar(value=self.cfg["threads"])
        ctk.CTkLabel(row, text="Parallel downloads", font=font(12), text_color=MUTED).pack(side="left")
        self.threads_lbl = ctk.CTkLabel(row, text=str(self.threads.get()), font=font(13, "bold"),
                                        text_color=TEXT, width=30)
        self.threads_lbl.pack(side="right")
        ctk.CTkSlider(c.body, from_=1, to=32, number_of_steps=31, variable=self.threads,
                      progress_color=ACCENT, button_color=ACCENT, button_hover_color=ACCENT_HOVER,
                      command=lambda v: self.threads_lbl.configure(text=str(int(v)))).pack(
            fill="x", pady=(6, 0))

        # Actions (pinned below the scroll area)
        actions = ctk.CTkFrame(left, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        actions.grid_columnconfigure(0, weight=1)
        self.go_btn = ctk.CTkButton(actions, text="Download", height=52, corner_radius=14,
                                    fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                    font=font(17, "bold"), command=self.start)
        self.go_btn.grid(row=0, column=0, sticky="ew")
        self.queue_btn = ctk.CTkButton(actions, text="+ Queue", width=100, height=52,
                                       corner_radius=14, fg_color=CARD, hover_color=CARD_2,
                                       border_width=1, border_color=BORDER, text_color=TEXT,
                                       font=font(14, "bold"), command=self.add_to_queue)
        self.queue_btn.grid(row=0, column=1, padx=(10, 0))

    def _build_reference(self, body):
        self.drop = ctk.CTkFrame(body, height=150, fg_color=CARD_2, corner_radius=12,
                                 border_width=2, border_color=BORDER)
        self.drop.pack(fill="x")
        self.drop.pack_propagate(False)
        self.drop_img = ctk.CTkLabel(self.drop, text="", width=130)
        self.drop_text = ctk.CTkLabel(
            self.drop, font=font(13), text_color=MUTED, justify="center",
            text="Drop a picture here\nor click to choose one\n\nCtrl+V pastes from clipboard")
        self.drop_text.pack(expand=True)
        for w in (self.drop, self.drop_text, self.drop_img):
            w.bind("<Button-1>", lambda _: self._choose_reference())
            w.configure(cursor="hand2")
        if HAS_DND:
            try:  # the whole window accepts dropped pictures
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass
        self.clear_ref_btn = ctk.CTkButton(self.drop, text="✕", width=28, height=28,
                                           corner_radius=14, fg_color=CARD,
                                           hover_color=ACCENT, text_color=TEXT,
                                           command=lambda: self._load_reference(""))

        checks = ctk.CTkFrame(body, fg_color="transparent")
        checks.pack(fill="x", pady=(12, 0))
        self.look = ctk.BooleanVar(value=self.cfg["look"])
        self.colors = ctk.BooleanVar(value=self.cfg["colors"])
        self.match_boxes = {}
        for key, var, text in (("look", self.look, "Looks similar"),
                               ("colors", self.colors, "Similar colors")):
            cb = ctk.CTkCheckBox(checks, text=text, variable=var, command=self._refresh_match_ui,
                                 fg_color=ACCENT, hover_color=ACCENT_HOVER, font=font(13, "bold"),
                                 text_color=TEXT, border_color=MUTED)
            cb.pack(side="left", padx=(0, 18))
            self.match_boxes[key] = cb

        # describe it in words (smart model)
        from . import smart
        self.smart_ok = smart.available()
        self.describe = ctk.StringVar(value=self.cfg.get("describe", "") if self.smart_ok else "")
        self.smart = ctk.BooleanVar(value=bool(self.cfg.get("smart", True)) and self.smart_ok)
        self.describe_box = ctk.CTkFrame(body, fg_color="transparent")
        if self.smart_ok:
            self.describe_box.pack(fill="x", pady=(12, 0))
        self.describe_entry = ctk.CTkEntry(
            self.describe_box, textvariable=self.describe, height=36, corner_radius=10,
            font=font(13), border_color=BORDER, fg_color=CARD_2,
            placeholder_text="Or describe it: line drawing, no words")
        self.describe_entry.pack(fill="x")
        self.describe_entry.bind("<KeyRelease>", lambda _: self._refresh_match_ui())
        self.describe_entry.bind("<Return>", lambda _: self.start())
        srow = ctk.CTkFrame(self.describe_box, fg_color="transparent")
        srow.pack(fill="x", pady=(8, 0))
        ctk.CTkSwitch(srow, text="Smart matching", variable=self.smart, progress_color=ACCENT,
                      font=font(12, "bold"), text_color=TEXT,
                      command=self._refresh_match_ui).pack(side="left")
        self.smart_lbl = ctk.CTkLabel(srow, text="", font=font(11), text_color=MUTED, anchor="e")
        self.smart_lbl.pack(side="right")

        # look options
        self.look_box = ctk.CTkFrame(body, fg_color="transparent")
        top = ctk.CTkFrame(self.look_box, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text="How close?", font=font(12), text_color=MUTED).pack(side="left")
        self.close_lbl = ctk.CTkLabel(top, text="", font=font(12, "bold"), text_color=TEXT)
        self.close_lbl.pack(side="right")
        self.closeness = ctk.DoubleVar(value=self.cfg["closeness"])
        ctk.CTkSlider(self.look_box, from_=0, to=100, variable=self.closeness,
                      progress_color=ACCENT, button_color=ACCENT, button_hover_color=ACCENT_HOVER,
                      command=lambda _: self._refresh_match_ui()).pack(fill="x", pady=(4, 0))

        # colour options
        self.color_box = ctk.CTkFrame(body, fg_color="transparent")
        head = ctk.CTkFrame(self.color_box, fg_color="transparent")
        head.pack(fill="x")
        self.colors_title = ctk.CTkLabel(head, text="", font=font(12), text_color=MUTED, anchor="w")
        self.colors_title.pack(side="left")
        self.pick_btn = ctk.CTkButton(head, text="+ Pick a color", width=10, height=26,
                                      corner_radius=13, font=font(12, "bold"), fg_color=CARD_2,
                                      hover_color=BORDER, text_color=TEXT, command=self._pick_color)
        self.pick_btn.pack(side="right")
        self.reset_btn = ctk.CTkButton(head, text="Reset", width=10, height=26, corner_radius=13,
                                       font=font(12), fg_color="transparent", hover_color=BORDER,
                                       text_color=MUTED, command=self._reset_palette)
        self.bar = ctk.CTkFrame(self.color_box, height=26, corner_radius=8, fg_color=CARD_2)
        self.bar.pack(fill="x", pady=(6, 6))
        self.swatches = ctk.CTkFrame(self.color_box, fg_color="transparent", height=1)
        self.swatches.pack(fill="x")
        top = ctk.CTkFrame(self.color_box, fg_color="transparent")
        top.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(top, text="Color tolerance", font=font(12), text_color=MUTED).pack(side="left")
        self.tol_val = ctk.CTkLabel(top, text="", font=font(12, "bold"), text_color=TEXT)
        self.tol_val.pack(side="right")
        self.tolerance = ctk.DoubleVar(value=self.cfg["color_tolerance"])
        self.tol_slider = ctk.CTkSlider(
            self.color_box, from_=0, to=100, variable=self.tolerance, progress_color=ACCENT,
            button_color=ACCENT, button_hover_color=ACCENT_HOVER,
            command=lambda _: self._refresh_match_ui())
        self.tol_slider.pack(fill="x", pady=(4, 0))
        ends = ctk.CTkFrame(self.color_box, fg_color="transparent")
        ends.pack(fill="x")
        ctk.CTkLabel(ends, text="same amounts", font=font(11), text_color=MUTED).pack(side="left")
        ctk.CTkLabel(ends, text="any amounts", font=font(11), text_color=MUTED).pack(side="right")
        self.tol_lbl = ctk.CTkLabel(self.color_box, text="", font=font(12), text_color=TEXT,
                                    anchor="w", justify="left", wraplength=390)
        self.tol_lbl.pack(fill="x", pady=(2, 0))

        self.match_hint = ctk.CTkLabel(body, text="", font=font(12), text_color=MUTED,
                                       anchor="w", justify="left", wraplength=390)
        self.match_hint.pack(fill="x", pady=(8, 0))

    def _build_right(self):
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 18), pady=16)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=3)
        right.grid_rowconfigure(2, weight=2)

        # status
        st = ctk.CTkFrame(right, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER)
        st.grid(row=0, column=0, sticky="ew")
        st.grid_columnconfigure(0, weight=1)
        self.status = ctk.CTkLabel(st, text="Ready when you are.", font=font(15, "bold"),
                                   text_color=TEXT, anchor="w")
        self.status.grid(row=0, column=0, sticky="w", padx=16, pady=(12, 0))
        self.elapsed = ctk.CTkLabel(st, text="", font=font(12), text_color=MUTED)
        self.elapsed.grid(row=0, column=1, padx=16, pady=(12, 0))
        self.bar_progress = ctk.CTkProgressBar(st, height=10, corner_radius=5, progress_color=ACCENT)
        self.bar_progress.set(0)
        self.bar_progress.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=10)
        chips = ctk.CTkFrame(st, fg_color="transparent")
        chips.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
        self.chips = {}
        for k in KINDS:
            lbl = ctk.CTkLabel(chips, text="", font=font(12, "bold"), corner_radius=10,
                               fg_color=CARD_2, text_color=KIND_COLOR[k], height=26)
            lbl.pack(side="left", padx=4)
            self.chips[k] = lbl
        self.stop_btn = ctk.CTkButton(chips, text="Stop", width=70, height=28, fg_color=CARD_2,
                                      hover_color="#FF4D4F", text_color=TEXT, state="disabled",
                                      command=self.stop)
        self.stop_btn.pack(side="right", padx=4)
        ctk.CTkButton(chips, text="Open folder", width=100, height=28, fg_color=CARD_2,
                      hover_color=BORDER, text_color=TEXT, command=self.open_folder).pack(
            side="right", padx=4)
        self._update_chips()

        # gallery
        gal = ctk.CTkFrame(right, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER)
        gal.grid(row=1, column=0, sticky="nsew", pady=12)
        gal.grid_columnconfigure(0, weight=1)
        gal.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(gal, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
        self.gal_title = ctk.CTkLabel(head, text="Downloaded", font=font(15, "bold"),
                                      text_color=TEXT)
        self.gal_title.pack(side="left")
        self.lib_search = ctk.CTkEntry(head, width=230, height=30, corner_radius=15,
                                       font=font(12), border_color=BORDER, fg_color=CARD_2,
                                       placeholder_text="🔍  Search your downloads")
        self.lib_search.pack(side="right")
        self.lib_search.bind("<Return>", lambda _: self.show_library(self.lib_search.get()))
        self.pick_bar = ctk.CTkFrame(head, fg_color="transparent")
        self.pick_go = ctk.CTkButton(self.pick_bar, text="Download picked", height=30, width=150,
                                     corner_radius=15, font=font(12, "bold"), fg_color=ACCENT,
                                     hover_color=ACCENT_HOVER, command=self.download_picked)
        self.pick_go.pack(side="right")
        self.pick_more = ctk.CTkButton(self.pick_bar, text="More like my picks", height=30,
                                       width=10, corner_radius=15, font=font(12), fg_color=CARD_2,
                                       hover_color=BORDER, text_color=TEXT,
                                       command=self.more_like_picks)
        self.pick_more.pack(side="right", padx=6)
        for text, state in (("None", False), ("All", True)):
            ctk.CTkButton(self.pick_bar, text=text, height=30, width=52, corner_radius=15,
                          font=font(12), fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                          command=lambda s=state: self._pick_all(s)).pack(side="right", padx=(6, 0))
        self.gallery = ctk.CTkScrollableFrame(gal, fg_color=CARD,
                                              scrollbar_button_color=BORDER)
        self.gallery.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
        self.empty = ctk.CTkLabel(
            self.gallery, text="Your downloads show up here as they arrive.\n"
                               "Type something on the left and press Enter.",
            font=font(13), text_color=MUTED)
        self.empty.grid(row=0, column=0, padx=20, pady=60)
        self.cols = 5

        # queue + log
        tabs = ctk.CTkTabview(right, fg_color=CARD, corner_radius=14, border_width=1,
                              border_color=BORDER, segmented_button_selected_color=ACCENT,
                              segmented_button_selected_hover_color=ACCENT_HOVER, height=200)
        tabs.grid(row=2, column=0, sticky="nsew")
        self.tabs = tabs
        tabs.add("Queue")
        tabs.add("Following")
        tabs.add("Activity")
        self._build_following(tabs.tab("Following"))
        self.queue_list = ctk.CTkScrollableFrame(tabs.tab("Queue"), fg_color=CARD)
        self.queue_list.pack(fill="both", expand=True)
        self.queue_empty = ctk.CTkLabel(
            self.queue_list, text="Nothing queued. Use “+ Queue” to line up several searches.",
            font=font(12), text_color=MUTED)
        self.queue_empty.pack(pady=20)
        self.log_box = ctk.CTkTextbox(tabs.tab("Activity"), font=ctk.CTkFont("Consolas", 12),
                                      fg_color=CARD_2, wrap="word")
        self.log_box.pack(fill="both", expand=True)
        for lvl, col in LOG_COLOR.items():
            if col:
                self.log_box.tag_config(lvl, foreground=col)
        self.log_box.configure(state="disabled")
        self.log("Ready. Type a keyword or paste a Pinterest link, then press Enter.", "success")
        self._refresh_match_ui()

    def _check_update(self):
        """Background: is there a newer release? (asks GitHub at most once a day)"""
        from . import update
        found = update.check(self.cfg, __version__)
        if found:
            version, url = found
            self.ui_q.put(lambda: (
                self.update_btn.configure(text=f"⬆  Version {version} is out",
                                          command=lambda: __import__("webbrowser").open(url)),
                self.update_btn.pack(side="right", padx=(0, 10))))

    # ── following ───────────────────────────────────────────────────────
    def _build_following(self, tab):
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(top, text="★  Follow this search", height=30, corner_radius=15,
                      font=font(12, "bold"), fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self.follow_current).pack(side="left")
        ctk.CTkButton(top, text="Check all now", height=30, width=110, corner_radius=15,
                      font=font(12), fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                      command=lambda: self.check_follows()).pack(side="left", padx=8)
        self.follow_auto = ctk.BooleanVar(value=bool(self.cfg.get("follow_autocheck", True)))
        ctk.CTkSwitch(top, text="Check when the app opens", variable=self.follow_auto,
                      progress_color=ACCENT, font=font(12), text_color=TEXT,
                      command=lambda: self.cfg.update(follow_autocheck=self.follow_auto.get())
                      ).pack(side="right")
        self.follow_list = ctk.CTkScrollableFrame(tab, fg_color=CARD)
        self.follow_list.pack(fill="both", expand=True)
        self._render_follows()

    def _render_follows(self):
        for w in self.follow_list.winfo_children():
            w.destroy()
        follows = self.lib.follows()
        if not follows:
            ctk.CTkLabel(
                self.follow_list, font=font(12), text_color=MUTED, justify="center",
                text="Follow a search or a board and the app fetches only what's new each time.\n"
                     "Type it on the left, set how many to get per check, then press "
                     "“Follow this search”.").pack(pady=16)
            return
        for f in follows:
            row = ctk.CTkFrame(self.follow_list, fg_color=CARD_2, corner_radius=10)
            row.pack(fill="x", pady=3, padx=2)
            name = scraper.link_name(f.query) if is_url(f.query) else f.query
            name = name if len(name) <= 44 else name[:42] + "…"
            ctk.CTkLabel(row, text=name, font=font(13, "bold"), text_color=TEXT,
                         anchor="w").pack(side="left", padx=12, pady=8)
            if f.checked:
                ago = max(0, time.time() - f.checked)
                when = ("just now" if ago < 90 else f"{ago / 60:.0f} min ago" if ago < 5400
                        else f"{ago / 3600:.0f} h ago" if ago < 172800 else f"{ago / 86400:.0f} days ago")
                note = f"checked {when} · {f.last_new} new · {f.total} in all"
            else:
                note = "not checked yet"
            ctk.CTkLabel(row, text=note, font=font(12), text_color=MUTED).pack(side="left")
            ctk.CTkButton(row, text="✕", width=28, height=24, fg_color="transparent",
                          hover_color=BORDER, text_color=MUTED,
                          command=lambda f=f: (self.lib.unfollow(f.id), self._render_follows())
                          ).pack(side="right", padx=6)
            ctk.CTkButton(row, text="Check", width=64, height=24, fg_color=CARD, hover_color=BORDER,
                          text_color=TEXT, font=font(12),
                          command=lambda f=f: self.check_follows([f.id])).pack(side="right")

    def follow_current(self):
        """Follow what's in the search box, with the current counts, folder and quality."""
        item = self._make_job()
        if not item:
            self.tabs.set("Following")
            return
        job: Job = item["job"]
        self.lib.follow(job.query, job.out_dir, job.counts, job.min_side, job.shape)
        self._remember(job.query)
        self.search.delete(0, "end")
        self._update_mode_hint()
        self._render_follows()
        self.log(f"Following “{job.query}”: only what's new is fetched from now on.", "success")
        self.check_follows([f.id for f in self.lib.follows()
                            if f.query == job.query and f.folder == job.out_dir])

    def check_follows(self, only: list | None = None, older_than: float = 0):
        """Queue a check for everything followed (or just the ids in *only*)."""
        queued = {i.get("follow") for i in self.queue_items if i["status"] in ("Waiting", "Running")}
        n = 0
        for f in self.lib.follows():
            if (only is not None and f.id not in only) or f.id in queued:
                continue
            if older_than and time.time() - f.checked < older_than:
                continue
            self.queue_items.append({"job": follow_job(f, self.lib, int(self.threads.get())),
                                     "query": f"★ {f.query}", "folder": f.folder,
                                     "status": "Waiting", "follow": f.id})
            n += 1
        if not n:
            if only is None and not older_than:
                self.status.configure(text="You're not following anything yet."
                                      if not self.lib.follows() else "Already checking.")
            return
        self._render_queue()
        self._update_go()
        self._begin()

    # ── small UI helpers ────────────────────────────────────────────────
    def log(self, text: str, level: str = "info"):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n", level if LOG_COLOR.get(level) else ())
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _set_theme(self, mode):
        ctk.set_appearance_mode(mode)
        self.theme_btn.set(mode)
        self.cfg["appearance"] = mode

    def _update_mode_hint(self):
        q = self.search.get().strip()
        if not q:
            self.mode_hint.configure(text="Keywords search all of Pinterest. Links work too: "
                                          "boards, sections, profiles, searches, pins.")
        elif is_url(q):
            kind = scraper.parse_link(q)[0] if "pin.it/" not in q else "pin"
            self.mode_hint.configure(
                text=f"🔗  {scraper.LINK_NAMES[kind]}" if kind in scraper.LINK_NAMES
                else "⚠  Not a board, profile, search or pin link")
        else:
            self.mode_hint.configure(text=f"🔍  Searching Pinterest for “{q}”")

    def _render_recent(self):
        for w in self.recent_row.winfo_children():
            w.destroy()
        recent = [r for r in self.cfg.get("recent", []) if r][:5]
        if not recent:
            self.recent_row.pack_forget()
            return
        self.recent_row.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(self.recent_row, text="Recent:", font=font(11), text_color=MUTED).pack(side="left")
        for r in recent:
            label = r if len(r) <= 18 else r[:16] + "…"
            ctk.CTkButton(self.recent_row, text=label, height=24, width=10, corner_radius=12,
                          font=font(11), fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                          command=lambda r=r: self._use_recent(r)).pack(side="left", padx=3)

    def _use_recent(self, text):
        self.search.delete(0, "end")
        self.search.insert(0, text)
        self._update_mode_hint()

    def _set_login(self, cookies: dict | None, quiet: bool = False):
        ok = scraper.signed_in(cookies)
        if cookies and not ok and not quiet:
            self.login_lbl.configure(
                text="Those cookies aren't from a signed-in Pinterest session. Sign in to "
                     "pinterest.com in your browser first, then export them again.",
                text_color="#E0A100")
            return
        scraper.sign_in(cookies if ok else None)
        if not quiet or not ok:
            settings.save_cookies(cookies if ok else None)
        if ok:
            self.login_lbl.configure(text="✓  Signed in. Private boards and Pinterest's own "
                                          "“more like this” are available.", text_color=TEXT)
            self.logout_btn.pack(side="left", padx=8)
        else:
            self.login_lbl.configure(
                text="Not signed in: everything public works. To reach your private boards, "
                     "export pinterest.com's cookies from your browser (a “cookies.txt” "
                     "extension does it) and choose the file here. It stays on this PC.",
                text_color=MUTED)
            self.logout_btn.pack_forget()

    def _login_file(self):
        p = filedialog.askopenfilename(
            title="Cookies exported from your browser",
            filetypes=[("Cookie exports", "*.txt *.json"), ("All files", "*.*")])
        if not p:
            return
        try:
            self._set_login(scraper.read_cookies(p))
        except OSError as exc:
            self.login_lbl.configure(text=f"Couldn't read that file: {exc}", text_color="#E0A100")

    def _browse(self):
        d = filedialog.askdirectory(title="Choose a download folder", initialdir=self.folder.get())
        if d:
            self.folder.set(d)

    def open_folder(self):
        path = (self.current or {}).get("folder") or self.folder.get()
        if not os.path.isdir(path):
            path = self.folder.get()
        os.makedirs(path, exist_ok=True)
        os.startfile(path)

    def _update_chips(self):
        for k in KINDS:
            self.chips[k].configure(text=f"  {KIND_ICON[k]}  {self.counters[k]} {LABEL[k]}  ")

    # ── reference image ─────────────────────────────────────────────────
    def _choose_reference(self):
        p = filedialog.askopenfilename(
            title="Choose a reference picture",
            filetypes=[("Pictures", "*.jpg *.jpeg *.png *.webp *.gif *.bmp"), ("All files", "*.*")])
        if p:
            self._load_reference(p)

    def _on_drop(self, event):
        files = self.tk.splitlist(event.data)
        if files:
            self._load_reference(files[0])
        return event.action

    def _paste(self, _event=None):
        try:
            clip = ImageGrab.grabclipboard()
        except Exception:
            clip = None
        if isinstance(clip, Image.Image):
            path = Path(settings._path()).parent / "pasted_reference.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            clip.convert("RGB").save(path)
            self._load_reference(str(path))
            return "break"
        if isinstance(clip, list) and clip and os.path.isfile(clip[0]):
            self._load_reference(clip[0])
            return "break"
        try:
            text = self.clipboard_get().strip()
        except Exception:
            return None
        if self.focus_get() in (self.search._entry, self.describe_entry._entry):
            return None  # normal text paste into a text box
        if text.lower().startswith("http") and not is_url(text):
            data = fetch_bytes(text, limit=25 * 1024 * 1024)
            if data:
                path = Path(settings._path()).parent / "pasted_reference.img"
                path.write_bytes(data)
                self._load_reference(str(path))
                return "break"
        return None

    def _load_reference(self, path: str, quiet: bool = False):
        self.cfg["reference"] = ""
        if path or not self.palette_edited:
            self.palette = None
            self.palette_edited = False
        if path:
            try:
                im = Image.open(path)
                im.seek(0)
                im = im.convert("RGB")
                im.thumbnail((240, 130))
                self.palette = extract_palette(path)
                self.cfg["reference"] = path
                self._ref_ctk = ctk.CTkImage(im, im, size=im.size)
                self.drop_img.configure(image=self._ref_ctk)
                self.drop_text.configure(text=os.path.basename(path)[:28] + "\n\nclick to change",
                                         font=font(12))
                self.drop_text.pack_forget()
                self.drop_img.pack(side="left", padx=10, pady=10)
                self.drop_text.pack(side="left", padx=4)
                self.clear_ref_btn.place(relx=1.0, x=-8, y=8, anchor="ne")
                self.drop.configure(border_color=ACCENT)
                if not (self.look.get() or self.colors.get()):
                    self.look.set(True)
                if not quiet:
                    self.log(f"Reference picture: {path}", "success")
            except Exception as exc:
                if not quiet:
                    self.log(f"Couldn't open that picture: {exc}", "error")
                path = ""
        if not self.cfg["reference"]:
            self.drop_img.pack_forget()
            self.drop_text.pack_forget()
            self.drop_text.configure(
                text="Drop a picture here\nor click to choose one\n\nCtrl+V pastes from clipboard",
                font=font(13))
            self.drop_text.pack(expand=True)
            self.clear_ref_btn.place_forget()
            self.drop.configure(border_color=BORDER)
        self._render_palette()
        self._refresh_match_ui()

    def _render_palette(self):
        for w in self.bar.winfo_children() + self.swatches.winfo_children():
            w.destroy()
        self.swatch_labels = []
        if not self.palette:
            ctk.CTkLabel(self.bar, text="no colors yet", font=font(11), text_color=MUTED).place(
                relx=0.5, rely=0.5, anchor="center")
            return
        x = 0.0
        for hx, share in zip(self.palette.hex(), self.palette.shares):
            ctk.CTkFrame(self.bar, fg_color=hx, corner_radius=0, height=26).place(
                relx=x, rely=0, relwidth=float(share), relheight=1)
            x += float(share)
        for i, hx in enumerate(self.palette.hex()):
            cell = ctk.CTkFrame(self.swatches, fg_color="transparent", cursor="hand2")
            cell.grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 12), pady=2)
            sw = ctk.CTkFrame(cell, width=14, height=14, corner_radius=4, fg_color=hx,
                              border_width=1, border_color=BORDER)
            sw.pack(side="left")
            lbl = ctk.CTkLabel(cell, text="", font=font(11), text_color=TEXT)
            lbl.pack(side="left", padx=(5, 0))
            x = ctk.CTkLabel(cell, text="✕", font=font(10), text_color=MUTED, width=12)
            x.pack(side="left", padx=(3, 0))
            for w in (cell, sw, lbl, x):
                w.bind("<Button-1>", lambda _e, i=i: self._remove_color(i))
            self.swatch_labels.append(lbl)

    def _pick_color(self):
        from tkinter import colorchooser
        start = self.palette.hex()[0] if self.palette else ACCENT
        _rgb, hx = colorchooser.askcolor(color=start, title="Pick a color to match", parent=self)
        if hx:
            self.add_color(hx)

    def add_color(self, hx: str):
        self.palette = self.palette.plus(hx) if self.palette else Palette.from_entries([(hx, 1.0)])
        self.palette_edited = True
        self.colors.set(True)
        self._render_palette()
        self._refresh_match_ui()

    def _remove_color(self, i: int):
        if not self.palette:
            return
        self.palette = self.palette.without(i) if len(self.palette.shares) > 1 else None
        self.palette_edited = True
        self._render_palette()
        self._refresh_match_ui()

    def _reset_palette(self):
        self.palette_edited = False
        ref = self.cfg.get("reference")
        self.palette = extract_palette(ref) if ref else None
        self._render_palette()
        self._refresh_match_ui()

    def _refresh_match_ui(self):
        has_ref = bool(self.cfg.get("reference"))
        look, colors = self.look.get(), self.colors.get()
        if self.palette_edited:
            self.colors_title.configure(text="Your colors (click one to remove it)")
        elif self.palette:
            self.colors_title.configure(text="Colors in your picture")
        else:
            self.colors_title.configure(text="Pick colors, or add a picture")
        if self.palette_edited and has_ref:
            self.reset_btn.pack(side="right", padx=4)
        else:
            self.reset_btn.pack_forget()
        self.look_box.pack_forget()
        self.color_box.pack_forget()
        described = self.smart.get() and bool(self.describe.get().strip())
        if self.smart_ok:
            from . import smart
            self.describe_entry.configure(state="normal" if self.smart.get() else "disabled")
            self.smart_lbl.configure(
                text="understands what a picture shows" if smart.installed()
                else f"{smart.TOTAL_MB} MB download on first use" if self.smart.get()
                else "off: compares shapes and edges only")
        if look or described:
            self.look_box.pack(fill="x", pady=(12, 0), before=self.match_hint)
            self.close_lbl.configure(text=describe_closeness(self.closeness.get()))
        if colors:
            self.color_box.pack(fill="x", pady=(12, 0), before=self.match_hint)
            t = self.tolerance.get()
            self.tol_val.configure(text=f"{t:.0f}%")
            self.tol_lbl.configure(text=describe_tolerance(t))
            if self.palette:
                for lbl, s, (lo, hi) in zip(self.swatch_labels, self.palette.shares,
                                            allowed_ranges(self.palette, t)):
                    lbl.configure(text=f"{s:.0%}  →  {lo:.0%}–{hi:.0%}")
        ms = self._match_settings()
        what = " and ".join(w for w, on in (("look like your picture", look and has_ref),
                                            ("use these colors", colors and bool(self.palette)),
                                            ("fit your description", described))
                            if on)
        if not (look or colors or described):
            hint = "Tick a box to download only pins that look like a picture or use its colors."
        elif not ms.active:
            hint = "Add a picture above, or pick colors, to start matching."
        else:
            hint = f"✓  Only pins that {what} will be downloaded."
        self.match_hint.configure(text=hint)

    def _quality(self) -> dict:
        return {"min_side": SIZES.get(self.size.get(), 0),
                "shape": SHAPE_NAMES.get(self.shape.get(), "any")}

    def _match_settings(self) -> MatchSettings:
        return MatchSettings(reference=self.cfg.get("reference") or None,
                             palette=self.palette.entries() if self.palette else None,
                             look=self.look.get(),
                             colors=self.colors.get(), color_tolerance=self.tolerance.get(),
                             closeness=self.closeness.get(), smart=self.smart.get(),
                             describe=self.describe.get().strip() if self.smart.get() else "")

    # ── queue ───────────────────────────────────────────────────────────
    def _make_job(self) -> dict | None:
        q = self.search.get().strip()
        if not q:
            self._flash(self.search)
            self.status.configure(text="Type a keyword or paste a link first.")
            return None
        counts = {k: r.value for k, r in self.rows.items()}
        if not any(counts.values()):
            self.status.configure(text="Every count is 0. Raise at least one slider.")
            return None
        folder = self.folder.get().strip() or settings.DEFAULTS["folder"]
        if self.subfolders.get():
            folder = os.path.join(folder, safe_name(q))
        return {"job": Job(query=q, out_dir=folder, counts=counts, match=self._match_settings(),
                           threads=int(self.threads.get()), preview=self.pick_first.get(),
                           library=self.lib, skip_owned=self.skip_owned.get(),
                           **self._quality()),
                "query": q, "folder": folder, "status": "Waiting"}

    def remote_search(self, query: str, counts: dict):
        """A search sent from the phone: same settings as the window, its own counts."""
        folder = self.folder.get().strip() or settings.DEFAULTS["folder"]
        if self.subfolders.get():
            folder = os.path.join(folder, safe_name(query))
        job = Job(query=query, out_dir=folder, counts=counts, match=MatchSettings(),
                  threads=int(self.threads.get()), library=self.lib,
                  skip_owned=self.skip_owned.get(), **self._quality())
        self.queue_items.append({"job": job, "query": f"📱 {query}", "folder": folder,
                                 "status": "Waiting"})
        self._remember(query)
        self._render_queue()
        self._update_go()
        self.log(f"From your phone: “{query}”", "success")
        self._begin()

    def _remote_sync(self, **kw):
        """Keep what the phone sees in step with the window."""
        self.remote.state = dict(self.remote.state, **kw,
                                 waiting=sum(i["status"] == "Waiting" for i in self.queue_items))

    def add_to_queue(self, auto: bool = False):
        item = self._make_job()
        if not item:
            return None
        self.queue_items.append(item)
        self._remember(item["query"])
        self.search.delete(0, "end")
        self._update_mode_hint()
        self._render_queue()
        if not auto:
            self.tabs.set("Queue")
            self.status.configure(text=f"Queued “{item['query']}”. Press Download when ready.")
        self._update_go()
        return item

    def _render_queue(self):
        for w in self.queue_list.winfo_children():
            w.destroy()
        if not self.queue_items:
            self.queue_empty = ctk.CTkLabel(
                self.queue_list, text="Nothing queued. Use “+ Queue” to line up several searches.",
                font=font(12), text_color=MUTED)
            self.queue_empty.pack(pady=20)
            return
        colours = {"Waiting": MUTED, "Running": ACCENT, "Done": "#1DB954", "Stopped": "#E0A100",
                   "No results": "#E0A100", "Your pick": "#3B82F6", "Nothing new": MUTED}
        for item in self.queue_items:
            job: Job = item["job"]
            row = ctk.CTkFrame(self.queue_list, fg_color=CARD_2, corner_radius=10)
            row.pack(fill="x", pady=3, padx=2)
            ctk.CTkLabel(row, text=item["query"][:40], font=font(13, "bold"), text_color=TEXT,
                         anchor="w").pack(side="left", padx=12, pady=8)
            parts = [f"{KIND_ICON[k]} {job.counts[k]}" for k in KINDS if job.counts[k]]
            if job.match.active:
                parts.append("🎯 match")
            if job.preview:
                parts.append("👆 pick first")
            if job.min_side or job.shape != "any":
                parts.append("📐 " + " ".join(
                    p for p in (job.shape if job.shape != "any" else "",
                                f"{job.min_side}px+" if job.min_side else "") if p))
            ctk.CTkLabel(row, text="   ".join(parts), font=font(12), text_color=MUTED).pack(side="left")
            if item["status"] != "Running" and not (
                    self.running and item is self.current):
                ctk.CTkButton(row, text="✕", width=28, height=24, fg_color="transparent",
                              hover_color=BORDER, text_color=MUTED,
                              command=lambda i=item: self._remove(i)).pack(side="right", padx=6)
            ctk.CTkLabel(row, text=item["status"], font=font(12, "bold"),
                         text_color=colours.get(item["status"], MUTED)).pack(side="right", padx=8)

    def _remove(self, item):
        if item is self.current and self.running:
            return
        self.queue_items.remove(item)
        self._render_queue()
        self._update_go()

    def _update_go(self):
        if self.running:
            self.go_btn.configure(text="Downloading…", state="disabled")
            return
        waiting = sum(1 for i in self.queue_items if i["status"] == "Waiting")
        idle = "Show me what's there" if self.pick_first.get() else "Download"
        self.go_btn.configure(state="normal",
                              text=f"Download queue ({waiting})" if waiting else idle)

    def _remember(self, q):
        recent = [q] + [r for r in self.cfg.get("recent", []) if r != q]
        self.cfg["recent"] = recent[:8]
        self._render_recent()

    def _flash(self, widget, n=4):
        if n <= 0:
            widget.configure(border_color=BORDER)
            return
        widget.configure(border_color=ACCENT if n % 2 else BORDER)
        self.after(140, lambda: self._flash(widget, n - 1))

    # ── running ─────────────────────────────────────────────────────────
    def start(self):
        if self.running:
            return
        if self.search.get().strip():
            self.add_to_queue(auto=True)
        self._begin()

    def _begin(self):
        """Run whatever is waiting in the queue."""
        if self.running:
            return
        if not any(i["status"] == "Waiting" for i in self.queue_items):
            if not self.queue_items:
                self._make_job()  # shows the hint
            else:
                self.status.configure(text="Everything in the queue is done. Add another search.")
            return
        self.running = True
        self._sync_picks()
        self.started = time.time()
        self.stop_btn.configure(state="normal")
        self.tabs.set("Activity")
        self._update_go()
        self._next()

    def _next(self):
        item = next((i for i in self.queue_items if i["status"] == "Waiting"), None)
        if not item or not self.running:
            self._finish()
            return
        self.current = item
        item["status"] = "Running"
        job: Job = item["job"]
        if job.preview:
            if not job.exclude:          # a new preview; "more like my picks" adds to the old one
                self._clear_gallery()
            self.pick_job = job
            self.gal_title.configure(text="Pick the ones you want")
        elif self.cands or self._lib_token is not None:   # replaces previews / a library view
            self._clear_gallery()
            self._lib_token = None
        self._render_queue()
        self.counters = {k: 0 for k in KINDS}
        self._update_chips()
        self.bar_progress.configure(mode="indeterminate")
        self.bar_progress.start()
        self.status.configure(text=f"Working on “{item['query']}”…")
        self._remote_sync(running=True, query=job.query, phase="Starting…", done=0, total=job.total)
        self.log("─" * 50)
        self.worker = Worker(item["job"], self.events)
        threading.Thread(target=self.worker.run, daemon=True).start()

    def stop(self):
        if self.worker:
            self.worker.stop()
            self.status.configure(text="Stopping…")
            self.stop_btn.configure(state="disabled")
        self.running = False  # waiting items stay queued for the next Download

    def _finish(self):
        self.running = False
        self._remote_sync(running=False, phase="")
        self.bar_progress.stop()
        self.bar_progress.configure(mode="determinate")
        self.stop_btn.configure(state="disabled")
        self._update_go()
        self._sync_picks()
        secs = time.time() - self.started
        self.elapsed.configure(text=f"{secs:.0f}s")
        self.bell()
        self._save_settings()
        self._index_library()

    def _on_event(self, ev: Event):
        if ev.type == "log":
            self.log(ev.text, ev.level)
        elif ev.type == "phase":
            self.status.configure(text=ev.text)
            self._remote_sync(phase=ev.text)
        elif ev.type == "progress":
            self._remote_sync(done=ev.done, total=ev.total)
            if ev.total:
                if self.bar_progress.cget("mode") == "indeterminate":
                    self.bar_progress.stop()
                    self.bar_progress.configure(mode="determinate")
                self.bar_progress.set(ev.done / ev.total)
        elif ev.type == "saved":
            self.counters[ev.kind] += 1
            self._update_chips()
            self._add_tile(ev)
        elif ev.type == "candidate":
            self._add_candidate(ev)
        elif ev.type == "done" and ev.preview:
            n = sum(ev.saved.values())
            if self.current:
                self.current["status"] = "Your pick" if n else "No results"
            self._render_queue()
            self.status.configure(
                text=f"{n} to choose from. Click the ones you want, then “Download picked”."
                if n else "Nothing to show. The Activity tab says why.")
            self.bar_progress.set(1 if n else 0)
            self._finish()               # the queue waits here until you've picked
        elif ev.type == "done":
            item = self.current
            stopped = ev.level == "warning"
            n = sum(ev.saved.values())
            if item:
                name = item["job"].query
                self._remote_sync(finished=self.remote.state["finished"] + 1,
                                  last=f"“{name}”: {n} saved" if n else f"“{name}”: nothing found")
            followed = bool(item and item.get("follow"))
            if item:
                item["status"] = ("Stopped" if stopped else "Done" if n
                                  else "Nothing new" if followed else "No results")
            if followed and not stopped:
                self.lib.follow_checked(item["follow"], n)
                self._render_follows()
            self._render_queue()
            if stopped:
                self.status.configure(text=f"Stopped. {n} files saved.")
                self._finish()
            elif self.running and any(i["status"] == "Waiting" for i in self.queue_items):
                self._next()
            else:
                self.status.configure(text=f"Done! {n} files saved. Click “Open folder” to see them."
                                      if n else "Nothing new in what you follow." if followed
                                      else "Finished, but nothing was saved. The Activity tab says why.")
                self.bar_progress.set(1 if n else 0)
                self._finish()

    def _pump(self):
        try:
            for _ in range(200):
                self._on_event(self.events.get_nowait())
        except queue.Empty:
            pass
        try:
            while True:
                fn = self.ui_q.get_nowait()
                fn()
        except queue.Empty:
            pass
        if self.running:
            self.elapsed.configure(text=f"{time.time() - self.started:.0f}s")
        self.after(60, self._pump)

    # ── gallery ─────────────────────────────────────────────────────────
    @staticmethod
    def _tile_image(path: str, kind: str) -> Image.Image:
        """Square thumbnail of a downloaded file (a play symbol for videos)."""
        from PIL import ImageOps
        im = None
        try:
            if kind != "video":
                im = Image.open(path)
                im.draft("RGB", (TILE * 2, TILE * 2))
                im = im.convert("RGB")
        except Exception:
            im = None
        if im is None:
            im = Image.new("RGB", (TILE, TILE), (40, 32, 64))
            d = ImageDraw.Draw(im)
            c = TILE // 2
            d.polygon([(c - 14, c - 18), (c - 14, c + 18), (c + 18, c)], fill=(255, 255, 255))
        return ImageOps.fit(im, (TILE, TILE), Image.Resampling.LANCZOS)

    def _add_tile(self, ev: Event):
        def load():
            im = self._tile_image(ev.path, ev.kind)
            self.ui_q.put(lambda: self._place_tile(ev, im))
        self.thumbs.submit(load)

    # ── library ─────────────────────────────────────────────────────────
    def _smart_on(self) -> bool:
        """Is smart matching switched on? (main thread only: reads a Tk variable)"""
        return bool(self.smart_ok and self.smart.get())

    @staticmethod
    def _smart_clip(on: bool):
        """The smart model if it is switched on and already downloaded (else None)."""
        from . import smart
        return smart.get() if on and smart.installed() else None

    def show_library(self, text: str = ""):
        """Fill the gallery with downloads matching *text* (all recent ones if empty)."""
        if self.running:
            self.status.configure(text="Search your downloads once the current run is finished.")
            return
        text = text.strip()
        self._clear_gallery()
        self.pick_job = None
        self.gal_title.configure(text=f"Your downloads: “{text}”" if text else "Your downloads")
        token = self._lib_token = object()
        smart_on = self._smart_on()

        def say(msg):
            self.ui_q.put(lambda: token is self._lib_token and self.status.configure(text=msg))

        def show(items):
            for it in items:      # in order, best first
                im = self._tile_image(it.path, it.kind)
                ev = Event("saved", kind=it.kind, path=it.path, pin=it.pin, score=it.score,
                           origin=it.query)
                self.ui_q.put(lambda ev=ev, im=im: token is self._lib_token
                              and self._place_tile(ev, im, append=True))

        def work():
            # matches by word come straight away; matches by meaning follow once
            # the smart model is loaded (a few seconds the first time)
            items = self.lib.search(text, 60)
            show(items)
            if text and smart_on:
                if items:
                    say(f"{len(items)} of your downloads mention “{text}”. Looking for more…")
                else:
                    say(f"Looking through your downloads for “{text}”…")
                shown = {it.path for it in items}
                more = [it for it in self.lib.search(text, 60, clip=self._smart_clip(True))
                        if it.path not in shown]
                show(more)
                items = items + more
            if not items:
                say("Nothing in your downloads matches that." if text
                    else "No downloads recorded yet.")
            else:
                say(f"{len(items)} of your downloads" + (f" match “{text}”." if text else "."))
        threading.Thread(target=work, daemon=True).start()

    def _index_library(self):
        """Let the smart model look at downloads it hasn't seen, so they can be
        found by meaning. Runs quietly after each run."""
        if self.indexing or not self._smart_on():
            return

        def work():
            try:
                clip = self._smart_clip(True)
                if clip is None:
                    return
                from .matching import load
                for path, _kind in self.lib.missing_embeddings(300):
                    if self.running or self.closing:
                        return     # don't compete with a download for the CPU
                    try:
                        self.lib.set_embedding(path, clip.image(load(path)))
                    except Exception:
                        self.lib.forget(path) if not os.path.exists(path) else None
            finally:
                self.indexing = False
        self.indexing = True
        threading.Thread(target=work, daemon=True).start()

    def _place_tile(self, ev: Event, im: Image.Image, append: bool = False):
        if self.empty.winfo_exists():
            self.empty.destroy()
        img = ctk.CTkImage(im, im, size=(TILE, TILE))
        tile = ctk.CTkFrame(self.gallery, fg_color=CARD_2, corner_radius=10)
        pic = ctk.CTkLabel(tile, image=img, text="", cursor="hand2")
        pic.pack(padx=4, pady=(4, 0))
        pic.bind("<Button-1>", lambda _: os.startfile(ev.path))
        cap = f"{KIND_ICON[ev.kind]}"
        if ev.score is not None:
            cap += f"  {ev.score:.0f}% match"
        ctk.CTkLabel(tile, text=cap, font=font(11), text_color=MUTED, height=20).pack()
        if ev.pin is not None:
            ctk.CTkButton(tile, text="More like this", height=22, width=TILE, corner_radius=8,
                          font=font(11), fg_color="transparent", hover_color=BORDER,
                          text_color=TEXT, command=lambda: self.more_like(ev)).pack(
                padx=4, pady=(0, 4))
        if append:
            self.tiles.append(tile)
            self.tile_images.append(img)
            i = len(self.tiles) - 1
            tile.grid(row=i // self.cols, column=i % self.cols, padx=5, pady=5)
            return
        self.tiles.insert(0, tile)
        self.tile_images.insert(0, img)
        if len(self.tiles) > 150:
            self.tiles.pop().destroy()
            self.tile_images.pop()
        self._regrid()

    # ── picking before downloading ──────────────────────────────────────
    def _clear_gallery(self):
        for t in self.tiles:
            t.destroy()
        self.tiles.clear()
        self.tile_images.clear()
        self.cands.clear()
        if self.empty.winfo_exists():
            self.empty.destroy()
        self.gal_title.configure(text="Downloaded")
        self._sync_picks()

    def _add_candidate(self, ev: Event):
        def load():
            import io

            from PIL import ImageOps
            try:
                im = Image.open(io.BytesIO(ev.data))
                im.seek(0)
                im = ImageOps.fit(im.convert("RGB"), (TILE, TILE), Image.Resampling.LANCZOS)
            except Exception:
                im = Image.new("RGB", (TILE, TILE), (40, 32, 64))
            self.ui_q.put(lambda: self._place_candidate(ev, im))
        self.thumbs.submit(load)

    def _place_candidate(self, ev: Event, im: Image.Image):
        if self.pick_job is None:
            return
        if self.empty.winfo_exists():
            self.empty.destroy()
        img = ctk.CTkImage(im, im, size=(TILE, TILE))
        tile = ctk.CTkFrame(self.gallery, fg_color=CARD_2, corner_radius=10, border_width=2,
                            border_color=CARD_2)
        pic = ctk.CTkLabel(tile, image=img, text="", cursor="hand2")
        pic.pack(padx=4, pady=(4, 0))
        cap = ctk.CTkLabel(tile, text="", font=font(11), text_color=MUTED, height=20,
                           cursor="hand2")
        cap.pack(pady=(0, 3))
        cand = {"ev": ev, "tile": tile, "cap": cap, "picked": False}
        for w in (tile, pic, cap):
            w.bind("<Button-1>", lambda _e, c=cand: self._toggle_pick(c))
        self.cands.append(cand)
        self.tiles.append(tile)          # added at the end: tiles must not jump while you click
        self.tile_images.append(img)
        i = len(self.tiles) - 1
        tile.grid(row=i // self.cols, column=i % self.cols, padx=5, pady=5)
        self._paint_pick(cand)
        self._sync_picks()

    def _paint_pick(self, cand: dict):
        ev = cand["ev"]
        if cand["picked"]:
            cand["tile"].configure(border_color=ACCENT)
            cand["cap"].configure(text="✓ picked", text_color=ACCENT)
        else:
            text = KIND_ICON[ev.kind] + (f"  {ev.score:.0f}% match" if ev.score is not None else "")
            cand["tile"].configure(border_color=CARD_2)
            cand["cap"].configure(text=text, text_color=MUTED)

    def _toggle_pick(self, cand: dict):
        cand["picked"] = not cand["picked"]
        self._paint_pick(cand)
        self._sync_picks()

    def _pick_all(self, state: bool):
        for c in self.cands:
            if c["picked"] != state:
                c["picked"] = state
                self._paint_pick(c)
        self._sync_picks()

    def _sync_picks(self):
        if not self.cands:
            self.pick_bar.pack_forget()
            self.lib_search.pack(side="right")
            return
        n = sum(c["picked"] for c in self.cands)
        self.lib_search.pack_forget()
        self.pick_bar.pack(side="right")
        self.pick_go.configure(text=f"Download picked ({n})",
                               state="normal" if n and not self.running else "disabled")
        can_learn = bool(n) and self.smart_ok and self.smart.get() and not self.running
        self.pick_more.configure(state="normal" if can_learn else "disabled")

    def _queue_next(self, item: dict):
        """Put *item* ahead of everything still waiting, and run the queue."""
        at = next((i for i, it in enumerate(self.queue_items) if it["status"] == "Waiting"),
                  len(self.queue_items))
        self.queue_items.insert(at, item)
        self._render_queue()
        self._begin()

    def download_picked(self):
        picked = [c["ev"] for c in self.cands if c["picked"]]
        base = self.pick_job
        if not picked or base is None or self.running:
            return
        base.scores = {e.pin.id: e.score for e in picked if e.score is not None}
        job = picks_job([e.pin for e in picked], base)
        self._queue_next({"job": job, "query": base.query, "folder": base.out_dir,
                          "status": "Waiting"})

    def more_like_picks(self):
        """Another round of previews, steered by what was picked and passed over."""
        base = self.pick_job
        picked = [c for c in self.cands if c["picked"]]
        if not picked or base is None or self.running:
            return
        passed = [c for c in self.cands if not c["picked"]]
        match = self._match_settings()
        match.examples = [c["ev"].data for c in picked][:16]
        match.rejects = [c["ev"].data for c in passed][:32]
        shown = {c["ev"].pin.id for c in self.cands} | set(base.exclude)
        for c in passed:                 # keep the picks on screen, drop the rest
            i = self.tiles.index(c["tile"])
            self.tiles.pop(i).destroy()
            self.tile_images.pop(i)
        self.cands = picked
        self._regrid()
        job = Job(query=base.query, out_dir=base.out_dir, counts=dict(base.counts), match=match,
                  threads=base.threads, preview=True, exclude=shown, origin=base.origin,
                  seed=base.seed, library=base.library, skip_owned=base.skip_owned,
                  min_side=base.min_side, shape=base.shape)
        self._queue_next({"job": job, "query": f"More like my picks: {base.query}",
                          "folder": base.out_dir, "status": "Waiting"})

    def more_like(self, ev: Event):
        """Queue a search for pins that look like one already downloaded."""
        counts = {k: r.value for k, r in self.rows.items()}
        if not any(counts.values()):
            counts["image"] = 30
        base = Job(query=ev.origin, out_dir=os.path.dirname(ev.path), counts=counts,
                   match=self._match_settings(), threads=int(self.threads.get()),
                   library=self.lib, skip_owned=self.skip_owned.get(), **self._quality())
        job = similar_job(ev.pin, ev.path, base, ev.origin)
        self.queue_items.append({"job": job, "query": f"Like: {job.query}",
                                 "folder": job.out_dir, "status": "Waiting"})
        self._render_queue()
        if self.running:
            self.status.configure(text="Queued: more like that one. It runs after the current search.")
        self._update_go()
        self._begin()

    def _regrid(self):
        width = self.gallery.winfo_width()
        if width > 1:  # 1 = not laid out yet
            self.cols = max(2, (width - 30) // (TILE + 18))
        for i, t in enumerate(self.tiles):
            t.grid(row=i // self.cols, column=i % self.cols, padx=5, pady=5)

    def _on_resize(self, event):
        if event.widget is not self:
            return
        cols = max(2, (self.gallery.winfo_width() - 30) // (TILE + 18))
        if cols != self.cols:
            self.cols = cols
            self._regrid()

    # ── phone sharing ───────────────────────────────────────────────────
    def _phone_folder(self) -> str:
        return self.cfg.get("phone_folder") or self.folder.get()

    def _phone_start(self):
        from .phone import PhoneServer
        if self.phone and self.phone.running:
            return True
        folder = self._phone_folder()
        os.makedirs(folder, exist_ok=True)
        try:
            self.phone = PhoneServer(folder, self.cfg["phone_token"], control=self.remote)
            self.phone.start()
        except OSError as exc:
            self.log(f"Couldn't start phone sharing: {exc}", "error")
            self.phone = None
            return False
        self.phone_btn.configure(text="📱  Phone  ●", text_color="#1DB954")
        self.log(f"Phone sharing on: {self.phone.url.split('?')[0]} (scan the QR code under Phone)",
                 "success")
        return True

    def _phone_stop(self):
        if self.phone:
            self.phone.stop()
            self.phone = None
        self.phone_btn.configure(text="📱  Phone", text_color=TEXT)

    def open_phone(self):
        if self.phone_win and self.phone_win.winfo_exists():
            self.phone_win.focus()
            return
        from .phone import qr_image
        win = ctk.CTkToplevel(self)
        self.phone_win = win
        win.title("Use your downloads on your phone")
        win.geometry("520x700")
        win.resizable(False, False)
        win.configure(fg_color=BG)
        win.transient(self)
        win.after(100, win.lift)

        ctk.CTkLabel(win, text="Browse & share from your phone", font=font(19, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=24, pady=(22, 2))
        ctk.CTkLabel(win, text="Keep this PC on. Your phone streams the pictures over Wi-Fi\n"
                               "and nothing gets saved on it unless you choose to.",
                     font=font(12), text_color=MUTED, justify="left").pack(anchor="w", padx=24)

        card = ctk.CTkFrame(win, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=20, pady=14)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(row, text="Folder", font=font(12), text_color=MUTED).pack(side="left")
        folder_var = ctk.StringVar(value=self._phone_folder())
        ctk.CTkEntry(row, textvariable=folder_var, height=32, border_color=BORDER, fg_color=CARD_2,
                     font=font(12), state="readonly").pack(side="left", fill="x", expand=True, padx=8)

        def browse():
            d = filedialog.askdirectory(parent=win, title="Folder to share with your phone",
                                        initialdir=folder_var.get())
            if d:
                folder_var.set(d)
                self.cfg["phone_folder"] = d
                if self.phone:
                    self._phone_stop()
                    self._phone_start()
                    refresh()
        ctk.CTkButton(row, text="Change", width=70, height=32, fg_color=CARD_2, hover_color=BORDER,
                      text_color=TEXT, command=browse).pack(side="left")

        on = ctk.BooleanVar(value=bool(self.phone and self.phone.running))
        auto = ctk.BooleanVar(value=bool(self.cfg.get("phone_autostart")))
        sw = ctk.CTkSwitch(card, text="Share with my phone", variable=on, font=font(14, "bold"),
                           progress_color=ACCENT, text_color=TEXT)
        sw.pack(anchor="w", padx=16, pady=(6, 4))
        ctk.CTkCheckBox(card, text="Turn on automatically when the app opens", variable=auto,
                        font=font(12), text_color=TEXT, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                        border_color=MUTED,
                        command=lambda: self.cfg.update(phone_autostart=auto.get())).pack(
            anchor="w", padx=16, pady=(4, 14))

        qr_box = ctk.CTkFrame(win, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER)
        qr_box.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        qr_lbl = ctk.CTkLabel(qr_box, text="")
        qr_lbl.pack(pady=(18, 6))
        url_lbl = ctk.CTkLabel(qr_box, text="", font=font(12), text_color=MUTED)
        url_lbl.pack()
        btns = ctk.CTkFrame(qr_box, fg_color="transparent")
        btns.pack(pady=6)
        steps = ctk.CTkLabel(qr_box, text="", font=font(12), text_color=TEXT, justify="left")
        steps.pack(padx=20, pady=(4, 16))

        def copy_link():
            if self.phone:
                self.clipboard_clear()
                self.clipboard_append(self.phone.url)
                url_lbl.configure(text="Link copied ✓")
        ctk.CTkButton(btns, text="Copy link", width=90, height=28, fg_color=CARD_2,
                      hover_color=BORDER, text_color=TEXT, command=copy_link).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Open here", width=90, height=28, fg_color=CARD_2,
                      hover_color=BORDER, text_color=TEXT,
                      command=lambda: self.phone and __import__("webbrowser").open(self.phone.url)
                      ).pack(side="left", padx=4)

        def refresh():
            if self.phone and self.phone.running:
                q = qr_image(self.phone.url, box=7)
                img = ctk.CTkImage(q, q, size=(230, 230))
                qr_lbl.configure(image=img, text="")
                qr_lbl._img = img
                url_lbl.configure(text=self.phone.url.split("?")[0])
                btns.pack(pady=6, before=steps)
                steps.configure(text="1.  Connect your phone to the same Wi-Fi as this PC\n"
                                     "2.  Point the phone's camera at the code and open the link\n"
                                     "3.  Tap a picture, then Share → Instagram, WhatsApp, …\n\n"
                                     "If Windows asks about the firewall, allow Private networks.")
            else:
                qr_lbl.configure(image=None, text="📱", font=font(64))
                url_lbl.configure(text="Turn on sharing to get a QR code for your phone.")
                btns.pack_forget()
                steps.configure(text="")

        def toggled():
            if on.get():
                if not self._phone_start():
                    on.set(False)
            else:
                self._phone_stop()
            refresh()
        sw.configure(command=toggled)
        if not on.get():  # opening the panel means they want it: switch on straight away
            on.set(True)
            toggled()
        else:
            refresh()

    # ── persistence ─────────────────────────────────────────────────────
    def _save_settings(self):
        self.cfg.update({
            "pick_first": self.pick_first.get(),
            "skip_owned": self.skip_owned.get(),
            **self._quality(),
            "folder": self.folder.get(), "subfolders": self.subfolders.get(),
            "threads": int(self.threads.get()), "look": self.look.get(),
            "colors": self.colors.get(), "color_tolerance": round(self.tolerance.get()),
            "closeness": round(self.closeness.get()),
            "smart": self.smart.get() if self.smart_ok else self.cfg.get("smart", True),
            "describe": self.describe.get().strip(),
            "palette": self.palette.entries() if self.palette else [],
            "palette_edited": self.palette_edited,
            **{k: r.value for k, r in self.rows.items()},
        })
        settings.save(self.cfg)

    def _close(self):
        self.closing = True
        if self.worker:
            self.worker.stop()
        self._phone_stop()
        self._save_settings()
        self.thumbs.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def main():
    try:  # own taskbar identity, so Windows shows our icon instead of Python's
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "IamOumarIbrahim.PinterestMassDownloader")
    except (AttributeError, OSError):
        pass
    app = App()
    app.mainloop()
