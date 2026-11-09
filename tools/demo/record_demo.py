"""Record the README walkthrough: drives the real app and captures the screen.

usage: python tools/demo/record_demo.py REFERENCE_IMAGE WORKDIR [QUERY]

Produces WORKDIR/raw.mp4, WORKDIR/frames.json and WORKDIR/events.json; then run
compose_video.py to turn them into the polished video + GIF. The app runs with
its own throw-away settings folder, so nothing personal ends up on camera.
"""

import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

REF, WORK = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
QUERY = sys.argv[3] if len(sys.argv) > 3 else "fortnite llama"
os.makedirs(WORK, exist_ok=True)
os.environ["APPDATA"] = os.path.join(WORK, "appdata")
shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
# A short, clean path looks better on camera; it is created fresh and must not exist.
OUT = os.environ.get("DEMO_OUT") or os.path.join(WORK, "downloads")
if os.path.exists(OUT) and not os.environ.get("DEMO_OUT_REUSE"):
    sys.exit(f"{OUT} already exists; pick another DEMO_OUT")
os.makedirs(OUT, exist_ok=True)
_ref_copy = os.path.join(OUT, ".reference", os.path.basename(REF))
os.makedirs(os.path.dirname(_ref_copy), exist_ok=True)
shutil.copy(REF, _ref_copy)
REF = _ref_copy

from pinmass import settings  # noqa: E402

cfg = dict(settings.DEFAULTS, folder=OUT, image=50, look=True, colors=False,
           color_tolerance=50, closeness=50, appearance="Dark", recent=["cat aesthetic", "anime wallpaper"])
settings.save(cfg)

from pinmass.gui import App  # noqa: E402

W, H, X, Y = 1320, 860, 300, 70
app = App()
app.geometry(f"{W}x{H}+{X}+{Y}")
app.attributes("-topmost", True)
events: list[dict] = []


def log(kind, **kw):
    events.append({"t": time.time(), "type": kind, **kw})


def center(widget, dx=0, dy=0):
    app.update_idletasks()
    return (widget.winfo_rootx() - app.winfo_rootx() + widget.winfo_width() // 2 + dx,
            widget.winfo_rooty() - app.winfo_rooty() + widget.winfo_height() // 2 + dy)


def rect(widget, pad=12):
    app.update_idletasks()
    x = widget.winfo_rootx() - app.winfo_rootx()
    y = widget.winfo_rooty() - app.winfo_rooty()
    return [x - pad, y - pad, x + widget.winfo_width() + pad, y + widget.winfo_height() + pad]


def knob(slider, value):
    app.update_idletasks()
    lo, hi = slider.cget("from_"), slider.cget("to")
    frac = (value - lo) / (hi - lo)
    x = slider.winfo_rootx() - app.winfo_rootx()
    y = slider.winfo_rooty() - app.winfo_rooty() + slider.winfo_height() // 2
    return x + 10 + frac * (slider.winfo_width() - 20), y


def move(pos, dur=0.7):
    log("move", x=pos[0], y=pos[1], dur=dur)
    yield dur + 0.05


def click():
    log("click")
    yield 0.18


def caption(text):
    log("caption", text=text)
    yield 0


def focus(r=None, zoom=1.0):
    log("focus", rect=r, zoom=zoom)
    yield 0


def drag_slider(slider, to, steps=24, dur=0.9, on_change=None):
    start = slider.get()
    yield from move(knob(slider, start), 0.6)
    log("press")
    for i in range(1, steps + 1):
        v = start + (to - start) * (i / steps) ** 0.8
        slider.set(v)
        cmd = slider._command
        if cmd:
            cmd(v)
        if on_change:
            on_change(v)
        x, y = knob(slider, v)
        log("move", x=x, y=y, dur=dur / steps)
        yield dur / steps
    log("release")
    yield 0.3


def scroll_left(to, dur=0.8, steps=20):
    canvas = app.left_scroll._parent_canvas
    start = canvas.yview()[0]
    for i in range(1, steps + 1):
        f = i / steps
        f = f * f * (3 - 2 * f)
        canvas.yview_moveto(start + (to - start) * f)
        yield dur / steps


def type_text(entry, text, cps=11):
    for ch in text:
        entry.insert("end", ch)
        app._update_mode_hint()
        yield 1 / cps


def script():
    yield 1.2
    yield from caption("Type what you're looking for")
    yield from focus(rect(app.search.master.master, 6), 1.55)
    yield from move(center(app.search, -120))
    yield from click()
    app.search.focus_set()
    yield from type_text(app.search, QUERY)
    yield 0.8

    yield from caption("Choose how many pictures, videos and GIFs")
    yield from focus(rect(app.rows["image"].master.master, 6), 1.5)
    yield 0.4
    yield from drag_slider(app.rows["image"].slider, 8)
    yield 0.6

    yield from caption("Drop in a picture you like")
    yield from focus(None)
    yield from scroll_left(0.27)
    yield 0.2
    drop_c = center(app.drop)
    yield from move((W - 60, drop_c[1] - 40), 0.6)
    log("drag_file", path=REF)
    yield from move(drop_c, 1.0)
    log("drop")
    app._load_reference(REF)
    yield from focus(rect(app.drop.master.master, 6), 1.45)
    yield 1.6

    yield from caption("Match its look, its colors, or both")
    yield from move(center(app.match_boxes["colors"], -40))
    yield from click()
    app.colors.set(True)
    app._refresh_match_ui()
    yield 0.6
    yield from scroll_left(0.52)
    yield from focus(rect(app.color_box, 10), 1.45)
    yield 1.2

    yield from caption("Tolerance: same color amounts  ↔  any amounts")
    yield from drag_slider(app.tol_slider, 15, dur=1.0)
    yield 0.7
    yield from drag_slider(app.tol_slider, 85, dur=1.2)
    yield 0.6
    yield from drag_slider(app.tol_slider, 70, dur=0.6)
    yield 0.8

    yield from caption("…or pick your own colors (click one to remove it)")
    yield from move(center(app.pick_btn))
    yield from click()
    app.add_color("#ff2d95")
    yield 1.3
    n = len(app.palette.shares)
    last = app.swatch_labels[-1]
    yield from move(center(last, 20))
    yield from click()
    app._remove_color(n - 1)
    yield 1.0

    yield from caption("Hit Download: matches stream in with their score")
    yield from focus(None)
    yield from move(center(app.go_btn))
    yield from click()
    app.start()
    yield 1.5
    yield from move((W // 2 + 250, 380), 1.2)
    log("speed", factor=4)
    t0 = time.time()
    while app.running and time.time() - t0 < 150:
        yield 0.3
    log("speed", factor=1)
    yield 1.0
    yield from focus(rect(app.gallery.master, 4), 1.12)
    yield 2.5
    yield from focus(None)

    yield from caption("Open Phone to browse & share from your phone")
    yield from move(center(app.phone_btn))
    yield from click()
    app.open_phone()
    app.phone_win.attributes("-topmost", True)
    app.phone_win.geometry(f"520x700+{X + 760}+{Y + 90}")
    yield 0.8
    yield from move((800, 400), 0.8)
    yield 3.5
    yield from caption(None)
    yield 0.6


def run():
    gen = script()

    def step():
        try:
            d = next(gen)
        except StopIteration:
            finish()
            return
        app.after(max(1, int(d * 1000)), step)
    step()


def finish():
    open(stopfile, "w").close()
    cap.wait(timeout=60)
    with open(os.path.join(WORK, "events.json"), "w") as f:
        json.dump({"window": [W, H], "events": events}, f, indent=1)
    app._close()


stopfile = os.path.join(WORK, "stop")
if os.path.exists(stopfile):
    os.remove(stopfile)


def begin():
    global cap
    app.update()
    x, y = app.winfo_rootx(), app.winfo_rooty()
    cap = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), "capture.py"),
                            str(x), str(y), str(W), str(H), "30", os.path.join(WORK, "raw.mp4"),
                            stopfile, os.path.join(WORK, "frames.json")])
    app.after(1500, run)


app.after(1500, begin)
app.mainloop()
