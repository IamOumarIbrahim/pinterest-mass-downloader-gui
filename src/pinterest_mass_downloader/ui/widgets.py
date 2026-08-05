"""Custom styled Tkinter widgets for dark UI aesthetic."""

import tkinter as tk
from tkinter import ttk

from pinterest_mass_downloader.ui import theme


def apply_theme_styles(root: tk.Tk) -> ttk.Style:
    """Configure ttk theme styles for dark mode aesthetic."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(
        ".", background=theme.BG_COLOR, foreground=theme.TEXT_COLOR, font=theme.FONT_BODY
    )
    style.configure("TFrame", background=theme.BG_COLOR)
    style.configure("Card.TFrame", background=theme.SURFACE_COLOR, relief="flat", borderwidth=1)

    style.configure(
        "TLabel", background=theme.BG_COLOR, foreground=theme.TEXT_COLOR, font=theme.FONT_BODY
    )
    style.configure(
        "Card.TLabel",
        background=theme.SURFACE_COLOR,
        foreground=theme.TEXT_COLOR,
        font=theme.FONT_BODY,
    )
    style.configure(
        "Muted.TLabel",
        background=theme.SURFACE_COLOR,
        foreground=theme.TEXT_MUTED,
        font=theme.FONT_SMALL,
    )
    style.configure(
        "Header.TLabel",
        background=theme.BG_COLOR,
        foreground=theme.PRIMARY_RED,
        font=theme.FONT_TITLE,
    )

    style.configure(
        "Primary.TButton",
        background=theme.PRIMARY_RED,
        foreground="#FFFFFF",
        font=theme.FONT_HEADING,
        borderwidth=0,
        focusthickness=0,
        padding=6,
    )
    style.map("Primary.TButton", background=[("active", theme.PRIMARY_RED_HOVER)])

    style.configure(
        "Secondary.TButton",
        background=theme.SURFACE_LIGHT,
        foreground=theme.TEXT_COLOR,
        font=theme.FONT_BODY,
        borderwidth=0,
        padding=5,
    )
    style.map("Secondary.TButton", background=[("active", "#3D3D3D")])

    style.configure(
        "TEntry", fieldbackground=theme.SURFACE_LIGHT, foreground=theme.TEXT_COLOR, borderwidth=1
    )
    style.configure(
        "TSpinbox", fieldbackground=theme.SURFACE_LIGHT, foreground=theme.TEXT_COLOR, borderwidth=1
    )
    style.configure(
        "TCombobox", fieldbackground=theme.SURFACE_LIGHT, foreground=theme.TEXT_COLOR, borderwidth=1
    )

    # Progress bar style
    style.configure(
        "Horizontal.TProgressbar",
        troughcolor=theme.SURFACE_LIGHT,
        background=theme.PRIMARY_RED,
        borderwidth=0,
    )

    # Treeview style for Queue table
    style.configure(
        "Treeview",
        background=theme.SURFACE_COLOR,
        foreground=theme.TEXT_COLOR,
        fieldbackground=theme.SURFACE_COLOR,
        rowheight=26,
        font=theme.FONT_SMALL,
    )
    style.configure(
        "Treeview.Heading",
        background=theme.SURFACE_LIGHT,
        foreground=theme.TEXT_COLOR,
        font=theme.FONT_HEADING,
    )
    style.map("Treeview", background=[("selected", theme.PRIMARY_RED)])

    return style
