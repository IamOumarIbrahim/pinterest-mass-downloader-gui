"""Grab a screen rectangle at a fixed frame rate into a near-lossless MP4.

usage: python capture.py X Y W H FPS OUT.mp4 STOPFILE TIMESFILE
Runs until STOPFILE exists. Writes the wall-clock time of every frame to
TIMESFILE (JSON) so the composer can line frames up with the driver's events.
"""

import json
import os
import subprocess
import sys
import time

import imageio_ffmpeg
from PIL import ImageGrab


def main():
    x, y, w, h, fps = map(int, sys.argv[1:6])
    out, stopfile, timesfile = sys.argv[6:9]
    w -= w % 2
    h -= h % 2
    ff = subprocess.Popen(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "ultrafast",
         "-crf", "8", "-pix_fmt", "yuv444p", out], stdin=subprocess.PIPE)
    times = []
    step = 1 / fps
    nxt = time.perf_counter()
    t0_wall = time.time() - time.perf_counter()
    while not os.path.exists(stopfile):
        frame = ImageGrab.grab((x, y, x + w, y + h), all_screens=True).convert("RGB").tobytes()
        now = time.perf_counter()
        # keep a constant frame rate: repeat the frame if we fell behind
        while nxt <= now:
            ff.stdin.write(frame)
            times.append(t0_wall + nxt)
            nxt += step
        time.sleep(max(0, nxt - time.perf_counter() - 0.002))
    ff.stdin.close()
    ff.wait()
    with open(timesfile, "w") as f:
        json.dump(times, f)


if __name__ == "__main__":
    main()
