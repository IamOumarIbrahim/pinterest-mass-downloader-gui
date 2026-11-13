"""
Pinterest Mass Downloader

    python pinterest_downloader.py                 open the app
    python pinterest_downloader.py --keyword cats  download from the command line

See README.md for all options.
"""

import sys


def selftest(report: str) -> int:
    """Check that everything the app needs can be loaded, and write the result
    to *report*. Used to verify a packaged build, which has no console."""
    lines = []
    ok = True

    def step(name, fn, required=True):
        nonlocal ok
        try:
            lines.append(f"ok    {name}: {fn()}")
        except Exception as exc:  # report everything, whatever went wrong
            lines.append(f"{'FAIL ' if required else 'skip '} {name}: {exc.__class__.__name__}: {exc}")
            ok = ok and not required

    def window():
        from pinmass import gui
        app = gui.App()
        app.update()
        size = f"{app.winfo_width()}x{app.winfo_height()}"
        app._close()
        return size

    step("version", lambda: __import__("pinmass").__version__)
    step("phone page", lambda: f"{len(__import__('pinmass.phone', fromlist=['PAGE']).PAGE.read_text('utf-8'))} chars")
    step("ffmpeg", lambda: __import__("pinmass.media", fromlist=["find_ffmpeg"]).find_ffmpeg() or 1 / 0,
         required=False)
    def smart_engine():
        import onnxruntime
        import tokenizers  # noqa: F401
        assert "CPUExecutionProvider" in onnxruntime.get_available_providers()
        return f"onnxruntime {onnxruntime.__version__}"

    def smart_model():
        from PIL import Image

        from pinmass import smart
        if not smart.installed():
            raise RuntimeError("not downloaded yet (the app fetches it on first use)")
        clip = smart.get()
        red = clip.image(Image.new("RGB", (64, 64), (220, 20, 20)))
        fit = float(red @ clip.text("a picture of the color red"))
        other = float(red @ clip.text("a picture of a bicycle"))
        assert fit > other, (fit, other)
        return f"runs; red picture fits 'red' {fit:.2f} vs 'bicycle' {other:.2f}"

    step("smart matching engine", smart_engine, required=False)
    step("smart matching model", smart_model, required=False)
    step("qr code", lambda: __import__("pinmass.phone", fromlist=["qr_image"]).qr_image("x").size)
    step("library", lambda: __import__("pinmass.library", fromlist=["Library"]).Library(":memory:").count())
    step("pinterest-dl", lambda: __import__("pinterest_dl").__name__, required=False)
    step("window", window)
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(lines + ["PASS" if ok else "FAILED"]) + "\n")
    return 0 if ok else 1


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--selftest":
        return selftest(sys.argv[2])
    if len(sys.argv) > 1:
        from pinmass.cli import main as cli_main
        return cli_main(sys.argv[1:])
    from pinmass.gui import main as gui_main
    gui_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
