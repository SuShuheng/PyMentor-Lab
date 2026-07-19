"""Generate Windows .ico and a 256x256 PNG for the PyMentor Lab desktop app.

Source
------
The provided brand asset is ``assets/PyMentorLab.png`` at 162x157 RGBA. This
resolution is below the 256x256 minimum required for a high-quality Windows
application icon (and well below the >=512x512 source recommended for modern
HiDPI/Retina targets). To produce a compliant multi-resolution .ico we upscale
the source to 256x256 using Lanczos resampling, which gives acceptable results
for this low-complexity logo but will soften fine detail.

Recommendation for future releases: drop a >=512x512 master PNG (ideally
1024x1024) into ``assets/`` and this script will downscale it instead, yielding
crisper icons at every size. No code change is required once the source meets
the size threshold.

Outputs (written to ``apps/desktop/build/``)
--------------------------------------------
* ``icon.ico``   - multi-resolution ICO with sizes 16, 32, 48, 64, 128, 256.
                   Consumed by Electron Forge ``packagerConfig.icon`` (Forge
                   appends ``.ico`` automatically on Windows) and by
                   MakerSquirrel ``setupIcon``.
* ``icon-256.png`` - the 256x256 PNG, useful as the Linux/macOS app icon.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

# Repository layout: this script lives at infra/icons/generate-icons.py.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCE_PNG = REPO_ROOT / "assets" / "PyMentorLab.png"
BUILD_DIR = REPO_ROOT / "apps" / "desktop" / "build"
ICO_PATH = BUILD_DIR / "icon.ico"
PNG_256_PATH = BUILD_DIR / "icon-256.png"

# Sizes embedded in the .ico (Windows picks the best fit per context).
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
TARGET = 256


def main() -> None:
    if not SOURCE_PNG.exists():
        raise SystemExit(f"Source PNG not found: {SOURCE_PNG}")

    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    with Image.open(SOURCE_PNG) as src:
        src.load()
        print(f"Source: {SOURCE_PNG.relative_to(REPO_ROOT)} ({src.size[0]}x{src.size[1]} {src.mode})")

        if src.mode != "RGBA":
            src = src.convert("RGBA")

        # Upscale to 256x256 with Lanczos. Non-square source (162x157) is forced
        # to exactly 256x256 so the .ico entries are square as Windows expects.
        master = src.resize((TARGET, TARGET), Image.LANCZOS)

        # Save the 256x256 PNG first (Linux/macOS app icon).
        master.save(PNG_256_PATH, format="PNG")
        print(f"Wrote {PNG_256_PATH.relative_to(REPO_ROOT)} ({master.size[0]}x{master.size[1]})")

        # Multi-resolution .ico. Pillow downsamples from the in-memory master
        # for each requested size.
        master.save(ICO_PATH, format="ICO", sizes=ICO_SIZES)
        print(f"Wrote {ICO_PATH.relative_to(REPO_ROOT)} with sizes {ICO_SIZES}")


if __name__ == "__main__":
    main()
