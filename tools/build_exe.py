"""Build the Windows app: a folder you can zip and hand to anyone, no Python needed.

    pip install pyinstaller
    python tools/build_exe.py            # → dist/PinterestMassDownloader/PinterestMassDownloader.exe
    python tools/build_exe.py --zip      # also dist/PinterestMassDownloader-<version>-windows.zip

A folder build (not a single .exe) is used on purpose: a single file has to
unpack ffmpeg and the matching engine to a temp folder on every start, which
makes the app take many seconds to open.

The smart matching model is not bundled; the app downloads it (about 150 MB)
the first time smart matching is used, exactly as it does when run from source.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "PinterestMassDownloader"
# The app runs its model on the CPU. If the build machine has the GPU edition
# of onnxruntime, these come along for nothing (several hundred MB).
GPU_ONLY = ("onnxruntime_providers_cuda*", "onnxruntime_providers_tensorrt*", "cublas*", "cudnn*",
            "cufft*", "curand*", "cusolver*", "cusparse*", "cudart*", "nvrtc*", "nvinfer*",
            "nvjitlink*", "nvonnxparser*")
sys.path.insert(0, str(ROOT))
from pinmass import __version__  # noqa: E402


def main() -> int:
    sep = ";" if sys.platform == "win32" else ":"
    args = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", NAME,
        "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        "--add-data", f"{ROOT / 'pinmass' / 'phone_page.html'}{sep}pinmass",
        "--add-data", f"{ROOT / 'assets' / 'icon.ico'}{sep}assets",
        # packages that load their own data files or binaries at run time
        "--collect-all", "customtkinter",
        "--collect-all", "tkinterdnd2",
        "--collect-all", "imageio_ffmpeg",
        # only the engine itself: onnxruntime also ships model-conversion tools
        # that would drag in torch, scipy, pandas and friends if collected whole
        "--collect-binaries", "onnxruntime",
        "--hidden-import", "onnxruntime",
        "--hidden-import", "tokenizers",
        "--hidden-import", "pinterest_dl",
        "--hidden-import", "qrcode",
        "--hidden-import", "cryptography",
    ]
    # Whatever else happens to be installed on the build machine stays out.
    # (playwright is pinterest-dl's optional browser driver, never used here.)
    for module in ("playwright", "pytest", "torch", "torchvision", "tensorflow", "scipy",
                   "pandas", "matplotlib", "IPython", "jedi", "zmq", "notebook", "black",
                   "astroid", "sympy", "numba", "onnx", "transformers", "sklearn", "cv2",
                   "onnxruntime.transformers", "onnxruntime.tools", "onnxruntime.quantization",
                   "onnxruntime.training", "huggingface_hub", "pyarrow"):
        args += ["--exclude-module", module]
    icon = ROOT / "assets" / "icon.ico"
    if icon.exists():
        args += ["--icon", str(icon)]
    args.append(str(ROOT / "pinterest_downloader.py"))
    print("Building", NAME, __version__)
    if subprocess.call(args, cwd=ROOT) != 0:
        return 1
    out = ROOT / "dist" / NAME
    freed = 0
    for pattern in GPU_ONLY:
        for f in out.rglob(pattern):
            if f.is_file():
                freed += f.stat().st_size
                f.unlink()
    if freed:
        print(f"Removed {freed / 1e6:.0f} MB of GPU-only libraries the app doesn't use")
    exe = out / (NAME + (".exe" if sys.platform == "win32" else ""))
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1e6
    print(f"Built {exe}  ({size:.0f} MB in the folder)")
    if "--zip" in sys.argv:
        archive = shutil.make_archive(str(ROOT / "dist" / f"{NAME}-{__version__}-windows"), "zip",
                                      root_dir=out.parent, base_dir=NAME)
        print("Zipped", archive, f"({Path(archive).stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
