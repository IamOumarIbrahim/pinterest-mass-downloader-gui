"""Tkinter Desktop UI application for Pinterest Mass Downloader v2.0.0."""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from pinterest_mass_downloader.application.events import (
    AppEvent,
    LogEvent,
    ProgressEvent,
    TerminalResultEvent,
)
from pinterest_mass_downloader.domain.enums import BackendType, InputMode
from pinterest_mass_downloader.domain.models import DownloadRequest
from pinterest_mass_downloader.infrastructure.system import open_folder
from pinterest_mass_downloader.services.persistence import SettingsManager
from pinterest_mass_downloader.ui import theme
from pinterest_mass_downloader.ui.controller import UIController
from pinterest_mass_downloader.ui.widgets import apply_theme_styles


class PinterestDownloaderGUI:
    """Main Tkinter window for Pinterest Mass Downloader v2.0.0."""

    def __init__(self, root: tk.Tk, controller: Optional[UIController] = None):
        self.root = root
        self.controller = controller or UIController()
        self.settings_manager = SettingsManager()
        self.settings = self.settings_manager.load_settings()

        self.root.title("Pinterest Mass Downloader v2.0.0")
        self.root.geometry("1050x700")
        self.root.minsize(850, 550)
        self.root.configure(bg=theme.BG_COLOR)

        apply_theme_styles(self.root)

        self._setup_ui()
        self.refresh_queue_table()

        # Start periodic event polling loop
        self.root.after(100, self._poll_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _setup_ui(self) -> None:
        # Header
        header_frame = ttk.Frame(self.root)
        header_frame.pack(fill="x", padx=15, pady=10)
        lbl_title = ttk.Label(
            header_frame, text="Pinterest Mass Downloader v2.0.0", style="Header.TLabel"
        )
        lbl_title.pack(side="left")
        lbl_subtitle = ttk.Label(
            header_frame,
            text="Concurrent Pinterest Media Downloader",
            foreground=theme.TEXT_MUTED,
            font=theme.FONT_SMALL,
        )
        lbl_subtitle.pack(side="left", padx=15)

        # Main Split Frame
        main_paned = ttk.PanedWindow(self.root, orient="horizontal")
        main_paned.pack(fill="both", expand=True, padx=15, pady=5)

        # Left Panel: Job Form
        left_card = ttk.Frame(main_paned, style="Card.TFrame")
        main_paned.add(left_card, weight=1)

        self._setup_form(left_card)

        # Right Panel: Queue & Logs
        right_card = ttk.Frame(main_paned, style="Card.TFrame")
        main_paned.add(right_card, weight=2)

        self._setup_queue_and_logs(right_card)

    def _setup_form(self, parent: ttk.Frame) -> None:
        form_frame = ttk.Frame(parent, style="Card.TFrame")
        form_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Mode Selection
        mode_frame = ttk.Frame(form_frame, style="Card.TFrame")
        mode_frame.pack(fill="x", pady=5)
        ttk.Label(mode_frame, text="Mode:", style="Card.TLabel", font=theme.FONT_HEADING).pack(
            side="left"
        )

        self.var_mode = tk.StringVar(value=InputMode.KEYWORD.value)
        r1 = ttk.Radiobutton(
            mode_frame,
            text="Keyword Search",
            value=InputMode.KEYWORD.value,
            variable=self.var_mode,
            command=self._on_mode_change,
        )
        r1.pack(side="left", padx=10)
        r2 = ttk.Radiobutton(
            mode_frame,
            text="Pinterest Board/Pin URL",
            value=InputMode.URL.value,
            variable=self.var_mode,
            command=self._on_mode_change,
        )
        r2.pack(side="left", padx=10)

        # Query / URL Field
        self.lbl_query = ttk.Label(
            form_frame, text="Search Keyword:", style="Card.TLabel", font=theme.FONT_HEADING
        )
        self.lbl_query.pack(anchor="w", pady=(10, 2))

        self.ent_query = ttk.Entry(form_frame, width=40)
        self.ent_query.pack(fill="x", pady=2)
        self.ent_query.insert(0, "modern architecture")

        # Output Folder Field
        ttk.Label(
            form_frame, text="Base Output Directory:", style="Card.TLabel", font=theme.FONT_HEADING
        ).pack(anchor="w", pady=(10, 2))

        out_box = ttk.Frame(form_frame, style="Card.TFrame")
        out_box.pack(fill="x", pady=2)

        self.ent_output = ttk.Entry(out_box)
        self.ent_output.pack(side="left", fill="x", expand=True)
        self.ent_output.insert(0, self.settings.get("default_output_dir", ""))

        btn_browse_out = ttk.Button(
            out_box, text="Browse", style="Secondary.TButton", command=self._browse_output
        )
        btn_browse_out.pack(side="left", padx=5)

        # Media Limits
        limits_frame = ttk.Frame(form_frame, style="Card.TFrame")
        limits_frame.pack(fill="x", pady=10)

        ttk.Label(limits_frame, text="Images:", style="Card.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.spn_images = ttk.Spinbox(limits_frame, from_=0, to=5000, width=8)
        self.spn_images.grid(row=0, column=1, padx=5, pady=2)
        self.spn_images.set(self.settings.get("default_images", 50))

        ttk.Label(limits_frame, text="Videos:", style="Card.TLabel").grid(
            row=0, column=2, sticky="w", padx=(10, 0)
        )
        self.spn_videos = ttk.Spinbox(limits_frame, from_=0, to=1000, width=8)
        self.spn_videos.grid(row=0, column=3, padx=5, pady=2)
        self.spn_videos.set(self.settings.get("default_videos", 0))

        ttk.Label(limits_frame, text="GIFs:", style="Card.TLabel").grid(row=1, column=0, sticky="w")
        self.spn_gifs = ttk.Spinbox(limits_frame, from_=0, to=1000, width=8)
        self.spn_gifs.grid(row=1, column=1, padx=5, pady=2)
        self.spn_gifs.set(self.settings.get("default_gifs", 0))

        # Resolution Bounds
        ttk.Label(limits_frame, text="Min WxH:", style="Card.TLabel").grid(
            row=1, column=2, sticky="w", padx=(10, 0)
        )
        res_sub = ttk.Frame(limits_frame, style="Card.TFrame")
        res_sub.grid(row=1, column=3, sticky="w")
        self.spn_min_w = ttk.Spinbox(res_sub, from_=0, to=4000, width=5)
        self.spn_min_w.pack(side="left")
        self.spn_min_w.set(0)
        ttk.Label(res_sub, text="x", style="Card.TLabel").pack(side="left", padx=2)
        self.spn_min_h = ttk.Spinbox(res_sub, from_=0, to=4000, width=5)
        self.spn_min_h.pack(side="left")
        self.spn_min_h.set(0)

        # Backend Selector & Thread Note
        backend_frame = ttk.Frame(form_frame, style="Card.TFrame")
        backend_frame.pack(fill="x", pady=5)
        ttk.Label(backend_frame, text="Backend:", style="Card.TLabel").pack(side="left")
        self.cbo_backend = ttk.Combobox(
            backend_frame, values=["api", "chromium", "firefox"], width=12, state="readonly"
        )
        self.cbo_backend.set(self.settings.get("default_backend", "api"))
        self.cbo_backend.pack(side="left", padx=5)

        ttk.Label(
            form_frame,
            text="* Downloads process concurrently via pinterest-dl pool.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=2)

        # Optional Cookies File
        cookie_frame = ttk.Frame(form_frame, style="Card.TFrame")
        cookie_frame.pack(fill="x", pady=5)
        ttk.Label(cookie_frame, text="Cookies (Optional):", style="Card.TLabel").pack(anchor="w")
        cookie_sub = ttk.Frame(cookie_frame, style="Card.TFrame")
        cookie_sub.pack(fill="x", pady=2)

        self.ent_cookies = ttk.Entry(cookie_sub)
        self.ent_cookies.pack(side="left", fill="x", expand=True)
        btn_browse_cookie = ttk.Button(
            cookie_sub, text="Browse", style="Secondary.TButton", command=self._browse_cookies
        )
        btn_browse_cookie.pack(side="left", padx=5)
        ttk.Label(
            cookie_frame,
            text="Privacy Note: Cookie content is loaded at runtime and never saved to app state.",
            style="Muted.TLabel",
        ).pack(anchor="w")

        # Checkboxes
        self.var_raw_video = tk.BooleanVar(value=False)
        chk_raw = ttk.Checkbutton(
            form_frame, text="Raw Video Streams (skip FFmpeg remuxing)", variable=self.var_raw_video
        )
        chk_raw.pack(anchor="w", pady=5)

        # Add Job Button
        btn_add = ttk.Button(
            form_frame,
            text="+ Add Job to Queue",
            style="Primary.TButton",
            command=self._add_job_from_form,
        )
        btn_add.pack(fill="x", pady=10)

    def _setup_queue_and_logs(self, parent: ttk.Frame) -> None:
        q_frame = ttk.Frame(parent, style="Card.TFrame")
        q_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Action bar
        act_bar = ttk.Frame(q_frame, style="Card.TFrame")
        act_bar.pack(fill="x", pady=5)

        self.btn_start = ttk.Button(
            act_bar, text="▶ Start Queue", style="Primary.TButton", command=self._start_queue
        )
        self.btn_start.pack(side="left", padx=2)

        self.btn_stop = ttk.Button(
            act_bar, text="⏹ Stop Queue", style="Secondary.TButton", command=self._stop_queue
        )
        self.btn_stop.pack(side="left", padx=2)

        ttk.Button(
            act_bar, text="Retry Selected", style="Secondary.TButton", command=self._retry_selected
        ).pack(side="left", padx=5)
        ttk.Button(
            act_bar, text="Remove", style="Secondary.TButton", command=self._remove_selected
        ).pack(side="left", padx=2)
        ttk.Button(
            act_bar,
            text="Clear Completed",
            style="Secondary.TButton",
            command=self._clear_completed,
        ).pack(side="left", padx=2)

        ttk.Button(
            act_bar,
            text="Open Job Folder",
            style="Secondary.TButton",
            command=self._open_selected_folder,
        ).pack(side="right", padx=2)
        ttk.Button(
            act_bar,
            text="Open Base Folder",
            style="Secondary.TButton",
            command=self._open_base_folder,
        ).pack(side="right", padx=2)

        # Queue Table
        table_frame = ttk.Frame(q_frame, style="Card.TFrame")
        table_frame.pack(fill="both", expand=True, pady=5)

        cols = ("id", "query", "mode", "limits", "status", "progress", "summary")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=8)

        self.tree.heading("id", text="Job ID")
        self.tree.heading("query", text="Query / URL")
        self.tree.heading("mode", text="Mode")
        self.tree.heading("limits", text="Req (I/V/G)")
        self.tree.heading("status", text="Status")
        self.tree.heading("progress", text="Progress")
        self.tree.heading("summary", text="Summary")

        self.tree.column("id", width=80, anchor="center")
        self.tree.column("query", width=180)
        self.tree.column("mode", width=60, anchor="center")
        self.tree.column("limits", width=90, anchor="center")
        self.tree.column("status", width=90, anchor="center")
        self.tree.column("progress", width=80, anchor="center")
        self.tree.column("summary", width=150)

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Overall Progress Bar
        self.progress_bar = ttk.Progressbar(
            q_frame, orient="horizontal", mode="determinate", style="Horizontal.TProgressbar"
        )
        self.progress_bar.pack(fill="x", pady=5)

        # Activity Log Text
        lbl_log = ttk.Label(
            q_frame, text="Activity Log:", style="Card.TLabel", font=theme.FONT_HEADING
        )
        lbl_log.pack(anchor="w", pady=(5, 2))

        log_frame = ttk.Frame(q_frame, style="Card.TFrame")
        log_frame.pack(fill="both", expand=True, pady=2)

        self.txt_log = tk.Text(
            log_frame,
            height=6,
            bg=theme.BG_COLOR,
            fg=theme.TEXT_COLOR,
            insertbackground=theme.TEXT_COLOR,
            font=theme.FONT_SMALL,
            relief="flat",
        )
        log_scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscroll=log_scrollbar.set)

        self.txt_log.pack(side="left", fill="both", expand=True)
        log_scrollbar.pack(side="right", fill="y")

    def _on_mode_change(self) -> None:
        mode = self.var_mode.get()
        if mode == InputMode.KEYWORD.value:
            self.lbl_query.config(text="Search Keyword:")
        else:
            self.lbl_query.config(text="Pinterest Board/Pin URL:")

    def _browse_output(self) -> None:
        path = filedialog.askdirectory(initialdir=self.ent_output.get())
        if path:
            self.ent_output.delete(0, tk.END)
            self.ent_output.insert(0, path)

    def _browse_cookies(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")]
        )
        if path:
            self.ent_cookies.delete(0, tk.END)
            self.ent_cookies.insert(0, path)

    def _add_job_from_form(self) -> None:
        mode = InputMode(self.var_mode.get())
        query = self.ent_query.get().strip()
        output_dir = self.ent_output.get().strip()

        try:
            images = int(self.spn_images.get())
            videos = int(self.spn_videos.get())
            gifs = int(self.spn_gifs.get())
            min_w = int(self.spn_min_w.get())
            min_h = int(self.spn_min_h.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Counts and resolutions must be valid integers.")
            return

        cookies_p = self.ent_cookies.get().strip() or None

        req = DownloadRequest(
            mode=mode,
            query=query,
            output_dir=output_dir,
            images=images,
            videos=videos,
            gifs=gifs,
            min_width=min_w,
            min_height=min_h,
            backend=BackendType(self.cbo_backend.get()),
            cookies_path=cookies_p,
            raw_video=self.var_raw_video.get(),
        )

        try:
            req.validate()
        except Exception as ve:
            messagebox.showerror("Validation Error", str(ve))
            return

        job = self.controller.queue_manager.add_job(req)
        self.log(f"Added job {job.id[:8]} for '{query}'")
        self.refresh_queue_table()

    def refresh_queue_table(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        for job in self.controller.queue_manager.jobs:
            req = job.request
            limits = f"{req.images}/{req.videos}/{req.gifs}"
            summary = job.result.message or ""

            # Derive progress string
            downloaded = sum(c.downloaded for c in job.result.counts.values())
            selected = sum(c.selected for c in job.result.counts.values())
            prog_str = f"{downloaded}/{selected}" if selected > 0 else "0/0"

            self.tree.insert(
                "",
                "end",
                iid=job.id,
                values=(
                    job.id[:8],
                    req.query,
                    req.mode.value,
                    limits,
                    job.status.value.upper(),
                    prog_str,
                    summary,
                ),
            )

    def log(self, message: str, level: str = "INFO") -> None:
        self.txt_log.insert(tk.END, f"[{level}] {message}\n")
        self.txt_log.see(tk.END)

    def _start_queue(self) -> None:
        if self.controller.queue_manager.start_queue():
            self.log("Started queue execution.")
        else:
            messagebox.showinfo("Queue Running", "Queue is already executing.")

    def _stop_queue(self) -> None:
        self.controller.queue_manager.stop_queue()
        self.log("Requested queue cancellation...", level="WARNING")

    def _retry_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        job_id = sel[0]
        if self.controller.queue_manager.retry_job(job_id):
            self.refresh_queue_table()
            self.log(f"Retried job {job_id[:8]}")

    def _remove_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        job_id = sel[0]
        if self.controller.queue_manager.remove_job(job_id):
            self.refresh_queue_table()
            self.log(f"Removed job {job_id[:8]}")

    def _clear_completed(self) -> None:
        self.controller.queue_manager.clear_completed()
        self.refresh_queue_table()

    def _open_selected_folder(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        job_id = sel[0]
        for job in self.controller.queue_manager.jobs:
            if job.id == job_id:
                folder = Path(job.request.output_dir)
                open_folder(folder)
                break

    def _open_base_folder(self) -> None:
        out_dir = Path(self.ent_output.get().strip())
        open_folder(out_dir)

    def _poll_events(self) -> None:
        """Poll thread-safe event queue delivered by UIController."""
        self.controller.process_events(self._handle_event)
        self.refresh_queue_table()
        self.root.after(100, self._poll_events)

    def _handle_event(self, event: AppEvent) -> None:
        if isinstance(event, LogEvent):
            self.log(event.message, event.level)
        elif isinstance(event, ProgressEvent):
            self.progress_bar["value"] = event.percentage
        elif isinstance(event, TerminalResultEvent):
            self.refresh_queue_table()

    def _on_closing(self) -> None:
        if self.controller.queue_manager.is_running():
            msg = (
                "A download job is currently running.\n"
                "Stopping now will request safe cancellation.\n"
                "Do you want to exit?"
            )
            ans = messagebox.askyesno("Queue Active", msg)
            if ans:
                self.controller.queue_manager.stop_queue()
                self.root.destroy()
        else:
            self.root.destroy()


def launch_gui() -> int:
    """Launch Desktop Tkinter GUI Application."""
    root = tk.Tk()
    PinterestDownloaderGUI(root)
    root.mainloop()
    return 0
