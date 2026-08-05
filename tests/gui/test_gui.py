"""Unit and smoke tests for the refactored Tkinter GUI components."""

import tkinter as tk

import pytest

from pinterest_mass_downloader.application.events import LogEvent
from pinterest_mass_downloader.ui.app import PinterestDownloaderGUI
from pinterest_mass_downloader.ui.controller import UIController


def test_ui_controller_event_flow():
    controller = UIController()
    received_events = []

    controller._on_event(LogEvent(message="Test log"))
    controller.process_events(received_events.append)

    assert len(received_events) == 1
    assert received_events[0].message == "Test log"


def test_gui_instantiation(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tkinter display not available in headless environment")

    root.withdraw()

    try:
        app = PinterestDownloaderGUI(root)
        assert app.root == root
        assert app.ent_query.get() == "modern architecture"

        # Test adding job to queue from form
        app.ent_query.delete(0, tk.END)
        app.ent_query.insert(0, "nature photography")
        app.ent_output.delete(0, tk.END)
        app.ent_output.insert(0, str(tmp_path))

        app._add_job_from_form()
        assert len(app.controller.queue_manager.jobs) > 0
    finally:
        root.destroy()
