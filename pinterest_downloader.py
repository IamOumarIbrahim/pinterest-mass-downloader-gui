"""
Pinterest Mass Downloader
A fast, threaded desktop app for bulk downloading Pinterest images, videos, and GIFs.
Uses pinterest-dl as the core scraping library.

Media filtering: uses two-step scrape → classify → download to ensure correct types.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import sys
import queue
import time
import re
from pathlib import Path
from datetime import datetime


# ─────────────────────────────────────────────
#  Theme & Palette
# ─────────────────────────────────────────────
BG_DARK     = "#0D0D0D"
BG_CARD     = "#141414"
BG_PANEL    = "#1A1A1F"
BG_INPUT    = "#1E1E26"
ACCENT      = "#E60023"
ACCENT_GLOW = "#FF1744"
ACCENT_DARK = "#99001A"
TEXT_PRI    = "#F5F5F5"
TEXT_SEC    = "#9E9E9E"
TEXT_DIM    = "#555566"
BORDER      = "#2A2A38"
SUCCESS     = "#00E676"
WARNING     = "#FFD740"
ERROR_COL   = "#FF5252"
PURPLE      = "#7C4DFF"
BLUE        = "#4FC3F7"
TEAL        = "#26C6DA"
ORANGE      = "#FFA726"

FONT_TITLE  = ("Segoe UI", 20, "bold")
FONT_HEAD   = ("Segoe UI", 12, "bold")
FONT_SUB    = ("Segoe UI", 10, "bold")
FONT_BODY   = ("Segoe UI", 10)
FONT_MONO   = ("Consolas", 9)
FONT_SMALL  = ("Segoe UI", 8)
FONT_NUM    = ("Segoe UI", 18, "bold")


# ─────────────────────────────────────────────
#  Utility helpers
# ─────────────────────────────────────────────
def is_board_url(text: str) -> bool:
    return bool(re.match(r"https?://(www\.)?pinterest\.", text.strip()))


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def classify_pin(pin) -> str:
    """
    Returns 'video', 'gif', or 'image' based on PinterestMedia attributes.
    - If pin.video_stream is set → video
    - If pin.src ends with .gif  → gif
    - Otherwise                  → image
    """
    if getattr(pin, "video_stream", None) is not None:
        return "video"
    src = getattr(pin, "src", "") or ""
    if src.lower().endswith(".gif"):
        return "gif"
    return "image"


# ─────────────────────────────────────────────
#  Download Worker
# ─────────────────────────────────────────────
class DownloadWorker:
    def __init__(self, log_q: queue.Queue, progress_q: queue.Queue):
        self.log_q       = log_q
        self.progress_q  = progress_q
        self._stop       = threading.Event()

    def stop(self):
        self._stop.set()

    def _log(self, msg: str, level: str = "info"):
        self.log_q.put((level, f"[{ts()}] {msg}"))

    def _progress(self, done: int, total: int):
        self.progress_q.put((done, total))

    # ── helper: download a filtered list of pins ──────────────────────────
    def _download_pins(self, client, pins, output_dir: str,
                       download_streams: bool, label: str) -> int:
        """
        Use the client's internal _download_and_save() on an already-filtered list.
        Returns number of items downloaded.
        """
        if not pins:
            return 0
        self._log(f"  Downloading {len(pins)} {label}…")
        try:
            result = client._download_and_save(
                scraped_outputs=pins,
                output_dir=output_dir,
                download_streams=download_streams,
                skip_remux=True,
                cache_path=None,
                caption="none",
            )
            count = len(result) if result else 0
            self._log(f"  ✓ {count} {label} saved.", "success")
            return count
        except Exception as e:
            self._log(f"  Error downloading {label}: {e}", "error")
            return 0

    def run(self,
            query_or_url: str,
            output_dir: str,
            img_count: int,
            vid_count: int,
            gif_count: int,
            threads: int = 8):
        """Main download routine — runs in a background thread."""
        try:
            from pinterest_dl import PinterestDL
        except ImportError:
            self._log("ERROR: pinterest-dl is not installed.", "error")
            self._log("  Run:  pip install pinterest-dl", "warning")
            self._progress(0, 0)
            return

        total_requested = img_count + vid_count + gif_count
        if total_requested == 0:
            self._log("Nothing to do — all sliders are at 0.", "warning")
            self._progress(0, 0)
            return

        mode = "board" if is_board_url(query_or_url) else "keyword"
        self._log(f"Mode: {mode}  |  Query: {query_or_url}")
        self._log(f"Requesting → Images: {img_count}  Videos: {vid_count}  GIFs: {gif_count}")
        self._log(f"Output: {output_dir}")

        os.makedirs(output_dir, exist_ok=True)

        client = PinterestDL.with_api(timeout=5, verbose=False)

        # ── Step 1: scrape metadata (request enough to satisfy all types) ──
        # We over-request because Pinterest returns a mix; we need enough
        # of each type.  Request 4× total as a buffer.
        fetch_n = min(total_requested * 4, 600)
        self._log(f"Fetching up to {fetch_n} pin metadata records…")

        try:
            if mode == "board":
                pins = client.scrape(url=query_or_url, num=fetch_n)
            else:
                pins = client.search(query=query_or_url,
                                     num=fetch_n,
                                     min_resolution=(0, 0))
        except Exception as exc:
            self._log(f"Scrape error: {exc}", "error")
            self._progress(0, 0)
            return

        if not pins:
            self._log("No pins found. Check your query or try again.", "warning")
            self._progress(0, 0)
            return

        self._log(f"Got {len(pins)} pins. Classifying…")

        # ── Step 2: classify ───────────────────────────────────────────────
        images_pool = []
        videos_pool = []
        gifs_pool   = []

        for pin in pins:
            t = classify_pin(pin)
            if t == "video":
                videos_pool.append(pin)
            elif t == "gif":
                gifs_pool.append(pin)
            else:
                images_pool.append(pin)

        self._log(
            f"Classified → Images: {len(images_pool)}  "
            f"Videos: {len(videos_pool)}  GIFs: {len(gifs_pool)}"
        )

        # ── Step 3: slice to requested counts ─────────────────────────────
        to_dl_images = images_pool[:img_count]
        to_dl_videos = videos_pool[:vid_count]
        to_dl_gifs   = gifs_pool[:gif_count]

        actual_imgs = len(to_dl_images)
        actual_vids = len(to_dl_videos)
        actual_gifs = len(to_dl_gifs)

        if actual_imgs < img_count:
            self._log(
                f"  Only {actual_imgs} images found (wanted {img_count}).", "warning")
        if actual_vids < vid_count:
            self._log(
                f"  Only {actual_vids} videos found (wanted {vid_count}). "
                f"Videos may be limited on this query.", "warning")
        if actual_gifs < gif_count:
            self._log(
                f"  Only {actual_gifs} GIFs found (wanted {gif_count}).", "warning")

        total_dl = actual_imgs + actual_vids + actual_gifs
        self._log(f"Downloading {total_dl} items total…")
        self._progress(0, total_dl)

        if self._stop.is_set():
            self._log("Stopped before download.", "warning")
            return

        # ── Step 4: download each type ────────────────────────────────────
        done = 0

        if to_dl_images:
            n = self._download_pins(client, to_dl_images,
                                    output_dir, False, "images")
            done += n
            self._progress(done, total_dl)

        if self._stop.is_set():
            self._log("Stopped by user.", "warning")
            return

        if to_dl_videos:
            n = self._download_pins(client, to_dl_videos,
                                    output_dir, True, "videos")
            done += n
            self._progress(done, total_dl)

        if self._stop.is_set():
            self._log("Stopped by user.", "warning")
            return

        if to_dl_gifs:
            n = self._download_pins(client, to_dl_gifs,
                                    output_dir, False, "GIFs")
            done += n
            self._progress(done, total_dl)

        self._log(
            f"All done! {done} / {total_dl} items saved to:\n  {output_dir}",
            "success"
        )
        self._progress(done, total_dl)


# ─────────────────────────────────────────────
#  Styled Widgets
# ─────────────────────────────────────────────
class StyledEntry(tk.Entry):
    def __init__(self, parent, placeholder="", **kw):
        super().__init__(parent,
                         bg=BG_INPUT, fg=TEXT_PRI,
                         insertbackground=ACCENT,
                         relief="flat", bd=0, font=FONT_BODY,
                         highlightthickness=1,
                         highlightbackground=BORDER,
                         highlightcolor=ACCENT, **kw)
        self._placeholder = placeholder
        self._has_focus   = False
        if placeholder:
            self._show_placeholder()
            self.bind("<FocusIn>",  self._on_focus_in)
            self.bind("<FocusOut>", self._on_focus_out)

    def _show_placeholder(self):
        self.insert(0, self._placeholder)
        self.config(fg=TEXT_DIM)

    def _on_focus_in(self, _=None):
        if not self._has_focus and self.get() == self._placeholder:
            self.delete(0, "end")
            self.config(fg=TEXT_PRI)
        self._has_focus = True

    def _on_focus_out(self, _=None):
        self._has_focus = False
        if not self.get():
            self._show_placeholder()

    def real_value(self) -> str:
        val = self.get()
        return "" if val == self._placeholder else val


class StyledButton(tk.Button):
    def __init__(self, parent, text, command=None, style="accent", **kw):
        palettes = {
            "accent":  (ACCENT,      TEXT_PRI, ACCENT_GLOW),
            "ghost":   (BG_PANEL,    TEXT_SEC, BORDER),
            "success": (SUCCESS,     BG_DARK,  "#69F0AE"),
            "danger":  (ERROR_COL,   TEXT_PRI, "#FF8A80"),
            "neutral": (BG_INPUT,    TEXT_SEC, BORDER),
        }
        bg, fg, hover = palettes.get(style, palettes["accent"])
        self._bg_normal = bg
        self._bg_hover  = hover
        super().__init__(parent,
                         text=text, command=command,
                         bg=bg, fg=fg,
                         activebackground=hover, activeforeground=fg,
                         relief="flat", bd=0, font=FONT_SUB,
                         cursor="hand2", padx=14, pady=7, **kw)
        self.bind("<Enter>", lambda _: self.config(bg=self._bg_hover))
        self.bind("<Leave>", lambda _: self.config(bg=self._bg_normal))


class LogConsole(tk.Text):
    def __init__(self, parent, **kw):
        super().__init__(parent,
                         bg="#0A0A0E", fg=TEXT_SEC,
                         font=FONT_MONO, relief="flat", bd=0,
                         state="disabled", wrap="word",
                         highlightthickness=0, **kw)
        self.tag_config("info",    foreground=TEXT_SEC)
        self.tag_config("success", foreground=SUCCESS)
        self.tag_config("warning", foreground=WARNING)
        self.tag_config("error",   foreground=ERROR_COL)

    def append(self, text: str, level: str = "info"):
        self.config(state="normal")
        self.insert("end", text + "\n", level)
        self.see("end")
        self.config(state="disabled")

    def clear(self):
        self.config(state="normal")
        self.delete("1.0", "end")
        self.config(state="disabled")


# ─────────────────────────────────────────────
#  Count Slider Card  (reusable component)
# ─────────────────────────────────────────────
class CountSliderCard(tk.Frame):
    """
    A self-contained card with an icon label, slider, and numeric display.
    colour   — accent colour for the number and slider thumb
    icon     — emoji / text shown on the left
    label    — card title
    max_val  — slider max
    default  — initial value
    """
    def __init__(self, parent, icon: str, label: str,
                 colour: str, max_val: int = 200, default: int = 50,
                 **kw):
        super().__init__(parent, bg=BG_CARD, relief="flat", **kw)
        self._colour = colour

        # Top row: icon + label + big number
        top = tk.Frame(self, bg=BG_CARD)
        top.pack(fill="x", padx=14, pady=(10, 0))

        # Left: icon badge
        badge = tk.Frame(top, bg=colour, padx=6, pady=2)
        badge.pack(side="left")
        tk.Label(badge, text=icon, font=("Segoe UI", 14),
                 bg=colour, fg=BG_DARK).pack()

        tk.Label(top, text=f"  {label}", font=FONT_SUB,
                 bg=BG_CARD, fg=TEXT_PRI).pack(side="left")

        self._var = tk.IntVar(value=default)
        self._num_label = tk.Label(top, text=str(default),
                                   font=FONT_NUM, bg=BG_CARD, fg=colour)
        self._num_label.pack(side="right", padx=4)

        # Slider
        self._slider = tk.Scale(self, variable=self._var,
                                from_=0, to=max_val,
                                orient="horizontal",
                                bg=BG_CARD, fg=TEXT_PRI,
                                troughcolor=BG_INPUT,
                                activebackground=colour,
                                highlightthickness=0,
                                sliderlength=22,
                                font=FONT_SMALL,
                                showvalue=False,
                                command=self._on_change)
        self._slider.pack(fill="x", padx=14, pady=(2, 2))

        # Tick row
        ticks = tk.Frame(self, bg=BG_CARD)
        ticks.pack(fill="x", padx=14)
        for mark in ["0", str(max_val // 4), str(max_val // 2),
                     str(max_val * 3 // 4), str(max_val)]:
            tk.Label(ticks, text=mark, font=FONT_SMALL,
                     bg=BG_CARD, fg=TEXT_DIM).pack(side="left", expand=True)

        tk.Frame(self, bg=BG_CARD, height=6).pack()  # bottom padding

    def _on_change(self, _=None):
        self._num_label.config(text=str(self._var.get()))

    @property
    def value(self) -> int:
        return self._var.get()


# ─────────────────────────────────────────────
#  Main Application
# ─────────────────────────────────────────────
class PinterestDownloaderApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Pinterest Mass Downloader")
        self.geometry("1040x800")
        self.minsize(880, 640)
        self.configure(bg=BG_DARK)
        self.resizable(True, True)

        self._worker     = None
        self._thread     = None
        self._log_q      = queue.Queue()
        self._progress_q = queue.Queue()
        self._running    = False
        self._start_time = 0.0

        self._build_ui()
        self._poll_queues()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        header = tk.Frame(self, bg=BG_CARD, height=64)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        tk.Frame(header, bg=ACCENT, width=6).pack(side="left", fill="y")
        p_badge = tk.Frame(header, bg=ACCENT, padx=10)
        p_badge.pack(side="left", fill="y")
        tk.Label(p_badge, text="P", font=("Segoe UI", 26, "bold"),
                 bg=ACCENT, fg=TEXT_PRI).pack(expand=True)

        tk.Label(header, text="Pinterest Mass Downloader",
                 font=FONT_TITLE, bg=BG_CARD, fg=TEXT_PRI).pack(side="left",
                                                                  padx=14, pady=14)
        tk.Label(header, text="Fast · Threaded · Per-type Control",
                 font=FONT_SMALL, bg=BG_CARD, fg=TEXT_DIM).pack(side="left",
                                                                   pady=14, anchor="s")

        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x")

        # Body
        body = tk.Frame(self, bg=BG_DARK)
        body.pack(fill="both", expand=True, padx=20, pady=14)

        left = tk.Frame(body, bg=BG_DARK, width=460)
        left.pack(side="left", fill="y", padx=(0, 14))
        left.pack_propagate(False)

        right = tk.Frame(body, bg=BG_DARK)
        right.pack(side="left", fill="both", expand=True)

        self._build_controls(left)
        self._build_console(right)
        self._build_statusbar()

    def _section_label(self, parent, tag: str, title: str):
        row = tk.Frame(parent, bg=BG_DARK)
        row.pack(fill="x", pady=(14, 4))
        tk.Frame(row, bg=ACCENT, width=3).pack(side="left", fill="y")
        tk.Label(row, text=f"  {tag}",
                 font=("Segoe UI", 7, "bold"),
                 bg=BG_DARK, fg=ACCENT).pack(side="left")
        tk.Label(row, text=f"  {title}",
                 font=FONT_HEAD, bg=BG_DARK, fg=TEXT_PRI).pack(side="left")

    def _build_controls(self, parent):
        # ── Mode ──────────────────────────────────────────────────────────
        self._section_label(parent, "MODE", "Input Type")

        mode_card = tk.Frame(parent, bg=BG_CARD, relief="flat")
        mode_card.pack(fill="x", pady=2)
        mode_inner = tk.Frame(mode_card, bg=BG_CARD)
        mode_inner.pack(fill="x", padx=14, pady=10)

        self._mode_var = tk.StringVar(value="keyword")
        for val, label, hint in [
            ("keyword", "Keyword Search",   "e.g.  Fortnite cosplays"),
            ("board",   "Board / Pin URL",  "e.g.  https://pinterest.com/…"),
        ]:
            row = tk.Frame(mode_inner, bg=BG_CARD)
            row.pack(fill="x", pady=2)
            tk.Radiobutton(row, variable=self._mode_var, value=val,
                           bg=BG_CARD, activebackground=BG_CARD,
                           selectcolor=ACCENT_DARK,
                           fg=TEXT_PRI, activeforeground=TEXT_PRI,
                           font=FONT_SUB, cursor="hand2",
                           command=self._on_mode_change).pack(side="left")
            tk.Label(row, text=label, font=FONT_SUB,
                     bg=BG_CARD, fg=TEXT_PRI).pack(side="left")
            tk.Label(row, text=f"   {hint}", font=FONT_SMALL,
                     bg=BG_CARD, fg=TEXT_DIM).pack(side="left")

        # ── Query ─────────────────────────────────────────────────────────
        self._section_label(parent, "QUERY", "Keywords or URL")

        query_card = tk.Frame(parent, bg=BG_CARD)
        query_card.pack(fill="x", pady=2)
        self._query_entry = StyledEntry(
            query_card, placeholder="Enter keywords or board URL…")
        self._query_entry.pack(fill="x", padx=14, pady=12, ipady=7)

        # ── Save folder ───────────────────────────────────────────────────
        self._section_label(parent, "SAVE", "Download Folder")

        folder_card = tk.Frame(parent, bg=BG_CARD)
        folder_card.pack(fill="x", pady=2)
        folder_inner = tk.Frame(folder_card, bg=BG_CARD)
        folder_inner.pack(fill="x", padx=14, pady=10)

        self._folder_var = tk.StringVar(
            value=str(Path.home() / "Downloads" / "Pinterest"))
        tk.Entry(folder_inner,
                 textvariable=self._folder_var,
                 bg=BG_INPUT, fg=TEXT_PRI,
                 insertbackground=ACCENT,
                 relief="flat", bd=0, font=FONT_BODY,
                 highlightthickness=1,
                 highlightbackground=BORDER,
                 highlightcolor=ACCENT).pack(side="left", fill="x",
                                             expand=True, ipady=6)
        StyledButton(folder_inner, "Browse…",
                     command=self._browse_folder,
                     style="ghost").pack(side="left", padx=(8, 0))

        # ── Per-type count sliders ─────────────────────────────────────────
        self._section_label(parent, "COUNT", "Items per Media Type")

        self._img_slider = CountSliderCard(
            parent, icon="🖼", label="Pictures",
            colour=BLUE, max_val=300, default=50)
        self._img_slider.pack(fill="x", pady=(2, 4))

        self._vid_slider = CountSliderCard(
            parent, icon="🎬", label="Videos",
            colour=PURPLE, max_val=200, default=0)
        self._vid_slider.pack(fill="x", pady=(0, 4))

        self._gif_slider = CountSliderCard(
            parent, icon="✨", label="GIFs",
            colour=TEAL, max_val=200, default=0)
        self._gif_slider.pack(fill="x", pady=(0, 4))

        # ── Thread slider ─────────────────────────────────────────────────
        self._section_label(parent, "SPEED", "Parallel Threads")

        thread_card = tk.Frame(parent, bg=BG_CARD)
        thread_card.pack(fill="x", pady=2)
        thread_inner = tk.Frame(thread_card, bg=BG_CARD)
        thread_inner.pack(fill="x", padx=14, pady=8)

        self._threads_var = tk.IntVar(value=8)

        thread_top = tk.Frame(thread_inner, bg=BG_CARD)
        thread_top.pack(fill="x")
        tk.Label(thread_top, text="Concurrent threads:",
                 font=FONT_SMALL, bg=BG_CARD, fg=TEXT_SEC).pack(side="left")
        self._thread_label = tk.Label(thread_top, text="8",
                                      font=("Segoe UI", 16, "bold"),
                                      bg=BG_CARD, fg=ORANGE)
        self._thread_label.pack(side="right")

        tk.Scale(thread_inner, variable=self._threads_var,
                 from_=1, to=32, orient="horizontal",
                 bg=BG_CARD, fg=TEXT_PRI,
                 troughcolor=BG_INPUT, activebackground=ORANGE,
                 highlightthickness=0, sliderlength=22,
                 font=FONT_SMALL, showvalue=False,
                 command=self._on_thread_change).pack(fill="x", pady=(2, 0))

        # ── Action buttons ─────────────────────────────────────────────────
        btn_row = tk.Frame(parent, bg=BG_DARK)
        btn_row.pack(fill="x", pady=(16, 4))

        self._start_btn = StyledButton(
            btn_row, "  ▶  START DOWNLOAD  ",
            command=self._start_download, style="accent")
        self._start_btn.pack(side="left", fill="x", expand=True,
                             padx=(0, 8), ipady=5)

        self._stop_btn = StyledButton(
            btn_row, " ■  STOP ",
            command=self._stop_download, style="danger", state="disabled")
        self._stop_btn.pack(side="left", ipady=5)

        StyledButton(btn_row, " 📂 ",
                     command=self._open_folder,
                     style="ghost").pack(side="left", padx=(8, 0), ipady=5)

    def _build_console(self, parent):
        hdr = tk.Frame(parent, bg=BG_DARK)
        hdr.pack(fill="x", pady=(0, 6))
        tk.Label(hdr, text="ACTIVITY LOG",
                 font=FONT_HEAD, bg=BG_DARK, fg=TEXT_PRI).pack(side="left")
        tk.Frame(hdr, bg=BORDER, height=1).pack(side="left", fill="x",
                                                 expand=True, padx=10, pady=7)
        StyledButton(hdr, "Clear", style="neutral",
                     command=self._clear_log).pack(side="right")

        console_wrap = tk.Frame(parent, bg=BORDER, bd=1)
        console_wrap.pack(fill="both", expand=True)

        self._console = LogConsole(console_wrap)
        scroll = ttk.Scrollbar(console_wrap, command=self._console.yview)
        self._console.config(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self._console.pack(side="left", fill="both", expand=True,
                           padx=6, pady=6)

        self._console.append("Pinterest Mass Downloader — ready.", "success")
        self._console.append(
            "Tip: Set each slider to the number of that media type you want.", "info")
        self._console.append("─" * 58, "info")

        # Stats bar
        stats = tk.Frame(parent, bg=BG_CARD)
        stats.pack(fill="x", pady=(8, 0))

        self._dl_img_lbl = tk.Label(stats, text="Images: 0",
                                    font=FONT_SMALL, bg=BG_CARD, fg=BLUE)
        self._dl_img_lbl.pack(side="left", padx=12, pady=7)

        self._dl_vid_lbl = tk.Label(stats, text="Videos: 0",
                                    font=FONT_SMALL, bg=BG_CARD, fg=PURPLE)
        self._dl_vid_lbl.pack(side="left", padx=8, pady=7)

        self._dl_gif_lbl = tk.Label(stats, text="GIFs: 0",
                                    font=FONT_SMALL, bg=BG_CARD, fg=TEAL)
        self._dl_gif_lbl.pack(side="left", padx=8, pady=7)

        self._elapsed_lbl = tk.Label(stats, text="",
                                     font=FONT_SMALL, bg=BG_CARD, fg=TEXT_DIM)
        self._elapsed_lbl.pack(side="right", padx=12, pady=7)

    def _build_statusbar(self):
        bar = tk.Frame(self, bg=BG_CARD, height=30)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        tk.Frame(bar, bg=ACCENT, width=4).pack(side="left", fill="y")
        self._status_lbl = tk.Label(bar, text="Ready.",
                                    font=FONT_SMALL, bg=BG_CARD, fg=TEXT_SEC)
        self._status_lbl.pack(side="left", padx=10)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("P.Horizontal.TProgressbar",
                        troughcolor=BG_INPUT, background=ACCENT,
                        bordercolor=BG_CARD, lightcolor=ACCENT,
                        darkcolor=ACCENT_DARK)

        self._progress_var = tk.DoubleVar(value=0)
        self._progress_bar = ttk.Progressbar(
            bar, variable=self._progress_var,
            style="P.Horizontal.TProgressbar",
            length=240, mode="determinate")
        self._progress_bar.pack(side="right", padx=12, pady=4)

        self._progress_txt = tk.Label(bar, text="0 / 0",
                                      font=FONT_SMALL, bg=BG_CARD, fg=TEXT_DIM)
        self._progress_txt.pack(side="right", padx=(0, 4))

    # ── Events ──────────────────────────────────────────────────────────
    def _on_mode_change(self):
        pass

    def _on_thread_change(self, _=None):
        self._thread_label.config(text=str(self._threads_var.get()))

    def _browse_folder(self):
        d = filedialog.askdirectory(title="Select Download Folder",
                                    initialdir=self._folder_var.get())
        if d:
            self._folder_var.set(d)

    def _open_folder(self):
        p = self._folder_var.get()
        if os.path.isdir(p):
            os.startfile(p)
        else:
            messagebox.showinfo("Folder Not Found",
                                f"Folder does not exist yet:\n{p}\n\n"
                                "It will be created when you start downloading.")

    def _clear_log(self):
        self._console.clear()

    def _set_status(self, msg: str, col: str = TEXT_SEC):
        self._status_lbl.config(text=msg, fg=col)

    # ── Download control ─────────────────────────────────────────────────
    def _start_download(self):
        if self._running:
            return

        query = self._query_entry.real_value().strip()
        if not query:
            messagebox.showwarning("Missing Input",
                                   "Please enter a keyword or board URL.")
            return

        output_dir = self._folder_var.get().strip()
        if not output_dir:
            messagebox.showwarning("Missing Folder",
                                   "Please select a download folder.")
            return

        img_count = self._img_slider.value
        vid_count = self._vid_slider.value
        gif_count = self._gif_slider.value
        threads   = self._threads_var.get()

        if img_count + vid_count + gif_count == 0:
            messagebox.showwarning("Nothing Selected",
                                   "All sliders are at 0.\n"
                                   "Drag at least one slider above 0 to download.")
            return

        # Auto-detect URL
        if is_board_url(query):
            self._mode_var.set("board")

        self._running = True
        self._start_btn.config(state="disabled", text="  ⏳  DOWNLOADING…  ")
        self._stop_btn.config(state="normal")
        self._progress_var.set(0)
        self._progress_txt.config(text="0 / ?")
        self._dl_img_lbl.config(text="Images: 0")
        self._dl_vid_lbl.config(text="Videos: 0")
        self._dl_gif_lbl.config(text="GIFs: 0")
        self._elapsed_lbl.config(text="")
        self._set_status("Fetching pin metadata…", ACCENT)
        self._start_time = time.time()

        self._progress_bar.config(mode="indeterminate")
        self._progress_bar.start(12)

        self._log_q      = queue.Queue()
        self._progress_q = queue.Queue()

        self._worker = DownloadWorker(self._log_q, self._progress_q)
        self._thread = threading.Thread(
            target=self._worker.run,
            args=(query, output_dir, img_count, vid_count, gif_count, threads),
            daemon=True)
        self._thread.start()

    def _stop_download(self):
        if self._worker:
            self._worker.stop()
            self._log_q.put(("warning", f"[{ts()}] Stop requested by user."))
        self._finish_download()

    def _finish_download(self):
        self._running = False
        self._progress_bar.stop()
        self._progress_bar.config(mode="determinate")
        self._start_btn.config(state="normal", text="  ▶  START DOWNLOAD  ")
        self._stop_btn.config(state="disabled")
        elapsed = time.time() - self._start_time
        self._elapsed_lbl.config(text=f"Elapsed: {elapsed:.1f}s")
        self._set_status(f"Done in {elapsed:.1f}s", SUCCESS)

    # ── Queue polling ────────────────────────────────────────────────────
    def _poll_queues(self):
        # Logs
        try:
            while True:
                level, msg = self._log_q.get_nowait()
                self._console.append(msg, level)
        except queue.Empty:
            pass

        # Progress
        done = total = None
        try:
            while True:
                done, total = self._progress_q.get_nowait()
        except queue.Empty:
            pass

        if done is not None and total is not None:
            if total > 0:
                pct = (done / total) * 100
                self._progress_var.set(pct)
                self._progress_txt.config(text=f"{done} / {total}")
            else:
                self._progress_var.set(0)

        # Detect completion
        if self._running and self._thread and not self._thread.is_alive():
            self._finish_download()

        self.after(80, self._poll_queues)

    # ── Window close ─────────────────────────────────────────────────────
    def _on_close(self):
        if self._running:
            if messagebox.askyesno("Quit", "Download in progress. Quit anyway?"):
                if self._worker:
                    self._worker.stop()
                self.destroy()
        else:
            self.destroy()


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────
def main():
    try:
        import pinterest_dl  # noqa: F401
    except ImportError:
        root = tk.Tk()
        root.withdraw()
        answer = messagebox.askyesno(
            "Missing Dependency",
            "pinterest-dl is not installed.\n\n"
            "Install it now? (requires internet)")
        root.destroy()
        if answer:
            import subprocess
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "pinterest-dl"],
                check=True)
        else:
            sys.exit(1)

    app = PinterestDownloaderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
