"""Automated GUI smoke script launching Tkinter window and scheduling clean close."""

import sys
import tkinter as tk

from pinterest_mass_downloader.ui.app import PinterestDownloaderGUI


def main():
    print("Starting Pinterest Mass Downloader GUI smoke test...")
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"Skipping GUI smoke test (no display available): {e}")
        return 0

    root.withdraw()  # Keep hidden during headless/smoke test if needed

    app = PinterestDownloaderGUI(root)
    assert app is not None
    assert app.root is not None

    # Schedule clean destroy after 300ms
    root.after(300, root.destroy)
    root.mainloop()

    print("GUI smoke test passed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
