#!/usr/bin/env python3
"""
asciiplay - a small native video/audio player with a terminal look.

  * drag & drop video, audio, subtitle files or URLs
  * audio / subtitle track selection, playback speed
  * ASCII art filter: the video is rendered as coloured text
  * colour modes (phosphor green/amber/mono, greyscale, retro palettes) for the filters
    and for plain video alike
  * optional CRT screen over the picture - with a display filter under it or straight on
    plain video, for a TV look (curvature, shadow mask, scanlines, focus blur, bloom,
    grain, chromatic aberration, phosphor trail; the last three adjustable, and the trail
    can be given a colour) - OpenGL only
  * audio files are always shown as an ASCII visualiser
  * checks its dependencies and prints the install commands if something is missing

Built on libmpv (decoding, tracks, speed, subtitles), PyQt6 (window) and numpy (ASCII conversion).
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import importlib.util
import locale
import math
import os
import shutil
import sys
import threading
import time

APP_NAME = "asciiplay"
VERSION = "1.3"
HOMEPAGE = "https://github.com/3p1cball-code/asciiplay"

# --------------------------------------------------------------------------------------
# Dependency check (runs before any third-party import)
# --------------------------------------------------------------------------------------

# package names per distro family
DEPS = [
    {
        "key": "pyqt6", "label": "PyQt6", "desc": "Qt 6 GUI bindings (python module)",
        "module": "PyQt6.QtWidgets", "pip": "PyQt6",
        "pkg": {"fedora": "python3-pyqt6", "debian": "python3-pyqt6", "arch": "python-pyqt6", "suse": "python3-PyQt6"},
    },
    {
        "key": "numpy", "label": "numpy", "desc": "array maths for the ASCII filter (python module)",
        "module": "numpy", "pip": "numpy",
        "pkg": {"fedora": "python3-numpy", "debian": "python3-numpy", "arch": "python-numpy", "suse": "python3-numpy"},
    },
    {
        "key": "libmpv", "label": "libmpv", "desc": "mpv media library (shared library, handles all formats)",
        "lib": True, "pip": None,
        "pkg": {"fedora": "mpv-libs", "debian": "libmpv2", "arch": "mpv", "suse": "libmpv2"},
    },
    {
        "key": "python-mpv", "label": "python-mpv", "desc": "python bindings for libmpv (python module)",
        "module": "mpv", "pip": "python-mpv",
        "pkg": {"fedora": "python3-mpv", "debian": "python3-mpv", "arch": "python-mpv", "suse": None},
    },
]

FAMILY_INFO = {
    "fedora": ("sudo dnf install", "Fedora family (Nobara, Fedora, RHEL)"),
    "debian": ("sudo apt install", "Debian family (Debian, Ubuntu, Mint, Pop!_OS)"),
    "arch": ("sudo pacman -S", "Arch family (Arch, Manjaro, EndeavourOS)"),
    "suse": ("sudo zypper install", "openSUSE"),
}


def detect_distro():
    """Return (pretty_name, family) from /etc/os-release."""
    info = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            for line in fh:
                if "=" in line:
                    k, v = line.rstrip("\n").split("=", 1)
                    info[k] = v.strip().strip('"')
    except OSError:
        pass
    ids = [info.get("ID", "")] + info.get("ID_LIKE", "").split()
    family = None
    for i in ids:
        i = i.lower()
        if i in ("fedora", "rhel", "centos", "nobara"):
            family = "fedora"
        elif i in ("debian", "ubuntu"):
            family = "debian"
        elif i in ("arch", "manjaro", "endeavouros"):
            family = "arch"
        elif i in ("opensuse", "suse", "opensuse-tumbleweed", "opensuse-leap"):
            family = "suse"
        if family:
            break
    return info.get("PRETTY_NAME", info.get("NAME", "unknown Linux")), family


def find_libmpv():
    name = ctypes.util.find_library("mpv")
    if name:
        return name
    for cand in ("libmpv.so.2", "libmpv.so.1", "libmpv.so"):
        try:
            ctypes.CDLL(cand)
            return cand
        except OSError:
            continue
    return None


def check_dependencies():
    """Return list of (dep, present: bool)."""
    result = []
    for dep in DEPS:
        if dep.get("lib"):
            ok = find_libmpv() is not None
        else:
            try:
                ok = importlib.util.find_spec(dep["module"]) is not None
            except (ImportError, ValueError):
                ok = False
        result.append((dep, ok))
    return result


def print_dependency_report(status, force=False):
    missing = [d for d, ok in status if not ok]
    if not missing and not force:
        return False
    distro, family = detect_distro()
    out = sys.stderr if missing else sys.stdout
    print(f"{APP_NAME} {VERSION} - dependency check on {distro}", file=out)
    for dep, ok in status:
        mark = "OK " if ok else "MISSING"
        print(f"  [{mark:7}] {dep['label']:<11} {dep['desc']}", file=out)
    if not missing:
        print("\nEverything is installed.", file=out)
        return False

    print("", file=out)
    if family in FAMILY_INFO:
        cmd, fam_label = FAMILY_INFO[family]
        pkgs = [d["pkg"].get(family) for d in missing]
        known = [p for p in pkgs if p]
        unknown = [d for d in missing if not d["pkg"].get(family)]
        print(f"Install on {fam_label} - copy & paste this:\n", file=out)
        if known:
            print(f"    {cmd} {' '.join(known)}\n", file=out)
        if unknown:
            print("Not packaged by your distro, install with pip:\n", file=out)
            pips = [d["pip"] for d in unknown if d["pip"]]
            if pips:
                print(f"    python3 -m pip install --user {' '.join(pips)}\n", file=out)
        if family == "fedora":
            print("Notes for Fedora/Nobara: 'mpv-libs' comes from RPM Fusion and 'python3-mpv' from the Terra", file=out)
            print("repository (both are enabled by default on Nobara). If dnf cannot find python3-mpv, use:\n", file=out)
            print("    python3 -m pip install --user python-mpv\n", file=out)
    else:
        print("Could not detect your distribution. Install these with your package manager:", file=out)
        for d in missing:
            print(f"    {d['label']}: " + ", ".join(f"{k}: {v}" for k, v in d["pkg"].items() if v), file=out)
        pips = [d["pip"] for d in missing if d["pip"]]
        if pips:
            print(f"\nPython modules can also come from pip:\n    python3 -m pip install --user {' '.join(pips)}", file=out)
    print(f"Then run again:  python3 {os.path.basename(sys.argv[0]) or 'asciiplay.py'}", file=out)
    return True


def parse_args(argv):
    p = argparse.ArgumentParser(prog=APP_NAME, description="terminal-style video/audio player with ASCII art filter")
    p.add_argument("files", nargs="*", help="media files, subtitle files or URLs to open")
    p.add_argument("--check", action="store_true", help="only check dependencies and exit")
    p.add_argument("--ascii", action="store_true", help="start with the ASCII filter enabled")
    p.add_argument("--filter", choices=["off", "ascii", "bayer2", "bayer4", "bayer8", "vector"], default=None,
                   help="start with this display filter on: ASCII art, Bayer 1-bit dithering (2x2, 4x4 or 8x8 "
                        "matrix) or the vector display (default: off, or ascii with --ascii)")
    p.add_argument("--font-size", type=int, default=12, help="ASCII cell font size in pixels (default 12)")
    p.add_argument("--pixel-size", type=int, default=2,
                   help="size of one dither/vector pixel in screen pixels for the Bayer and vector filters "
                        "(default 2; the resolution divider multiplies it)")
    p.add_argument("--crt", action="store_true",
                   help="start with the CRT screen filter on (over the display filter, or over plain video "
                        "for a TV look; OpenGL renderer only)")
    p.add_argument("--crt-level", choices=["subtle", "normal", "heavy"], default="normal",
                   help="how strong the CRT screen filter is (default normal)")
    # the three live CRT knobs (see CRT_KNOBS); 4 is CRT_KNOB_MAX, which is defined further
    # down - this function already runs during the dependency check, before that point
    p.add_argument("--crt-blur", type=float, default=1.0, metavar="X",
                   help="scale the CRT's focus blur (the beam's spot size): 0 = perfectly sharp, "
                        "1 = what the intensity level asks for (default), up to 4")
    p.add_argument("--crt-trail", type=float, default=1.0, metavar="X",
                   help="scale the CRT's phosphor trail (the smudge behind moving things): 0 = none, "
                        "1 = default, up to 4")
    p.add_argument("--crt-aberr", type=float, default=1.0, metavar="X",
                   help="scale the CRT's chromatic aberration (colour convergence error): 0 = none, "
                        "1 = default, up to 4")
    p.add_argument("--crt-trail-color", "--crt-trail-colour", metavar="NAME", default="auto",
                   help="colour the phosphor trail glows as it fades: auto (the picture's own colours), "
                        "green, amber, white, cyan, blue, magenta or red (default auto)")
    p.add_argument("--color", "--colour", dest="color", metavar="MODE", default=None,
                   help="start in this colour mode: color, raw (greyscale), green, amber, mono, pal8, "
                        "pal16 or pal32. Applies to the display filters and, with none of them on, to "
                        "the video itself")
    p.add_argument("--hwdec", default=None,
                   help="mpv hwdec setting (default: auto-safe with the OpenGL renderer, auto-copy with the "
                        "software renderer; use 'no' to disable)")
    p.add_argument("--fullscreen", action="store_true", help="start in fullscreen")
    p.add_argument("--ytdl-format", default="bestvideo[height<=?1080]+bestaudio/best",
                   help="yt-dlp format for YouTube & co (default: best up to 1080p; e.g. 'best' or "
                        "'bestvideo[height<=?2160]+bestaudio/best' for 4K)")
    p.add_argument("--ytdl-cookies-from-browser", metavar="BROWSER", default=None,
                   help="let yt-dlp use your browser's cookies (firefox, chrome, chromium, brave, edge, "
                        "opera, vivaldi, safari; a profile can follow, e.g. 'firefox:default'). This is the "
                        "cure when YouTube answers 'Sign in to confirm you are not a bot'")
    p.add_argument("--ytdl-client", metavar="CLIENT", default=None,
                   help="which YouTube player client yt-dlp should pretend to be (e.g. android_vr, tv, web, "
                        "ios; several separated by commas). Another thing to try against the bot check, and "
                        "it needs no cookies - but which client works changes over time")
    p.add_argument("--ytdl-raw-options", metavar="K=V,...", default=None,
                   help="anything else to hand yt-dlp, in mpv's --ytdl-raw-options syntax (added after the "
                        "two options above)")
    p.add_argument("--fps", action="store_true", help="print rendered frames per second to stderr")
    p.add_argument("--renderer", choices=["auto", "gl", "software"], default="auto",
                   help="how frames get to the screen: 'gl' draws with the GPU through OpenGL (video and "
                        "ASCII filter alike), 'software' is the old CPU path; 'auto' (default) tries gl "
                        "and falls back to software")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    return p.parse_args(argv)


if __name__ == "__main__":
    ARGS = parse_args(sys.argv[1:])
    _status = check_dependencies()
    if ARGS.check:
        print_dependency_report(_status, force=True)
        sys.exit(1 if any(not ok for _, ok in _status) else 0)
    if print_dependency_report(_status):
        sys.exit(1)

# --------------------------------------------------------------------------------------
# Real imports
# --------------------------------------------------------------------------------------
import numpy as np  # noqa: E402
import mpv  # noqa: E402
from PyQt6.QtCore import (QItemSelectionModel, QObject, QPoint, QPropertyAnimation, QRect,  # noqa: E402
                          QSize, Qt, QTimer, QUrl, pyqtSignal)
from PyQt6.QtGui import (QAction, QColor, QFont, QFontDatabase, QFontMetrics, QIcon, QImage,  # noqa: E402
                         QKeySequence, QPainter, QPen)
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QDockWidget,  # noqa: E402
                             QDoubleSpinBox, QFileDialog, QGraphicsOpacityEffect, QHBoxLayout,
                             QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                             QMessageBox, QPushButton, QSlider, QStyle, QToolButton, QVBoxLayout,
                             QWidget)
from PyQt6.QtGui import QOpenGLContext, QSurfaceFormat, QVector2D, QVector3D, QVector4D  # noqa: E402
try:
    # Part of PyQt6 proper on every distro we know of, but degrade to the software
    # renderer rather than crash if a packager split them out.
    from PyQt6.QtOpenGL import (QOpenGLFramebufferObject, QOpenGLShader,  # noqa: E402
                                QOpenGLShaderProgram, QOpenGLTexture, QOpenGLVertexArrayObject)
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget  # noqa: E402
    HAVE_GL = True
except ImportError:  # pragma: no cover
    HAVE_GL = False

# Where each browser yt-dlp can read cookies from keeps its profile, so the hint below can
# name one the user actually has rather than a guess.
BROWSER_DIRS = {
    "firefox": ("~/.mozilla/firefox", "~/snap/firefox/common/.mozilla/firefox",
                "~/.var/app/org.mozilla.firefox/.mozilla/firefox"),
    "chrome": ("~/.config/google-chrome",),
    "chromium": ("~/.config/chromium", "~/snap/chromium/common/chromium",
                 "~/.var/app/org.chromium.Chromium/config/chromium"),
    "brave": ("~/.config/BraveSoftware/Brave-Browser",),
    "edge": ("~/.config/microsoft-edge",),
    "vivaldi": ("~/.config/vivaldi",),
    "opera": ("~/.config/opera",),
}


def installed_browsers():
    """The browsers yt-dlp could take cookies from on this machine, best guess by profile dir."""
    return [name for name, dirs in BROWSER_DIRS.items()
            if any(os.path.isdir(os.path.expanduser(d)) for d in dirs)]


def ytdl_bot_hint():
    """YouTube sometimes refuses to hand yt-dlp a stream unless the request looks like a
    signed-in browser ("Sign in to confirm you're not a bot"). Nothing in the player can fix
    that - it is an anti-bot check on YouTube's side, keyed to the IP address and how many
    requests have come from it - so say what actually helps instead of the raw error."""
    found = installed_browsers()
    browser = found[0] if found else "firefox"
    others = "  (or: " + ", ".join(found[1:5]) + ")" if len(found) > 1 else ""
    return ("YouTube asked yt-dlp to \"confirm you're not a bot\".\n"
            "That is YouTube blocking this connection, not a problem with the file.\n"
            f"Start asciiplay with   --ytdl-cookies-from-browser {browser}{others}\n"
            "to let yt-dlp use your browser's YouTube login, or try\n"
            "  --ytdl-client android_vr   which needs no cookies.\n"
            "Waiting a few minutes often clears it by itself.")
SUB_EXT = {".srt", ".ass", ".ssa", ".sub", ".vtt", ".sup", ".idx", ".lrc", ".txt", ".smi", ".mks"}
MEDIA_FILTER = ("Media files (*.mp4 *.mkv *.webm *.avi *.mov *.m4v *.mpg *.mpeg *.ts *.flv *.wmv *.ogv "
                "*.mp3 *.flac *.ogg *.oga *.opus *.wav *.m4a *.aac *.wma *.aiff *.ape);;All files (*)")
SUB_FILTER = "Subtitles (*.srt *.ass *.ssa *.sub *.vtt *.sup *.idx *.lrc *.smi);;All files (*)"

# From few characters to a lot, so the dropdown reads as a density scale. Each ramp is
# authored roughly light -> dark, but the final ordering is decided at glyph-atlas build
# time by measuring each glyph's ink coverage in the font actually in use (see
# AsciiRenderer._ensure_atlas) - that is what guarantees a strictly monotonic ramp and no
# dark banding in smooth gradients, regardless of which monospace font the system provides.
CHAR_RAMPS = {
    "blocks": " ░▒▓█",
    "minimal": " <\\Yb$",
    "simple": " .:-=+*#%@",
    "digits": " .:1234567890",
    "detailed": " `,Ii~-[1|truzULOwdh*W%$",
    "classic": " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$",
}
# Colour modes cycled with `e`. The first five tint the picture directly (full colour,
# the raw video colour, and three CRT phosphors); the `pal*` modes snap every colour to a
# fixed retro palette (see PALETTES). All of them apply to every display filter, and with
# no filter on to the video itself (VIDEO_COLOR_FRAG), where `raw` means plain greyscale -
# the black and white TV - since the picture is already the raw video colour.
COLOR_MODES = ["color", "raw", "green", "amber", "mono", "pal8", "pal16", "pal32"]
COLOR_MODE_LABELS = {"color": "colour", "raw": "raw", "green": "green phosphor", "amber": "amber phosphor",
                     "mono": "mono phosphor", "pal8": "8 colours (RGB)", "pal16": "16 colours (CGA)",
                     "pal32": "32 colours (DB32)"}
# Quantised palettes for the pal* colour modes: (dither spread, RGB colours). The spread
# is how far the Bayer matrix pushes a colour before it snaps to the nearest entry - a
# sparser palette needs a wider spread to produce a visible dither pattern between two
# neighbouring colours instead of flat areas.
#   pal8   the 3-bit RGB set of the ZX Spectrum / BBC Micro / Teletext era
#   pal16  the 16 CGA/EGA text-mode colours every PC once had
#   pal32  DawnBringer's DB32, a general-purpose 32-colour pixel-art palette
PALETTES = {
    "pal8": (0.50, [(0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255),
                    (0, 255, 255), (255, 255, 255)]),
    "pal16": (0.35, [(0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170), (170, 0, 0), (170, 0, 170),
                     (170, 85, 0), (170, 170, 170), (85, 85, 85), (85, 85, 255), (85, 255, 85),
                     (85, 255, 255), (255, 85, 85), (255, 85, 255), (255, 255, 85), (255, 255, 255)]),
    "pal32": (0.25, [(0, 0, 0), (34, 32, 52), (69, 40, 60), (102, 57, 49), (143, 86, 59), (223, 113, 38),
                     (217, 160, 102), (238, 195, 154), (251, 242, 54), (153, 229, 80), (106, 190, 48),
                     (55, 148, 110), (75, 105, 47), (82, 75, 36), (50, 60, 57), (63, 63, 116),
                     (48, 96, 130), (91, 110, 225), (99, 155, 255), (95, 205, 228), (203, 219, 252),
                     (255, 255, 255), (155, 173, 183), (132, 126, 135), (105, 106, 106), (89, 86, 82),
                     (118, 66, 138), (172, 50, 50), (217, 87, 99), (215, 123, 186), (143, 151, 74),
                     (138, 111, 48)]),
}
# Display filters cycled with `t` (off -> each of these -> off). `ascii` is the ASCII art
# renderer; the `bayer*` filters are 1-bit ordered dithering with a 2x2, 4x4 or 8x8 Bayer
# matrix (the classic Mac/Atari ST/Amiga 1-bit look, in colour variants via `e`); `vector`
# runs an edge detector over the picture and draws the edges as glowing beam traces, like
# a vector monitor (Vectrex, Asteroids, Tempest). The Bayer and vector filters work on a
# grid of "pixels" rather than character cells: PIXEL size = --pixel-size (Ctrl+-/=)
# times the resolution divider (`d`), in screen pixels.
FILTERS = [("ascii", "ASCII art"), ("bayer2", "Bayer 2×2"), ("bayer4", "Bayer 4×4"), ("bayer8", "Bayer 8×8"),
           ("vector", "vector display")]
FILTER_NAMES = [name for name, _ in FILTERS]
FILTER_LABELS = dict(FILTERS)
# What the filter button and its dropdown say - kept short so the control bar does not
# get any wider than it was before the Bayer and vector filters existed.
FILTER_SHORT = {"ascii": "ascii", "bayer2": "bayer 2×2", "bayer4": "bayer 4×4", "bayer8": "bayer 8×8",
                "vector": "vector"}
FILTER_BUTTON = {"ascii": "ASCII", "bayer2": "BAYER", "bayer4": "BAYER", "bayer8": "BAYER", "vector": "VECTOR"}
BAYER_ORDER = {"bayer2": 1, "bayer4": 2, "bayer8": 3}     # matrix side = 2 ** order
# Vector display: Sobel edge magnitude below `lo` is dropped, above `hi` is a full-strength
# beam; `glow` is how much of the blurred beam is added back as halo (without the CRT filter
# that halo is all the glow there is).
VECTOR_EDGE_LO, VECTOR_EDGE_HI, VECTOR_GLOW = 0.06, 0.30, 1.2
# Crop presets cycled with `c` (like VLC): each is a target *display* aspect ratio (w/h).
# The picture is centre-cropped to that ratio, trimming baked-in black bars - top/bottom
# when the target is wider than the source, left/right when it is narrower. "off" clears
# the crop. The crop is applied with mpv's `crop` video filter, so it also feeds the
# ASCII path (which just picks up the new video-out-params).
CROP_RATIOS = [
    ("off", None),
    ("16:9", 16 / 9),
    ("16:10", 16 / 10),
    ("1.85:1", 1.85),
    ("2.00:1", 2.0),
    ("2.21:1", 2.21),
    ("2.35:1", 2.35),
    ("2.39:1", 2.39),
    ("4:3", 4 / 3),
    ("5:4", 5 / 4),
    ("1:1", 1.0),
]
# ASCII resolution divider: how many display pixels each character cell covers in each
# direction. 1 = full detail (one cell per available character-sized area); 2/4 = a
# quarter/sixteenth as many cells to render, stretched back up to fill the display -
# trades detail for speed, and applies to the audio visualiser too (same render path).
RES_DIVIDERS = [("Full (1:1)", 1), ("Half (1:2)", 2), ("Quarter (1:4)", 4)]
PHOSPHOR = {"green": (80, 255, 90), "amber": (0, 180, 255), "mono": (230, 230, 230)}  # BGR
# CRT screen filter (GL renderer only): an optional post-processing chain layered on top
# of the ASCII picture - see CRT_FRAG and GLVideoWidget._draw_crt. Three intensities, each
# a full set of knobs:
#   curve     barrel distortion of the picture (0 = flat glass)
#   mask      aperture-grille shadow mask strength (RGB stripes fixed to the glass)
#   scan      scanline strength (a whole number of lines per character row)
#   bloom     how much of the blurred, highlight-weighted picture is added back as glow
#   grain     per-pixel, per-frame noise
#   hum       a faint brightness bar slowly rolling down the tube
#   vignette  corner darkening
#   aberr     colour convergence error at the edge of the picture, in pixels
#   blur      focus blur: the electron beam's spot size, as a gaussian sigma in pixels
#             (horizontal; vertically it is CRT_BLUR_ASPECT of that, like a real tube's
#             limited video bandwidth)
#   tau       phosphor afterglow: per-channel (R, G, B) decay time constants in seconds -
#             bright things leave a short trail, and the green phosphor lingers longest
# Three of those - blur, tau ("smudge"/trail length) and aberr - are also live knobs: the
# user scales them with CRT_KNOBS (Ctrl+B / Ctrl+T / Ctrl+R, or the CRT screen dialog),
# and what the shaders get is the level's value times that factor.
CRT_LEVELS = [
    ("subtle", dict(curve=0.03, mask=0.12, scan=0.18, bloom=0.45, grain=0.025, hum=0.015, vignette=0.25,
                    aberr=1.0, blur=0.35, tau=(0.08, 0.12, 0.07))),
    ("normal", dict(curve=0.06, mask=0.22, scan=0.30, bloom=0.70, grain=0.05, hum=0.03, vignette=0.40,
                    aberr=2.0, blur=0.65, tau=(0.12, 0.18, 0.10))),
    ("heavy", dict(curve=0.10, mask=0.35, scan=0.42, bloom=1.00, grain=0.09, hum=0.05, vignette=0.55,
                   aberr=3.2, blur=1.10, tau=(0.18, 0.28, 0.15))),
]
CRT_LEVEL_NAMES = [name for name, _ in CRT_LEVELS]
# The three adjustable CRT knobs: attribute on AsciiRenderer, label, OSD unit and the
# shortcut that raises it. Each is a factor on the CRT_LEVELS value above, 0 = off.
CRT_KNOBS = [
    ("crt_blur", "blur", "px", "Ctrl+B"),
    ("crt_trail", "trail", "s", "Ctrl+T"),
    ("crt_aberr", "aberration", "px", "Ctrl+R"),
]
CRT_KNOB_MAX = 4.0     # x4 the level's value
# What colour the phosphor trail glows as it fades (cycled with Ctrl+Shift+G). "auto"
# keeps whatever colour the picture had - which in the green/amber/mono colour modes is
# already that phosphor - and the rest force one, so a full-colour picture can still smear
# green like an old radar screen. RGB, 0-255.
CRT_TRAIL_TINTS = [
    ("auto", None),
    ("green", (80, 255, 90)),
    ("amber", (255, 180, 0)),
    ("white", (235, 235, 235)),
    ("cyan", (90, 230, 255)),
    ("blue", (90, 130, 255)),
    ("magenta", (255, 100, 220)),
    ("red", (255, 70, 40)),
]
CRT_TINT_NAMES = [name for name, _ in CRT_TRAIL_TINTS]
CRT_KNOB_STEP = 0.25
CRT_BLUR_ASPECT = 0.7  # vertical focus blur, relative to the horizontal one
# A focus blur wider than this (in screen pixels) is done at half resolution: a picture
# that soft has no detail left to lose, and full-resolution taps that far apart are what
# makes the pass expensive on a big screen.
CRT_BLUR_HALF_PX = 1.5
# CRT screen filter on plain video (no display filter): how many scanlines the tube draws
# over the picture - a whole number of them, never closer together than CRT_SCAN_MIN_PX
# screen pixels, so they stay visible instead of turning into moire on a big display.
CRT_VIDEO_LINES = 486
CRT_SCAN_MIN_PX = 4.0

# lavfi filter graphs producing a video stream out of the audio. {W}x{H} is filled in.
VISUALIZERS = [
    ("cqt bars", "showcqt=s={W}x{H}:axis=0:sono_h=0:bar_h={H}:axis_h=0:bar_g=2"),
    ("waveform", "showwaves=s={W}x{H}:mode=cline:rate=30:draw=full:colors=cyan|magenta"),
    ("spectrum", "showspectrum=s={W}x{H}:slide=scroll:color=rainbow:scale=log"),
    ("freq bars", "showfreqs=s={W}x{H}:mode=bar:ascale=log:fscale=log:colors=yellow|red"),
    ("scope", "avectorscope=s={W}x{H}:mode=lissajous_xy:zoom=1.5:draw=line"),
]
VIZ_W, VIZ_H = 640, 360

# Repeat modes, cycled with Shift+L: mpv's loop-playlist / loop-file settings.
REPEAT_MODES = [("off", "no", "no"), ("all", "inf", "no"), ("one", "no", "inf")]

# libmpv render parameter ids (libmpv/render.h) - python-mpv 1.0.x does not wrap the sw ones
MPV_RENDER_PARAM_BLOCK_FOR_TARGET_TIME = 12
MPV_RENDER_PARAM_SW_SIZE = 17
MPV_RENDER_PARAM_SW_FORMAT = 18
MPV_RENDER_PARAM_SW_STRIDE = 19
MPV_RENDER_PARAM_SW_POINTER = 20

# The few raw OpenGL enums the GL widget touches directly (PyQt6 ships no QOpenGLFunctions
# binding, and PyOpenGL would be a whole extra dependency for nine calls).
GL_TRIANGLES = 0x0004
GL_DEPTH_TEST = 0x0B71
GL_CULL_FACE = 0x0B44
GL_BLEND = 0x0BE2
GL_SCISSOR_TEST = 0x0C11
GL_TEXTURE_2D = 0x0DE1
GL_COLOR_BUFFER_BIT = 0x4000
GL_TEXTURE0 = 0x84C0
GL_TEXTURE1 = 0x84C1
GL_RGBA8 = 0x8058
GL_FRAMEBUFFER = 0x8D40
GL_TEXTURE_MAG_FILTER = 0x2800
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_WRAP_S = 0x2802
GL_TEXTURE_WRAP_T = 0x2803
GL_LINEAR = 0x2601
GL_CLAMP_TO_EDGE = 0x812F

# ASCII filter as a fragment shader: one pixel of mpv's (cols x rows) render per character
# cell, mapped onto the glyph atlas and tinted, per screen pixel, on the GPU. This is the
# same arithmetic as AsciiRenderer.analyse() (luminance weights, gamma ramp, the three
# colour modes) - keep the two in sync. The GLSL version line is prepended at runtime,
# because Qt may hand us either a desktop OpenGL or an OpenGL ES context (see
# GLVideoWidget._build_shader).
ASCII_VERT = """
void main() {
    // one triangle that covers the whole framebuffer; no vertex buffer needed
    vec2 v = vec2(gl_VertexID == 1 ? 3.0 : -1.0, gl_VertexID == 2 ? 3.0 : -1.0);
    gl_Position = vec4(v, 0.0, 1.0);
}
"""
ASCII_FRAG = """
uniform sampler2D u_frame;    // mpv's render: one pixel per character cell, row 0 = top
uniform sampler2D u_atlas;    // glyph strip: n glyphs of u_glyph px side by side, white on black
uniform vec2 u_origin;        // top-left of the picture in framebuffer pixels
uniform vec2 u_cell;          // size of one character cell on screen, framebuffer pixels
uniform vec2 u_glyph;         // size of one glyph in the atlas, texels
uniform vec2 u_grid;          // cols, rows (float: PyQt6 cannot set an ivec2 uniform)
uniform float u_fbh;          // framebuffer height (gl_FragCoord counts from the bottom)
uniform float u_nchars;
uniform float u_gamma;
uniform int u_mode;           // 0 colour, 1 raw, 2 phosphor, 3 palette
uniform vec3 u_phosphor;      // tube colour for mode 2 (RGB, 0..1)
uniform int u_pal_off;        // palette for mode 3: first entry in PAL, and how many
uniform int u_pal_n;
out vec4 fragColor;
void main() {
    vec2 p = vec2(gl_FragCoord.x, u_fbh - gl_FragCoord.y) - u_origin;
    vec2 cf = p / u_cell;
    if (any(lessThan(cf, vec2(0.0))) || any(greaterThanEqual(cf, u_grid))) {
        fragColor = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }
    ivec2 cell = ivec2(floor(cf));
    vec3 c = texelFetch(u_frame, cell, 0).rgb;
    float lum = dot(c, vec3(77.0, 151.0, 28.0) / 256.0);
    float idx = floor(pow(lum, u_gamma) * (u_nchars - 1.0) + 0.5);
    vec2 f = fract(cf);
    // stay half a texel inside the glyph so linear filtering never bleeds a neighbour in
    f.x = clamp(f.x, 0.5 / u_glyph.x, 1.0 - 0.5 / u_glyph.x);
    float mask = texture(u_atlas, vec2((idx + f.x) / u_nchars, f.y)).r;
    vec3 col;
    if (u_mode == 0 || u_mode == 3) {
        float mx = max(max(c.r, c.g), c.b);
        vec3 norm = mx > 0.0 ? c / mx : vec3(0.0);
        col = (c * 2.0 + norm * 3.0) / 5.0;
        if (u_mode == 3) col = nearest_pal(col, u_pal_off, u_pal_n);
    } else if (u_mode == 1) {
        col = c;
    } else {
        float t = lum;
        vec3 glow = clamp(0.05 + t * 1.15, 0.0, 1.0) * u_phosphor;
        float hot = pow(clamp((t - 0.7) / 0.3, 0.0, 1.0), 2.0) * 0.85;
        col = glow * (1.0 - hot) + hot;
    }
    fragColor = vec4(mask * col, 1.0);
}
"""


def _glsl_common():
    """GLSL shared by the display-filter shaders: the palettes as one constant table
    (PAL_OFFSETS says where each starts), nearest-colour lookup, and the Bayer matrix."""
    entries, offsets = [], {}
    for name, (_spread, colours) in PALETTES.items():
        offsets[name] = len(entries)
        entries.extend(colours)
    table = ", ".join(f"vec3({r / 255:.4f}, {g / 255:.4f}, {b / 255:.4f})" for r, g, b in entries)
    code = f"const vec3 PAL[{len(entries)}] = vec3[{len(entries)}]({table});\n" + """
vec3 nearest_pal(vec3 c, int off, int n) {
    vec3 best = PAL[off];
    float bd = 1e9;
    for (int i = 0; i < 32; ++i) {
        if (i >= n) break;
        vec3 q = PAL[off + i];
        vec3 d = (c - q) * vec3(0.9, 1.1, 0.8);   // the eye weighs green most, blue least
        float dd = dot(d, d);
        if (dd < bd) { bd = dd; best = q; }
    }
    return best;
}
// Threshold of the 2^k x 2^k Bayer matrix at integer position p, in (0, 1): the matrix
// is built by bit-interleaving (x xor y) and y, finest bit first, which is the same
// recursive matrix AsciiRenderer.bayer_matrix() builds on the CPU.
float bayer(ivec2 p, int k) {
    int v = 0;
    int x = p.x;
    int y = p.y;
    for (int i = 0; i < k; ++i) {
        v = (v << 2) | (((x ^ y) & 1) << 1) | (y & 1);
        x >>= 1;
        y >>= 1;
    }
    return (float(v) + 0.5) / float(1 << (2 * k));
}
"""
    return code, offsets


GLSL_COMMON, PAL_OFFSETS = _glsl_common()

# Bayer 1-bit dithering (FILTERS bayer2/4/8): mpv renders one pixel per dither pixel into
# the small framebuffer, exactly like the ASCII path, and this shader thresholds each of
# them against the Bayer matrix. Colour modes: colour = one bit per channel (8 colours),
# raw = plain black and white, phosphor = black and the tube colour, palette = the
# dithered colour snapped to the nearest palette entry.
BAYER_FRAG = """
uniform sampler2D u_frame;    // mpv's render: one pixel per dither pixel, row 0 = top
uniform vec2 u_origin;
uniform vec2 u_cell;          // size of one dither pixel on screen, framebuffer pixels
uniform vec2 u_grid;          // cols, rows
uniform float u_fbh;
uniform float u_gamma;
uniform int u_mode;           // 0 rgb, 1 black/white, 2 phosphor, 3 palette
uniform vec3 u_phosphor;
uniform int u_order;          // 1, 2, 3 -> 2x2, 4x4, 8x8 matrix
uniform float u_spread;
uniform int u_pal_off;
uniform int u_pal_n;
out vec4 fragColor;
void main() {
    vec2 p = vec2(gl_FragCoord.x, u_fbh - gl_FragCoord.y) - u_origin;
    vec2 cf = p / u_cell;
    if (any(lessThan(cf, vec2(0.0))) || any(greaterThanEqual(cf, u_grid))) {
        fragColor = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }
    ivec2 cell = ivec2(floor(cf));
    vec3 c = texelFetch(u_frame, cell, 0).rgb;
    float t = bayer(cell, u_order);
    vec3 col;
    if (u_mode == 0) {
        col = step(vec3(t), pow(c, vec3(u_gamma)));
    } else if (u_mode == 3) {
        col = nearest_pal(clamp(c + (t - 0.5) * u_spread, 0.0, 1.0), u_pal_off, u_pal_n);
    } else {
        float lum = pow(dot(c, vec3(77.0, 151.0, 28.0) / 256.0), u_gamma);
        col = (u_mode == 1 ? vec3(1.0) : u_phosphor) * step(t, lum);
    }
    fragColor = vec4(col, 1.0);
}
"""

# Vector display (FILTERS vector), two passes. VECTOR_EDGE_FRAG runs a Sobel edge detector
# over mpv's small render (one texel per pixel of the vector grid) and writes the beam
# colour times the edge strength (alpha = strength) into a same-sized framebuffer;
# VECTOR_FRAG then draws that on screen, bilinearly upscaled so the traces are smooth
# lines, with a white-hot core and a soft halo like the beam of a vector monitor. Colour
# modes: phosphor = the tube colour, colour = the picture's own hue at full beam brightness
# (a colour vector monitor like Tempest's), raw = a dimmer version of that, palette =
# that hue snapped to the palette.
VECTOR_EDGE_FRAG = """
uniform sampler2D u_frame;
uniform vec2 u_grid;
uniform int u_mode;           // 0 colour, 1 raw, 2 phosphor, 3 palette
uniform vec3 u_phosphor;
uniform int u_pal_off;
uniform int u_pal_n;
uniform float u_lo;
uniform float u_hi;
out vec4 fragColor;
float L(ivec2 p) {
    p = clamp(p, ivec2(0), ivec2(u_grid) - 1);
    return dot(texelFetch(u_frame, p, 0).rgb, vec3(0.299, 0.587, 0.114));
}
void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    float gx = (L(p + ivec2(1, -1)) + 2.0 * L(p + ivec2(1, 0)) + L(p + ivec2(1, 1)))
             - (L(p + ivec2(-1, -1)) + 2.0 * L(p + ivec2(-1, 0)) + L(p + ivec2(-1, 1)));
    float gy = (L(p + ivec2(-1, 1)) + 2.0 * L(p + ivec2(0, 1)) + L(p + ivec2(1, 1)))
             - (L(p + ivec2(-1, -1)) + 2.0 * L(p + ivec2(0, -1)) + L(p + ivec2(1, -1)));
    float e = smoothstep(u_lo, u_hi, length(vec2(gx, gy)) * 0.25);
    vec3 c = texelFetch(u_frame, clamp(p, ivec2(0), ivec2(u_grid) - 1), 0).rgb;
    vec3 tint;
    if (u_mode == 2) {
        tint = u_phosphor;
    } else {
        float mx = max(max(c.r, c.g), c.b);
        vec3 norm = mx > 0.02 ? c / mx : vec3(1.0);
        if (u_mode == 0) tint = norm;
        else if (u_mode == 1) tint = mix(norm, c, 0.5);
        else tint = nearest_pal(norm, u_pal_off, u_pal_n);
    }
    fragColor = vec4(tint * e, e);
}
"""
VECTOR_FRAG = """
uniform sampler2D u_edge;     // beam traces at grid resolution (rgb = colour * strength, a = strength)
uniform vec2 u_origin;
uniform vec2 u_cell;          // size of one grid pixel on screen, framebuffer pixels
uniform vec2 u_grid;
uniform float u_fbh;
uniform float u_glow;
out vec4 fragColor;
void main() {
    vec2 p = vec2(gl_FragCoord.x, u_fbh - gl_FragCoord.y) - u_origin;
    vec2 cf = p / u_cell;
    if (any(lessThan(cf, vec2(0.0))) || any(greaterThanEqual(cf, u_grid))) {
        fragColor = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }
    vec2 uv = cf / u_grid;
    vec2 tx = 1.0 / u_grid;
    vec4 line = texture(u_edge, uv);
    vec3 glow = vec3(0.0);
    float wsum = 0.0;
    for (int j = -2; j <= 2; ++j) {
        for (int i = -2; i <= 2; ++i) {
            float w = exp(-0.4 * float(i * i + j * j));
            glow += texture(u_edge, uv + vec2(float(i), float(j)) * tx).rgb * w;
            wsum += w;
        }
    }
    vec3 col = line.rgb * 1.1 + vec3(0.35 * line.a * line.a) + glow / wsum * u_glow;
    fragColor = vec4(min(col, vec3(1.0)), 1.0);
}
"""

# Colour modes without a display filter (see COLOR_MODES): one pass over mpv's picture,
# so an ordinary video can run as a green/amber/white phosphor tube or through one of the
# retro palettes. `color` never gets here (full colour is the picture as it is); `raw` is
# plain greyscale - the black and white TV; the phosphor modes use the same glow curve as
# the ASCII shader; the palettes snap every pixel to the nearest entry after an 8x8 Bayer
# dither, so a photographic picture bands the way it would on that hardware.
VIDEO_COLOR_FRAG = """
uniform sampler2D u_frame;    // mpv's picture, framebuffer sized
uniform vec2 u_res;
uniform int u_mode;           // 1 greyscale, 2 phosphor, 3 palette
uniform vec3 u_phosphor;      // tube colour for mode 2 (RGB, 0..1)
uniform int u_pal_off;        // palette for mode 3: first entry in PAL, and how many
uniform int u_pal_n;
uniform float u_spread;       // how far the dither pushes a colour before it snaps
uniform float u_dither_px;    // size of one dither cell, framebuffer pixels
out vec4 fragColor;
void main() {
    vec2 uv = gl_FragCoord.xy / u_res;
    vec3 c = texture(u_frame, uv).rgb;
    float lum = dot(c, vec3(77.0, 151.0, 28.0) / 256.0);
    vec3 col;
    if (u_mode == 1) {
        col = vec3(lum);
    } else if (u_mode == 2) {
        // the tube colour glows through the midtones, the brightest bits blow out to white.
        // No lift off black here (unlike the ASCII shader, where it only ever lands inside
        // a glyph): the letterbox around the picture has to stay properly black.
        vec3 glow = clamp(lum * 1.15, 0.0, 1.0) * u_phosphor;
        float hot = pow(clamp((lum - 0.7) / 0.3, 0.0, 1.0), 2.0) * 0.85;
        col = glow * (1.0 - hot) + hot;
    } else {
        float t = bayer(ivec2(gl_FragCoord.xy / u_dither_px), 3);
        col = nearest_pal(clamp(c + (t - 0.5) * u_spread, 0.0, 1.0), u_pal_off, u_pal_n);
    }
    fragColor = vec4(col, 1.0);
}
"""

# CRT screen filter (see CRT_LEVELS): a few more passes run after the picture is drawn -
# either by one of the display-filter shaders above or, with no filter on, by mpv itself.
# That picture goes to an off-screen framebuffer instead of the screen; then
#   1. CRT_PERSIST_FRAG folds it into a persistence buffer (phosphor afterglow: each pixel
#      is the brighter of the new frame and the decayed previous one, so bright, fast
#      moving things leave a short trail - the "smudge"),
#   2. CRT_FOCUS_FRAG blurs that a little (two passes, horizontal then vertical): the
#      electron beam's spot is not a sharp pixel. Skipped when the blur knob is at 0,
#   3. CRT_BLUR_FRAG blurs a highlight-weighted, half-size copy of it (two passes again)
#      for the bloom,
#   4. CRT_FRAG composes the screen: barrel distortion with a rounded tube face, colour
#      convergence error, scanlines, aperture-grille shadow mask, bloom, grain, a faint
#      rolling hum bar and a vignette.
# All of them draw the same full-screen triangle as ASCII_VERT.
CRT_PERSIST_FRAG = """
uniform sampler2D u_cur;      // this frame's ASCII picture
uniform sampler2D u_prev;     // last frame's persistence buffer
uniform vec2 u_res;
uniform vec3 u_decay;         // per-channel multiplier for this frame's time step
uniform float u_floor;        // taken off every frame so faint trails reach zero in 8 bits instead of sticking
uniform float u_dtn;          // time step in 60ths of a second
uniform vec3 u_tint;          // what colour the trail glows as it fades
uniform float u_tint_mix;     // 0 = whatever colour the picture had (CRT_TRAIL_TINTS "auto")
out vec4 fragColor;
void main() {
    vec2 uv = gl_FragCoord.xy / u_res;
    vec3 c = texture(u_cur, uv).rgb;
    vec3 p = texture(u_prev, uv).rgb;
    // brightly lit phosphor keeps glowing, dim areas let go quickly
    float keep = pow(mix(0.8, 1.0, smoothstep(0.15, 0.7, max(max(p.r, p.g), p.b))), u_dtn);
    vec3 kept = p * u_decay * keep - u_floor;
    // a tinted trail glows in the phosphor's own colour, as bright as the beam left it
    if (u_tint_mix > 0.0) kept = mix(kept, max(max(kept.r, kept.g), kept.b) * u_tint, u_tint_mix);
    fragColor = vec4(max(c, kept), 1.0);
}
"""
CRT_FOCUS_FRAG = """
uniform sampler2D u_src;
uniform vec2 u_res;           // size of the target
uniform vec2 u_dir;           // a one-pixel step along the blur axis, in texture coordinates
uniform float u_sigma;        // beam spot size along that axis, in pixels
out vec4 fragColor;
void main() {
    vec2 uv = gl_FragCoord.xy / u_res;
    float s = max(u_sigma, 0.05);
    // taps half a sigma apart (never closer than a pixel), so a wide spot stays cheap
    float tap = max(1.0, s * 0.5);   // not `step`: that is a GLSL built-in
    vec3 acc = texture(u_src, uv).rgb;
    float wsum = 1.0;
    for (int i = 1; i <= 4; ++i) {
        float d = float(i) * tap;
        float w = exp(-0.5 * d * d / (s * s));
        acc += (texture(u_src, uv + u_dir * d).rgb + texture(u_src, uv - u_dir * d).rgb) * w;
        wsum += 2.0 * w;
    }
    fragColor = vec4(acc / wsum, 1.0);
}
"""
CRT_BLUR_FRAG = """
uniform sampler2D u_src;
uniform vec2 u_res;           // size of the target
uniform vec2 u_dir;           // one tap step, in source texture coordinates
uniform int u_prep;           // 1 on the first pass: weight towards the highlights
out vec4 fragColor;
const float W[7] = float[7](0.137023, 0.129618, 0.109719, 0.083109, 0.056332, 0.034167, 0.018544);
void main() {
    vec2 uv = gl_FragCoord.xy / u_res;
    vec3 acc = vec3(0.0);
    for (int i = -6; i <= 6; ++i) {
        vec3 s = texture(u_src, uv + u_dir * float(i)).rgb;
        if (u_prep == 1) s *= s;
        acc += s * W[i < 0 ? -i : i];
    }
    fragColor = vec4(acc, 1.0);
}
"""
CRT_FRAG = """
uniform sampler2D u_scene;    // the ASCII picture with afterglow, framebuffer-sized
uniform sampler2D u_bloom;    // the same, blurred and highlight-weighted, half size
uniform vec2 u_res;           // framebuffer size
uniform vec4 u_rect;          // picture rect in framebuffer px: x, y (bottom edge), w, h
uniform float u_curve;        // barrel distortion
uniform float u_corner;       // corner radius of the tube face, px
uniform float u_mask;         // shadow mask (aperture grille) strength
uniform float u_mask_px;      // width of one grille stripe, px
uniform float u_scan;         // scanline strength
uniform float u_scan_period;  // scanline spacing, px (a whole number of lines per character row)
uniform float u_bloom_amt;
uniform float u_grain;
uniform float u_hum;          // strength of the slow brightness bar rolling down the tube
uniform float u_vignette;
uniform float u_aberr;        // colour convergence error at the edge of the picture, px
uniform float u_time;
uniform int u_seed;
out vec4 fragColor;

float hash(uvec2 v, uint t) {
    uint h = v.x * 1597334677u ^ v.y * 3812015801u ^ t * 2798796415u;
    h = h * 747796405u + 2891336453u;
    h = (h >> 16u) ^ h;
    h *= 0x7feb352du;
    h = (h >> 15u) ^ h;
    return float(h & 0x00ffffffu) / 16777216.0;
}

void main() {
    vec2 p = gl_FragCoord.xy;
    vec2 n = (p - u_rect.xy) / u_rect.zw * 2.0 - 1.0;            // -1..1 across the picture
    // barrel distortion: the further out on the glass, the further out the source is read,
    // so straight edges bow inwards and the corners fall off the tube face
    vec2 ns = n * (1.0 + u_curve * vec2(n.y * n.y, n.x * n.x));
    // rounded tube face, anti-aliased over about a pixel
    vec2 d = (abs(ns) - 1.0) * u_rect.zw * 0.5 + u_corner;       // px outside the straight edges
    float dist = length(max(d, vec2(0.0))) + min(max(d.x, d.y), 0.0) - u_corner;
    float face = 1.0 - smoothstep(-0.75, 0.75, dist);
    if (face <= 0.0) {
        fragColor = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }
    vec2 src = u_rect.xy + (ns * 0.5 + 0.5) * u_rect.zw;         // where on the picture we are, px
    vec2 uv = src / u_res;
    // convergence error: a little of it everywhere, much more towards the edges
    vec2 ab = ns * (0.25 + 0.75 * dot(ns, ns)) * u_aberr / u_res;
    vec3 col = vec3(texture(u_scene, uv + ab).r, texture(u_scene, uv).g, texture(u_scene, uv - ab).b);
    float lum = dot(col, vec3(0.299, 0.587, 0.114));
    // scanlines ride on the (curved) picture; a bright beam is fatter and fills the gaps
    float s = 0.5 + 0.5 * cos(6.2831853 * (src.y - u_rect.y) / u_scan_period);
    float scan = (1.0 - u_scan * (1.0 - s) * (1.0 - 0.6 * lum)) / (1.0 - 0.35 * u_scan);
    // aperture grille: vertical R, G, B stripes fixed to the glass. Both the grille and
    // the scanlines above are gained back up so the picture stays about as bright as
    // without them - the brightest bits then blow out to white like a real tube.
    int stripe = int(mod(floor(p.x / u_mask_px), 3.0));
    vec3 sel = vec3(stripe == 0 ? 1.0 : 0.0, stripe == 1 ? 1.0 : 0.0, stripe == 2 ? 1.0 : 0.0);
    vec3 mask = mix(vec3(1.0), sel, u_mask) * (1.0 + 0.6 * u_mask);
    col = col * scan * mask + texture(u_bloom, uv).rgb * u_bloom_amt;
    // what overshoots white blows out softly, keeping its hue rather than clipping per channel
    float mx = max(col.r, max(col.g, col.b));
    if (mx > 1.0) col = mix(col / mx, vec3(1.0), clamp((mx - 1.0) * 0.6, 0.0, 1.0));
    // grain: fresh per pixel and per frame, a bit stronger where the phosphor is lit
    col += (hash(uvec2(p), uint(u_seed)) - 0.5) * u_grain * (0.3 + lum);
    // a faint hum bar drifting down the tube every few seconds
    float bar = pow(0.5 + 0.5 * sin(6.2831853 * (ns.y * 0.5 + 0.5 + u_time * 0.12)), 6.0);
    col *= 1.0 - u_hum * bar;
    // vignette; the glass itself is never quite black; and the soft edge of the tube face
    col *= 1.0 - u_vignette * 0.35 * dot(ns, ns);
    col += vec3(0.010, 0.011, 0.013) * (1.0 - 0.3 * dot(ns, ns));
    fragColor = vec4(col * face, 1.0);
}
"""


def fmt_time(secs):
    if secs is None or secs != secs or secs < 0:
        return "--:--"
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fit_rect(aspect, width, height):
    """Largest (w, h) with given aspect (w/h) that fits in width x height."""
    if aspect <= 0 or width <= 0 or height <= 0:
        return max(1, width), max(1, height)
    w = width
    h = int(round(w / aspect))
    if h > height:
        h = height
        w = int(round(h * aspect))
    return max(1, w), max(1, h)


# --------------------------------------------------------------------------------------
# libmpv wrapper
# --------------------------------------------------------------------------------------

class Engine(QObject):
    """Owns the mpv instance and its render context (OpenGL or software).

    python-mpv dispatches property/event callbacks (observe_property, file-loaded, log
    messages, ...) from its own internal Python `threading.Thread`, so those are safe to
    turn into ordinary Qt signals - PyQt delivers a cross-thread signal fine from a real
    Python thread. The render context's update_cb is different: libmpv invokes it directly
    from its own native render thread, which never goes through Python's threading module,
    and PyQt6 cannot reliably deliver a signal emitted from there (it silently vanishes).
    So that callback only flips a flag and pokes a tiny Python helper thread, whose whole
    job is to wait for that poke and re-emit it as the `frame_ready` Qt signal - a real
    Python thread, so queued delivery works. The GUI thread then redraws straight away
    instead of noticing the new frame on a poll timer, which keeps frame pacing even.

    The render context itself is created later by the video widget, because the OpenGL
    one has to be made while the widget's GL context is current (init_render_gl), and
    freed the same way (free_render_ctx)."""
    prop_changed = pyqtSignal(str, object)
    file_loaded = pyqtSignal()
    file_ended = pyqtSignal(str)
    log_message = pyqtSignal(str, str, str)
    frame_ready = pyqtSignal()

    OBSERVED = ["time-pos", "duration", "pause", "speed", "volume", "mute", "aid", "sid",
                "track-list", "media-title", "sub-text", "eof-reached", "video-out-params",
                "playlist-pos", "playlist-count", "playlist", "loop-playlist", "loop-file",
                "core-idle", "seeking"]

    @staticmethod
    def ytdl_raw_options(cookies_from_browser=None, client=None, extra=None):
        """mpv's --ytdl-raw-options value (a key=value list) for the yt-dlp knobs we expose,
        or None if there is nothing to pass. Entries are comma separated, so a value that
        contains a comma itself - `--ytdl-client android_vr,tv` - is given with mpv's
        length-prefixed quoting (`key=%12%some,value`) instead."""
        parts = []
        for key, value in (("cookies-from-browser", cookies_from_browser),
                           ("extractor-args", f"youtube:player_client={client}" if client else None)):
            if value:
                parts.append(f"{key}=%{len(value)}%{value}" if "," in value else f"{key}={value}")
        if extra:
            parts.append(extra)
        return ",".join(parts) or None

    def __init__(self, hwdec=None, gl=True, ytdl_format=None, ytdl_raw=None):
        super().__init__()
        # Qt resets the process locale when QApplication starts; libmpv insists on LC_NUMERIC=C
        locale.setlocale(locale.LC_NUMERIC, "C")
        # YouTube & co: mpv's ytdl hook shells out to yt-dlp (or youtube-dl) to resolve the
        # page URL into media streams. Only switch it on when one of them is installed;
        # the GUI tells the user what to install otherwise (see MainWindow.open_path).
        self.ytdl_tool = shutil.which("yt-dlp") or shutil.which("youtube-dl")
        ytdl_opts = {}
        if self.ytdl_tool:
            ytdl_opts = {"ytdl": True, "ytdl_format": ytdl_format or "bestvideo[height<=?1080]+bestaudio/best",
                         "script_opts": f"ytdl_hook-ytdl_path={self.ytdl_tool}"}
            if ytdl_raw:
                ytdl_opts["ytdl_raw_options"] = ytdl_raw
        # With the GPU renderer mpv can take decoded frames straight from the hardware
        # decoder (nvdec/vaapi interop), so allow the direct methods; the software renderer
        # can only use a copy-back decoder.
        self.hwdec = hwdec or ("auto-safe" if gl else "auto-copy")
        self.m = mpv.MPV(
            vo="libmpv", hwdec=self.hwdec, keep_open="yes", keepaspect="no",
            osc=False, input_default_bindings=False, input_vo_keyboard=False,
            osd_level=0, audio_display="no", sub_auto="fuzzy", idle="yes",
            log_handler=self._on_log, loglevel="warn", **(ytdl_opts or {"ytdl": False}),
        )
        # Transparent pixels (a webm/apng with alpha): mpv's default is a grey checkerboard
        # behind them, which the ASCII filter turns into a wall of grey glyphs. Plain black
        # instead (option renamed in mpv 0.38; older builds spell it --alpha=no). The audio
        # visualisers used to hit this too; they are made opaque in their filter graph now
        # (see MainWindow._apply_visualizer).
        try:
            self.m["background"] = "color"
        except Exception:
            try:
                self.m["alpha"] = "no"
            except Exception:
                pass
        self.ctx = None
        self.gl = False
        self._gpa = None          # keeps the ctypes get_proc_address trampoline alive
        self._pending = False
        self._wake = threading.Event()
        self._stop = False
        for name in self.OBSERVED:
            self.m.observe_property(name, self._on_prop)
        self.m.event_callback("file-loaded")(self._on_file_loaded)
        self.m.event_callback("end-file")(self._on_end_file)
        self._buf = None
        self._fmt = ctypes.c_char_p(b"bgr0")
        self._block = ctypes.c_int(0)
        self._pump = threading.Thread(target=self._pump_frames, name="asciiplay-frames", daemon=True)
        self._pump.start()

    # ---- render context ----
    def init_render_sw(self):
        try:
            self.ctx = mpv.MpvRenderContext(self.m, "sw")
        except Exception as exc:  # pragma: no cover - old libmpv
            raise RuntimeError("libmpv is too old for software rendering (need mpv >= 0.33): %s" % exc)
        self.ctx.update_cb = self._on_update
        self.gl = False

    def init_render_gl(self, get_proc_address):
        """Create the OpenGL render context. The target GL context must be current, and
        every later render/free call has to happen on this same thread with it current."""
        self._gpa = mpv.MpvGlGetProcAddressFn(lambda _ctx, name: get_proc_address(name))
        self.ctx = mpv.MpvRenderContext(self.m, "opengl", opengl_init_params={"get_proc_address": self._gpa})
        self.ctx.update_cb = self._on_update
        self.gl = True
        # vo_gpu scaler knobs (the sw renderer scales with swscale instead): the ASCII
        # filter asks for one pixel per character cell, a 5-10x downscale, so widen the
        # filter kernel to match instead of aliasing.
        self.set("correct-downscaling", True)
        # Intermediate render targets as 16-bit unorm instead of mpv's default 16-bit float.
        # With hardware decoding through NVDEC (even the copy-back variant) and the float
        # FBO, frames come out with bands of line noise across their lower part - the same
        # picture in a different memory layout bleeding through, i.e. the CUDA decoder and
        # the GL float textures aliasing in the driver (seen with NVIDIA 595.x). rgba16
        # has the same precision for SDR video and is what mpv itself uses where float
        # FBOs are unavailable, and it renders clean here in every mode tested.
        self.set("fbo-format", "rgba16")

    def free_render_ctx(self):
        """For a GL context, call with that GL context current."""
        ctx, self.ctx = self.ctx, None
        if ctx is None:
            return
        try:
            ctx.update_cb = None
        except Exception:
            pass
        try:
            ctx.free()
        except Exception:
            pass

    # ---- callbacks from mpv threads ----
    def _on_update(self):
        # Runs on libmpv's own native render thread - flip a flag, poke the pump, return.
        # No Qt or Python object graph traversal here (see the class docstring for why).
        self._pending = True
        self._wake.set()

    def _pump_frames(self):
        while True:
            self._wake.wait()
            self._wake.clear()
            if self._stop:
                return
            self.frame_ready.emit()

    def _on_prop(self, name, value):
        self.prop_changed.emit(name, value)

    def _on_file_loaded(self, _event):
        self.file_loaded.emit()

    def _on_end_file(self, event):
        reason = ""
        try:
            d = event.as_dict() if hasattr(event, "as_dict") else {}
            reason = str(d.get("reason", d.get("event", {}).get("reason", "")))
        except Exception:
            pass
        self.file_ended.emit(reason)

    def _on_log(self, level, prefix, text):
        self.log_message.emit(level, prefix, text.rstrip())

    # ---- render ----
    def take_update(self):
        """GUI thread: acknowledge a pending update. Returns True if mpv has a new frame."""
        if not self._pending or self.ctx is None:
            return False
        self._pending = False
        return self.ctx.update()

    def render_sw(self, w, h):
        """Software: render the current frame into a (h, w, 4) BGRX uint8 array (reused between calls)."""
        w, h = max(1, int(w)), max(1, int(h))
        if self._buf is None or self._buf.shape[0] != h or self._buf.shape[1] != w:
            self._buf = np.zeros((h, w, 4), np.uint8)
        buf = self._buf
        size = (ctypes.c_int * 2)(w, h)
        stride = ctypes.c_size_t(buf.strides[0])
        params = (mpv.MpvRenderParam * 6)()
        params[0].type_id, params[0].data = MPV_RENDER_PARAM_SW_SIZE, ctypes.addressof(size)
        params[1].type_id, params[1].data = MPV_RENDER_PARAM_SW_FORMAT, ctypes.cast(self._fmt, ctypes.c_void_p).value
        params[2].type_id, params[2].data = MPV_RENDER_PARAM_SW_STRIDE, ctypes.addressof(stride)
        params[3].type_id, params[3].data = MPV_RENDER_PARAM_SW_POINTER, buf.ctypes.data
        params[4].type_id, params[4].data = MPV_RENDER_PARAM_BLOCK_FOR_TARGET_TIME, ctypes.addressof(self._block)
        params[5].type_id = 0
        mpv._mpv_render_context_render(self.ctx.handle, params)
        return buf

    def render_gl(self, fbo, w, h, flip_y):
        """OpenGL: render the current frame into framebuffer object `fbo` of size w x h.
        The widget's GL context must be current. Redraws the last frame if there is no new one."""
        self.ctx.render(opengl_fbo={"fbo": int(fbo), "w": max(1, int(w)), "h": max(1, int(h)),
                                    "internal_format": GL_RGBA8},
                        flip_y=bool(flip_y), block_for_target_time=False)

    def report_swap(self):
        if self.ctx is not None and self.gl:
            try:
                self.ctx.report_swap()
            except Exception:
                pass

    # ---- helpers ----
    def prop(self, name, default=None):
        # python-mpv's __getitem__ only round-trips "options/*"-style properties; read-only
        # computed properties (track-list, time-pos, sub-text, video-out-params, ...) must go
        # through attribute access instead, so use that uniformly.
        try:
            v = getattr(self.m, name.replace("-", "_"))
            return default if v is None else v
        except Exception:
            return default

    def set(self, name, value):
        try:
            setattr(self.m, name.replace("-", "_"), value)
        except Exception as exc:
            self.log_message.emit("warn", "gui", f"cannot set {name}={value!r}: {exc}")

    def command(self, *args):
        try:
            self.m.command(*args)
        except Exception as exc:
            self.log_message.emit("warn", "gui", f"command {args[0]} failed: {exc}")

    def tracks(self, kind):
        out = []
        for t in self.prop("track-list", []) or []:
            if t.get("type") == kind:
                out.append(t)
        return out

    def has_real_video(self):
        for t in self.tracks("video"):
            if not t.get("albumart"):
                return True
        return False

    def display_aspect(self):
        """Aspect ratio (w/h) of the picture mpv currently outputs, rotation applied."""
        p = self.prop("video-out-params") or self.prop("video-params") or {}
        dw, dh = p.get("dw") or p.get("w") or 0, p.get("dh") or p.get("h") or 0
        if not dw or not dh:
            return 16 / 9
        if p.get("rotate", 0) in (90, 270):
            dw, dh = dh, dw
        return dw / dh

    def shutdown(self):
        """The GL widget must already have freed the render context (with its context current)."""
        self._stop = True
        self._wake.set()
        self.free_render_ctx()
        try:
            self.m.terminate()
        except Exception:
            pass


# --------------------------------------------------------------------------------------
# ASCII conversion
# --------------------------------------------------------------------------------------

class AsciiRenderer:
    """Turns a small BGRX frame (one pixel per character cell) into a picture of coloured text.

    mpv is asked to render exactly one pixel per character cell (its own software scaler
    does the downsampling from the real video resolution, which is both faster and better
    quality than box-averaging in Python). Converting that into coloured glyphs is a tight
    loop running at up to 60fps, so the scratch buffers it needs are allocated once per
    grid size and reused every frame instead of allocating fresh multi-megabyte arrays each
    call - that allocation churn, plus a numpy broadcasting pattern that turned out to
    vectorise poorly, was the main cost of fullscreen ASCII playback."""

    def __init__(self, font_family, font_px=12, ramp="classic", color_mode="color", gamma=0.85):
        self.font_family = font_family
        self.font_px = font_px
        self.ramp_name = ramp
        self.color_mode = color_mode
        self.gamma = gamma
        self._atlas_key = None
        self.cell_w = self.cell_h = 1
        self.font = None
        self.last_chars = None  # (rows, cols) char indices of the last frame, for text export
        self.last_colors = None
        self._buf_key = None
        self._mask_buf = self._mask_buf_4d = self._tmp_buf = self._out_buf = None
        # Resolution divider: 1 = one character cell per available cell-sized area (full
        # detail), 2/4 = half/quarter as many columns and rows in each direction, i.e. a
        # quarter/sixteenth as many cells total. Cuts the render/composite cost by roughly
        # that same factor (the biggest lever for fullscreen performance) and gives a
        # chunkier, lower-detail look; the smaller result is then stretched back up to fill
        # the display area. Applies to audio files too since they render through this same
        # path via the ASCII visualiser.
        self.res_divider = 1
        # Which display filter is drawn while the filter is on (see FILTERS); the on/off
        # state itself lives on the video widget. The Bayer and vector filters work on a
        # pixel grid instead of character cells: one grid pixel is pixel_px * res_divider
        # screen pixels.
        self.filter = "ascii"
        self.pixel_px = 2
        # CRT screen filter on top of the picture, with or without a display filter under
        # it (GL renderer only; see CRT_LEVELS). Kept here with the other display settings
        # so it survives a renderer swap. The three knobs scale the level's blur, phosphor
        # trail and colour convergence error; 1.0 = exactly what the level asks for.
        self.crt_on = False
        self.crt_level = 1
        self.crt_blur = 1.0
        self.crt_trail = 1.0
        self.crt_aberr = 1.0
        self.crt_tint = 0      # index into CRT_TRAIL_TINTS; 0 = auto (the picture's own colours)
        self._pal_cache = {}
        self._pix_key = None
        self._pix_out = self._bayer_t = None
        self._ensure_atlas()

    # ---- glyph atlas ----
    def _ensure_atlas(self):
        key = (self.font_family, self.font_px, self.ramp_name)
        if key == self._atlas_key:
            return
        font = QFont(self.font_family)
        font.setPixelSize(self.font_px)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        fm = QFontMetrics(font)
        cw = max(1, fm.horizontalAdvance("M"))
        ch = max(1, fm.height())

        def render_strip(chars):
            """Draw every glyph, centred, into a (ch, cw)-per-cell horizontal strip.
            Returns the QImage plus a (ch, n, cw) uint8 view onto its pixels."""
            n = len(chars)
            img = QImage(cw * n, ch, QImage.Format.Format_Grayscale8)
            img.fill(0)
            p = QPainter(img)
            p.setFont(font)
            p.setPen(QColor(255, 255, 255))
            for i, c in enumerate(chars):
                p.drawText(QRect(i * cw, 0, cw, ch), Qt.AlignmentFlag.AlignCenter, c)
            p.end()
            ptr = img.constBits()
            ptr.setsize(img.sizeInBytes())
            a = np.frombuffer(ptr, np.uint8).reshape(ch, img.bytesPerLine())[:, :cw * n]
            return img, a.reshape(ch, n, cw)

        # The glyphs in each CHAR_RAMP are hand-ordered light -> dark, but how much ink a
        # given glyph actually lays down depends on the font that's in use (metrics, weight,
        # how it centres in the cell). Re-sort the ramp by measured coverage in *this* font
        # so it is strictly monotonic: if any glyph covered less than the one before it, a
        # smooth luminance gradient in the video would step backwards there and show up as a
        # dark band. argsort is stable, so equal-coverage glyphs keep their authored order.
        base = CHAR_RAMPS[self.ramp_name]
        _probe_img, probe = render_strip(base)
        order = np.argsort(probe.mean(axis=(0, 2)), kind="stable")
        chars = "".join(base[i] for i in order)
        n = len(chars)

        img, strip = render_strip(chars)
        self.atlas = strip.transpose(1, 0, 2).astype(np.uint16)  # (n, ch, cw)
        self.atlas_image = img  # the same strip as a QImage, for uploading as a GL texture
        self.chars = chars
        self.font = font
        self.cell_w, self.cell_h = cw, ch
        lum = np.linspace(0, 1, 256) ** self.gamma
        self.lut = np.clip(np.round(lum * (n - 1)), 0, n - 1).astype(np.intp)
        self._atlas_key = key

    @property
    def atlas_key(self):
        """Changes whenever the glyph atlas is rebuilt (font size or character set)."""
        return self._atlas_key

    def set_font_px(self, px):
        self.font_px = max(6, min(48, int(px)))
        self._ensure_atlas()

    def set_ramp(self, name):
        self.ramp_name = name
        self._ensure_atlas()

    def grid(self, width_px, height_px):
        """Number of character cells that fit in the area, after the resolution divider."""
        d = self.res_divider
        return max(1, width_px // (self.cell_w * d)), max(1, height_px // (self.cell_h * d))

    # ---- pixel grid (Bayer / vector filters) ----
    def set_pixel_px(self, px):
        self.pixel_px = max(1, min(16, int(px)))

    def pixel_size(self):
        """Side of one dither/vector grid pixel in (logical) screen pixels."""
        return self.pixel_px * self.res_divider

    def pixel_grid(self, width_px, height_px):
        """Number of grid pixels that fit in the area for the Bayer and vector filters."""
        s = self.pixel_size()
        return max(1, width_px // s), max(1, height_px // s)

    @property
    def is_ascii(self):
        return self.filter == "ascii"

    # ---- palettes ----
    def palette_bgr(self, mode):
        """The pal* colour mode's colours as a (n, 3) float32 array, BGR, 0..1."""
        if mode not in self._pal_cache:
            cols = np.array(PALETTES[mode][1], np.float32)[:, ::-1] / 255.0
            self._pal_cache[mode] = np.ascontiguousarray(cols)
        return self._pal_cache[mode]

    def nearest_palette(self, col, mode):
        """col: (..., 3) float32 BGR 0..1 -> the nearest palette colour per pixel, same shape
        and range. The CPU twin of nearest_pal() in the shaders (same channel weights)."""
        pal = self.palette_bgr(mode)
        w = np.array([0.8, 1.1, 0.9], np.float32)          # BGR order of the shader's RGB weights
        best = np.full(col.shape[:-1], np.inf, np.float32)
        idx = np.zeros(col.shape[:-1], np.intp)
        for i, q in enumerate(pal):
            d = (((col - q) * w) ** 2).sum(axis=-1)
            closer = d < best
            best[closer] = d[closer]
            idx[closer] = i
        return pal[idx]

    @staticmethod
    def bayer_matrix(order):
        """Thresholds of the 2^order square Bayer matrix, in (0, 1), row-major (y, x)."""
        m = np.array([[0, 2], [3, 1]], np.int32)
        for _ in range(order - 1):
            m = np.block([[4 * m, 4 * m + 2], [4 * m + 3, 4 * m + 1]])
        n = m.shape[0]
        return (m.astype(np.float32) + 0.5) / float(n * n)

    def _ensure_pix_bufs(self, rows, cols, order):
        key = (rows, cols, order)
        if key == self._pix_key:
            return
        self._pix_out = np.empty((rows, cols, 4), np.uint8)
        self._pix_out[..., 3] = 0
        if order:
            m = self.bayer_matrix(order)
            n = m.shape[0]
            self._bayer_t = m[np.arange(rows)[:, None] % n, np.arange(cols)[None, :] % n]
        self._pix_key = key

    def _ensure_bufs(self, rows, cols):
        key = (rows, cols, self.cell_w, self.cell_h)
        if key == self._buf_key:
            return
        H, W = rows * self.cell_h, cols * self.cell_w
        self._mask_buf = np.empty((H, W), np.uint16)
        self._mask_buf_4d = self._mask_buf.reshape(rows, self.cell_h, cols, self.cell_w)
        self._tmp_buf = np.empty((H, W), np.uint16)
        self._out_buf = np.empty((H, W, 4), np.uint8)
        self._out_buf[..., 3] = 0  # alpha is always unused; set once, never touched again
        self._buf_key = key

    # ---- conversion ----
    def analyse(self, frame):
        """frame: (rows, cols, 4) BGRX uint8, one pixel per cell -> (char indices, BGR colours),
        both (rows, cols[, 3]). Also remembered for the text export. This is the CPU twin of
        the GL widget's fragment shader (ASCII_FRAG): same luminance weights, gamma ramp and
        colour modes - keep the two in sync."""
        small = frame[..., :3].astype(np.uint16)  # (rows, cols, 3) BGR
        b, g, r = small[..., 0], small[..., 1], small[..., 2]
        lum = (r * 77 + g * 151 + b * 28) >> 8  # 0..255
        idx = self.lut[lum]

        mode = self.color_mode
        if mode == "color":
            mx = small.max(axis=2, keepdims=True)
            mx[mx == 0] = 1
            norm = (small.astype(np.uint32) * 255 // mx).astype(np.uint16)
            col = (small * 2 + norm * 3) // 5
        elif mode == "raw":
            col = small
        elif mode in PALETTES:
            # palette: the "colour" mode's tint snapped to the nearest palette entry
            mx = small.max(axis=2, keepdims=True)
            mx[mx == 0] = 1
            norm = (small.astype(np.uint32) * 255 // mx).astype(np.uint16)
            tint = ((small * 2 + norm * 3) // 5).astype(np.float32) * (1.0 / 255.0)
            col = (self.nearest_palette(tint, mode) * 255.0 + 0.5).astype(np.uint16)
        else:
            # CRT phosphor look: the tube colour glows through the midtones, highlights
            # bloom brighter, and the very brightest pixels desaturate towards near-white,
            # like a real monitor's beam blowing out. `mono` has a near-white base so it
            # just gains the bloom.
            base = np.array(PHOSPHOR[mode], np.float32)          # BGR tube colour
            t = lum.astype(np.float32) * (1.0 / 255.0)           # 0..1 brightness
            glow = np.clip(0.05 + t * 1.15, 0.0, 1.0)[..., None] * base
            hot = (np.clip((t - 0.7) * (1.0 / 0.3), 0.0, 1.0) ** 2)[..., None] * 0.85
            col = (glow * (1.0 - hot) + 255.0 * hot).astype(np.uint16)
        self.last_chars, self.last_colors = idx, col
        return idx, col

    def bayer_convert(self, frame):
        """Bayer 1-bit dithering on the CPU: frame (rows, cols, 4) BGRX uint8, one pixel per
        grid pixel -> (rows, cols, 4) BGRX uint8 of the same size (to be scaled up with
        nearest-neighbour filtering). The CPU twin of BAYER_FRAG - keep the two in sync.
        Returns a buffer owned by this renderer and reused on the next call."""
        rows, cols = frame.shape[0], frame.shape[1]
        order = BAYER_ORDER[self.filter]
        self._ensure_pix_bufs(rows, cols, order)
        t, out = self._bayer_t, self._pix_out
        c = frame[..., :3].astype(np.float32) * (1.0 / 255.0)     # BGR 0..1
        mode = self.color_mode
        if mode == "color":
            out[..., :3] = (np.power(c, self.gamma) > t[..., None]) * np.uint8(255)
        elif mode in PALETTES:
            spread = PALETTES[mode][0]
            q = np.clip(c + (t[..., None] - 0.5) * spread, 0.0, 1.0)
            out[..., :3] = (self.nearest_palette(q, mode) * 255.0 + 0.5).astype(np.uint8)
        else:
            lum = np.power((c[..., 2] * 77.0 + c[..., 1] * 151.0 + c[..., 0] * 28.0) / 256.0, self.gamma)
            colour = np.array((255, 255, 255) if mode == "raw" else PHOSPHOR[mode], np.uint8)
            out[..., :3] = (lum > t)[..., None] * colour
        return out

    def vector_convert(self, frame):
        """Vector display on the CPU: Sobel edges of the small frame drawn as glowing beam
        traces, (rows, cols, 4) BGRX uint8 at grid resolution (to be scaled up smoothly).
        The CPU twin of VECTOR_EDGE_FRAG + VECTOR_FRAG - keep them in sync."""
        rows, cols = frame.shape[0], frame.shape[1]
        self._ensure_pix_bufs(rows, cols, 0)
        out = self._pix_out
        c = frame[..., :3].astype(np.float32) * (1.0 / 255.0)     # BGR 0..1
        lum = c[..., 2] * 0.299 + c[..., 1] * 0.587 + c[..., 0] * 0.114
        lp = np.pad(lum, 1, mode="edge")
        gx = ((lp[:-2, 2:] + 2.0 * lp[1:-1, 2:] + lp[2:, 2:])
              - (lp[:-2, :-2] + 2.0 * lp[1:-1, :-2] + lp[2:, :-2]))
        gy = ((lp[2:, :-2] + 2.0 * lp[2:, 1:-1] + lp[2:, 2:])
              - (lp[:-2, :-2] + 2.0 * lp[:-2, 1:-1] + lp[:-2, 2:]))
        e = np.clip((np.hypot(gx, gy) * 0.25 - VECTOR_EDGE_LO) / (VECTOR_EDGE_HI - VECTOR_EDGE_LO), 0.0, 1.0)
        e = e * e * (3.0 - 2.0 * e)                                 # smoothstep
        mode = self.color_mode
        if mode in PHOSPHOR:
            tint = np.array(PHOSPHOR[mode], np.float32) / 255.0
            line = e[..., None] * tint
        else:
            mx = c.max(axis=2, keepdims=True)
            norm = np.where(mx > 0.02, c / np.maximum(mx, 1e-6), 1.0).astype(np.float32)
            if mode == "raw":
                norm = (norm + c) * 0.5
            elif mode in PALETTES:
                norm = self.nearest_palette(norm, mode)
            line = e[..., None] * norm
        # halo: a small separable blur of the traces (the shader uses a 5x5 gaussian)
        k = np.array([1.0, 4.0, 6.0, 4.0, 1.0], np.float32) / 16.0
        pad = np.pad(line, ((2, 2), (2, 2), (0, 0)), mode="constant")
        h = sum(k[i] * pad[:, i:i + cols] for i in range(5))
        glow = sum(k[i] * h[i:i + rows] for i in range(5))
        pic = line * 1.1 + (0.35 * e * e)[..., None] + glow * VECTOR_GLOW
        out[..., :3] = (np.clip(pic, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        return out

    def convert(self, frame):
        """frame: (rows, cols, 4) BGRX uint8, one pixel per cell -> (rows*cell_h, cols*cell_w, 4) BGRX uint8.

        The returned array is a buffer owned by this renderer and reused on the next call -
        it must be consumed (e.g. blitted into a QImage that gets painted) before then."""
        rows, cols = frame.shape[0], frame.shape[1]
        idx, col = self.analyse(frame)
        self._ensure_bufs(rows, cols)
        mask, mask4d, tmp, out = self._mask_buf, self._mask_buf_4d, self._tmp_buf, self._out_buf

        # np.take is much faster here than atlas[idx] fancy indexing for this access pattern.
        glyphs = np.take(self.atlas, idx, axis=0)  # (rows, cols, cell_h, cell_w) uint16, 0..255 alpha
        np.copyto(mask4d, glyphs.transpose(0, 2, 1, 3))  # -> (rows*cell_h, cols*cell_w) via the buf's own layout
        # np.repeat's specialised C loop beats a broadcasted-view copy for this expansion.
        color_full = np.repeat(np.repeat(col, self.cell_h, axis=0), self.cell_w, axis=1)
        # Per-channel multiply into a reused scratch buffer: a plain (H,W)*(H,W) multiply
        # vectorises far better than one broadcasted (H,W,ch,cw,4)-shaped multiply did.
        for c in range(3):
            np.multiply(mask, color_full[..., c], out=tmp)
            np.right_shift(tmp, 8, out=tmp)
            out[..., c] = tmp
        return out

    def as_text(self, ansi=False):
        if self.last_chars is None:
            return ""
        chars = self.chars
        lines = []
        for y in range(self.last_chars.shape[0]):
            if ansi:
                parts = []
                for x in range(self.last_chars.shape[1]):
                    b, g, r = (int(v) for v in self.last_colors[y, x])
                    parts.append(f"\x1b[38;2;{r};{g};{b}m{chars[self.last_chars[y, x]]}")
                lines.append("".join(parts) + "\x1b[0m")
            else:
                lines.append("".join(chars[i] for i in self.last_chars[y]))
        return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------
# Video widget
# --------------------------------------------------------------------------------------

class VideoWidgetBase:
    """Everything the two video widgets share: state, the overlays drawn with QPainter
    (idle screen, subtitles, OSD flashes) and mouse handling. The concrete classes only
    differ in how the picture itself gets onto the screen. (A plain mixin: PyQt signals
    have to live on the QWidget subclasses themselves.)"""

    def _init_common(self, engine, ascii_renderer):
        self.engine = engine
        self.ascii = ascii_renderer
        self.ascii_mode = False
        self.forced_ascii = False  # audio visualiser: always ASCII
        self.has_media = False
        self.sub_text = ""
        self._osd_text = ""
        self._osd_until = 0.0
        self._cursor_on = True
        self.fps_log = False
        self.paused = False
        self._hide_osd = False        # set while grabbing a screenshot
        self._picture_rect = None     # where the picture sits in the last drawn frame (device px)
        self._fps_n = 0
        self._fps_t = time.monotonic()
        self.setMouseTracking(True)
        self.setMinimumSize(160, 90)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.mono_font = QFont(self.ascii.font_family)
        self.mono_font.setStyleHint(QFont.StyleHint.Monospace)
        self._osd_timer = QTimer(self)
        self._osd_timer.setSingleShot(True)
        self._osd_timer.timeout.connect(self.update)
        self._blink = QTimer(self)
        self._blink.timeout.connect(self._blink_tick)
        self._blink.start(530)
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self.toggle_pause.emit)

    # ---- state ----
    @property
    def ascii_active(self):
        return self.ascii_mode or self.forced_ascii

    def crt_supported(self):
        """Whether this widget can draw the CRT screen filter (needs the GL shaders)."""
        return False

    def video_color_supported(self):
        """Whether the colour modes also work on plain video (needs the GL shaders)."""
        return False

    @property
    def crt_active(self):
        """The CRT screen shows over the display filters and over plain video alike."""
        return self.ascii.crt_on and self.crt_supported()

    def flash(self, text, secs=2.0):
        self._osd_text = text
        self._osd_until = time.monotonic() + secs
        self._osd_timer.start(int(secs * 1000) + 50)
        self.update()

    def _blink_tick(self):
        self._cursor_on = not self._cursor_on
        if not self.has_media:
            self.update()

    def copy_state_from(self, other):
        for name in ("ascii_mode", "forced_ascii", "has_media", "sub_text", "_osd_text", "_osd_until", "fps_log",
                     "paused"):
            setattr(self, name, getattr(other, name))

    def _count_frame(self):
        if not self.fps_log:
            return
        self._fps_n += 1
        now = time.monotonic()
        if now - self._fps_t >= 1.0:
            print(f"[fps] {self._fps_n / (now - self._fps_t):.1f} frames/s drawn  ({self.width()}x{self.height()}"
                  f"{', ' + self.ascii.filter if self.ascii_active else ''}{'+crt' if self.crt_active else ''})",
                  file=sys.stderr)
            self._fps_n, self._fps_t = 0, now

    # ---- overlays ----
    def _osd_visible(self):
        return bool(self._osd_text) and time.monotonic() < self._osd_until

    def _paint_overlays(self, p):
        if not self.has_media:
            self._paint_idle(p)
        if self.ascii_active and self.sub_text and self.has_media:
            self._paint_subtitle(p)
        if self._osd_visible() and not self._hide_osd:
            self._paint_osd(p)

    def grab_picture(self):
        """The picture as currently shown (video or ASCII art), cropped to the picture area,
        without the OSD box - or None if there is nothing to grab."""
        if not self.has_media:
            return None
        self._hide_osd = True
        try:
            img = self._grab_frame()
        finally:
            self._hide_osd = False
        if img is None or img.isNull():
            return None
        rect = self._picture_rect
        if rect is not None:
            rect = rect.intersected(img.rect())
            if rect.width() > 0 and rect.height() > 0:
                img = img.copy(rect)
        return img

    def _paint_idle(self, p):
        font = QFont(self.mono_font)
        font.setPixelSize(max(12, min(20, self.width() // 48)))
        p.setFont(font)
        fm = QFontMetrics(font)
        lines = [
            "┌───────────────────────────────────────────┐",
            "│  asciiplay                                │",
            "│                                           │",
            "│  drop a video, audio or subtitle file     │",
            "│  or press  o  to open one                 │",
            "│                                           │",
            "│  t  filter g  crt  e  colour  c  crop     │",
            "│  [ ]  speed          a / j  audio / subs  │",
            "│  l  playlist         f  fullscreen        │",
            "│  h  all shortcuts                         │",
            "└───────────────────────────────────────────┘",
            "",
            "$ asciiplay _" if self._cursor_on else "$ asciiplay  ",
        ]
        lh = fm.height()
        total = lh * len(lines)
        y = max(10, (self.height() - total) // 2)
        x = max(10, (self.width() - fm.horizontalAdvance(lines[0])) // 2)
        p.setPen(QColor(90, 235, 110))
        for i, line in enumerate(lines):
            p.drawText(x, y + i * lh + fm.ascent(), line)

    def _paint_subtitle(self, p):
        font = QFont(self.mono_font)
        font.setPixelSize(max(14, int(self.ascii.cell_h * 1.4)))
        p.setFont(font)
        fm = QFontMetrics(font)
        lines = [ln for ln in self.sub_text.split("\n") if ln.strip()]
        if not lines:
            return
        lh = fm.height()
        margin = self.ascii.cell_h * 2 + 6
        y = self.height() - margin - lh * len(lines)
        for i, ln in enumerate(lines):
            w = fm.horizontalAdvance(ln) + 12
            x = (self.width() - w) // 2
            rect = QRect(x, y + i * lh, w, lh)
            p.fillRect(rect, QColor(0, 0, 0, 200))
            p.setPen(QColor(255, 255, 255))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, ln)

    def _paint_osd(self, p):
        font = QFont(self.mono_font)
        font.setPixelSize(16)
        p.setFont(font)
        fm = QFontMetrics(font)
        lines = self._osd_text.split("\n")
        w = max(fm.horizontalAdvance(ln) for ln in lines) + 16
        h = fm.height() * len(lines) + 10
        rect = QRect(12, 12, w, h)
        p.fillRect(rect, QColor(0, 0, 0, 190))
        p.setPen(QPen(QColor(90, 235, 110)))
        p.drawRect(rect)
        for i, ln in enumerate(lines):
            p.drawText(rect.x() + 8, rect.y() + 5 + i * fm.height() + fm.ascent(), ln)

    # ---- events ----
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.start(QApplication.doubleClickInterval())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self.toggle_fullscreen.emit()

    def wheelEvent(self, event):
        d = event.angleDelta().y()
        if d:
            self.seek_relative.emit(5.0 if d > 0 else -5.0)


class SoftwareVideoWidget(VideoWidgetBase, QWidget):
    """CPU path: mpv renders into a numpy array, the ASCII filter composites glyphs with
    numpy, and QPainter blits the result. Fallback for when OpenGL is unavailable."""
    toggle_pause = pyqtSignal()
    toggle_fullscreen = pyqtSignal()
    seek_relative = pyqtSignal(float)

    def __init__(self, engine: Engine, ascii_renderer: AsciiRenderer, parent=None):
        QWidget.__init__(self, parent)
        self._init_common(engine, ascii_renderer)
        self._image = None
        self._image_buf = None
        self._image_pos = QPoint(0, 0)
        self._image_target_size = None  # set when the resolution divider > 1: stretch to this size
        self._image_smooth = True       # ... with smooth filtering (False: nearest, for the Bayer pixels)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        # a full re-render per resize step is expensive here, so coalesce them
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self.render_now)
        self.engine.frame_ready.connect(self._on_frame_available)

    def _on_frame_available(self):
        if self.engine.take_update():
            self.render_now()

    def snapshot_ascii(self):
        """The text export reads the renderer's last frame; here that is always current."""
        return self.ascii.last_chars is not None

    def render_now(self):
        if not self.has_media or self.engine.ctx is None:
            self.update()
            return
        aspect = self.engine.display_aspect()
        W, H = self.width(), self.height()
        try:
            if self.ascii_active and not self.ascii.is_ascii:
                # Bayer / vector: one mpv-rendered pixel per grid pixel, converted at that
                # size and stretched up on paint (nearest for the dither, smooth for the beams)
                cols, rows = self.ascii.pixel_grid(W, H)
                s = self.ascii.pixel_size()
                vc, vr = fit_rect(aspect, cols, rows)
                frame = self.engine.render_sw(vc, vr)
                out = self.ascii.vector_convert(frame) if self.ascii.filter == "vector" \
                    else self.ascii.bayer_convert(frame)
                self._image_buf = out
                self._image = QImage(out.data, vc, vr, out.strides[0], QImage.Format.Format_RGB32)
                self._image_target_size = QSize(vc * s, vr * s)
                self._image_smooth = self.ascii.filter == "vector"
                self._image_pos = QPoint((W - vc * s) // 2, (H - vr * s) // 2)
                self._picture_rect = QRect(self._image_pos, self._image_target_size)
            elif self.ascii_active:
                cols, rows = self.ascii.grid(W, H)  # already divided by the resolution divider
                cw, ch = self.ascii.cell_w, self.ascii.cell_h
                d = self.ascii.res_divider
                # aspect in cell units: cells are cw x ch pixels
                vc, vr = fit_rect(aspect * ch / cw, cols, rows)
                # one mpv-rendered pixel per character cell - mpv's own scaler does the
                # downsampling from full video resolution.
                frame = self.engine.render_sw(vc, vr)
                out = self.ascii.convert(frame)
                self._image_buf = out
                h, w = out.shape[0], out.shape[1]
                self._image = QImage(out.data, w, h, out.strides[0], QImage.Format.Format_RGB32)
                if d > 1:
                    # below full resolution: the composited image is smaller than the
                    # display area by exactly the divider, so stretch it back up on paint
                    # instead of compositing that many more glyphs.
                    self._image_target_size = QSize(w * d, h * d)
                    self._image_smooth = True
                    self._image_pos = QPoint((W - w * d) // 2, (H - h * d) // 2)
                else:
                    self._image_target_size = None
                    self._image_pos = QPoint((W - vc * cw) // 2, (H - vr * ch) // 2)
                shown = self._image_target_size or QSize(w, h)
                self._picture_rect = QRect(self._image_pos, shown)
            else:
                dpr = self.devicePixelRatioF()
                pw, ph = fit_rect(aspect, int(W * dpr), int(H * dpr))
                frame = self.engine.render_sw(pw, ph)
                self._image_buf = frame
                self._image = QImage(frame.data, pw, ph, frame.strides[0], QImage.Format.Format_RGB32)
                self._image.setDevicePixelRatio(dpr)
                self._image_target_size = None
                self._image_pos = QPoint(int((W - pw / dpr) / 2), int((H - ph / dpr) / 2))
                self._picture_rect = QRect(self._image_pos, QSize(int(pw / dpr), int(ph / dpr)))
        except Exception as exc:
            self.engine.log_message.emit("error", "render", str(exc))
        self._count_frame()
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        if self.has_media and self._image is not None:
            if self._image_target_size is not None:
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._image_smooth)
                p.drawImage(QRect(self._image_pos, self._image_target_size), self._image)
            else:
                p.drawImage(self._image_pos, self._image)
        self._paint_overlays(p)
        p.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start(30)

    def _grab_frame(self):
        pix = self.grab()
        img = pix.toImage()
        dpr = pix.devicePixelRatio()
        if self._picture_rect is not None and dpr != 1:
            r = self._picture_rect
            self._picture_rect = QRect(int(r.x() * dpr), int(r.y() * dpr), int(r.width() * dpr), int(r.height() * dpr))
        return img

    def release_gl(self):
        pass


class _GLFuncs:
    """The handful of raw OpenGL entry points GLVideoWidget calls itself, resolved through
    Qt (PyQt6 has no QOpenGLFunctions binding, and PyOpenGL would be an extra dependency
    for nine calls)."""

    def __init__(self, ctx):
        self._ctx = ctx
        c = ctypes
        self.BindFramebuffer = self._load("glBindFramebuffer", None, c.c_uint, c.c_uint)
        self.Viewport = self._load("glViewport", None, c.c_int, c.c_int, c.c_int, c.c_int)
        self.ClearColor = self._load("glClearColor", None, c.c_float, c.c_float, c.c_float, c.c_float)
        self.Clear = self._load("glClear", None, c.c_uint)
        self.Disable = self._load("glDisable", None, c.c_uint)
        self.DrawArrays = self._load("glDrawArrays", None, c.c_uint, c.c_int, c.c_int)
        self.ActiveTexture = self._load("glActiveTexture", None, c.c_uint)
        self.BindTexture = self._load("glBindTexture", None, c.c_uint, c.c_uint)
        self.TexParameteri = self._load("glTexParameteri", None, c.c_uint, c.c_uint, c.c_int)

    def proc_address(self, name):
        """mpv's get_proc_address: bytes name -> address (0 if unknown)."""
        try:
            return int(self._ctx.getProcAddress(bytes(name)))
        except Exception:
            return 0

    def _load(self, name, restype, *argtypes):
        addr = self.proc_address(name.encode())
        if not addr:
            raise RuntimeError(f"OpenGL entry point {name} not available")
        return ctypes.CFUNCTYPE(restype, *argtypes)(addr)


if HAVE_GL:
    class GLVideoWidget(VideoWidgetBase, QOpenGLWidget):
        """GPU path. Normal video: mpv's OpenGL renderer draws straight into this widget's
        framebuffer - decoding, scaling and drawing never leave the graphics card (with
        nvdec/vaapi interop not even the decoded frame does). ASCII filter: mpv renders
        into a tiny off-screen framebuffer, one pixel per character cell, and a fragment
        shader (ASCII_FRAG) turns that into glyphs per screen pixel - so a 5120x1440
        fullscreen ASCII picture costs the GPU about as much as drawing a texture. With the
        CRT screen filter on, the picture - filtered or not - goes through a few more small
        passes (afterglow, focus blur, bloom, tube composition - see _draw_crt) before
        reaching the screen.

        Overlays (subtitles, OSD, idle screen) are still drawn with QPainter on top; Qt
        resets the GL state it needs when the painter begins."""
        toggle_pause = pyqtSignal()
        toggle_fullscreen = pyqtSignal()
        seek_relative = pyqtSignal(float)
        gl_failed = pyqtSignal(str)   # mpv could not use this GL context; caller should fall back
        render_ready = pyqtSignal()   # the render context exists; media may be loaded now

        def __init__(self, engine: Engine, ascii_renderer: AsciiRenderer, parent=None):
            QOpenGLWidget.__init__(self, parent)
            self._init_common(engine, ascii_renderer)
            self._gl = None
            self._prog = None
            self._vao = None
            self._atlas_tex = None
            self._atlas_key = None
            self._small_fbo = None
            self._shader_ok = False
            # Bayer / vector filter programs (separate from the ASCII one, so a driver that
            # rejects them still gets ASCII on the GPU) and the vector edge framebuffer
            self._progs = {}
            self._filters_ok = False
            self._edge_fbo = None
            # colour modes on plain video (VIDEO_COLOR_FRAG): mpv renders in here first
            self._video_fbo = None
            self._video_size = None
            self._cpu_smooth = True
            self._keepaspect = None
            self._ready = False
            self._released = False
            self._cpu_buf = None
            # CRT filter: programs and framebuffers (built lazily, sized to the widget)
            self._crt_ok = False
            self._crt_progs = {}
            self._scene_fbo = None
            self._persist = [None, None]
            self._persist_ix = 0
            self._persist_stale = True   # nothing usable in the persistence buffers yet
            self._focus = [None, None]
            self._focus_half = [None, None]
            self._bloom = [None, None]
            self._crt_size = None
            self._crt_last_t = None
            self._crt_t0 = time.monotonic()
            self._crt_seed = 0
            # while paused the grain and afterglow should keep living, but mpv sends no
            # new frames then - this timer stands in (only runs while paused with CRT on)
            self._crt_timer = QTimer(self)
            self._crt_timer.setInterval(40)
            self._crt_timer.timeout.connect(self.update)
            self.engine.frame_ready.connect(self.update)
            self.frameSwapped.connect(self.engine.report_swap)

        # ---- API shared with SoftwareVideoWidget ----
        def render_now(self):
            self.update()

        def _grab_frame(self):
            if not self._ready:
                return None
            return self.grabFramebuffer()   # re-runs paintGL, with the OSD suppressed by the caller

        def snapshot_ascii(self):
            """Read mpv's cell-sized render back and run the CPU analysis on it so the text
            export has characters and colours - only on demand, never per frame."""
            if not self._ready or self._small_fbo is None:
                return False
            self.makeCurrent()
            try:
                frame = self._read_small_frame()
            finally:
                self.doneCurrent()
            if frame is None:
                return False
            self.ascii.analyse(frame)
            return True

        def crt_supported(self):
            return self._shader_ok and self._crt_ok

        def video_color_supported(self):
            return self._shader_ok and self._filters_ok

        def release_gl(self):
            """Free mpv's render context and our GL objects while the context still exists."""
            if self._released:
                return
            self._released = True
            self._ready = False
            self._crt_timer.stop()
            try:
                self.makeCurrent()
            except Exception:
                pass
            try:
                if self._atlas_tex is not None:
                    self._atlas_tex.destroy()
                self._atlas_tex = None
                self._small_fbo = None
                self._prog = None
                self._vao = None
                self._progs = {}
                self._edge_fbo = None
                self._video_fbo = None
                self._video_size = None
                self._crt_progs = {}
                self._scene_fbo = None
                self._persist = [None, None]
                self._focus = [None, None]
                self._focus_half = [None, None]
                self._bloom = [None, None]
                self._crt_size = None
                self.engine.free_render_ctx()
            finally:
                try:
                    self.doneCurrent()
                except Exception:
                    pass

        # ---- GL setup ----
        def initializeGL(self):
            ctx = self.context()
            try:
                self._gl = _GLFuncs(ctx)
                self.engine.init_render_gl(self._gl.proc_address)
            except Exception as exc:
                self._gl = None
                message = str(exc)   # `exc` itself is gone once this block ends
                # don't tear this widget down from inside its own initializeGL
                QTimer.singleShot(0, lambda: self.gl_failed.emit(message))
                return
            ctx.aboutToBeDestroyed.connect(self.release_gl)
            self._ready = True
            f = ctx.format()
            print(f"[info] gl: {'OpenGL ES' if ctx.isOpenGLES() else 'OpenGL'} {f.majorVersion()}.{f.minorVersion()}"
                  f", swap interval {f.swapInterval()}", file=sys.stderr)
            try:
                self._build_shader()
                self._shader_ok = True
            except Exception as exc:
                self._shader_ok = False
                self.engine.log_message.emit("warn", "gl", f"ASCII shader unavailable, compositing on the CPU: {exc}")
            if self._shader_ok:
                try:
                    self._build_filter_shaders()
                    self._filters_ok = True
                except Exception as exc:
                    self._filters_ok = False
                    self.engine.log_message.emit("warn", "gl",
                                                 f"Bayer/vector shaders unavailable, compositing them on the CPU: {exc}")
                try:
                    self._build_crt_shaders()
                    self._crt_ok = True
                except Exception as exc:
                    self._crt_ok = False
                    self.engine.log_message.emit("warn", "gl", f"CRT filter unavailable: {exc}")
            QTimer.singleShot(0, self.render_ready.emit)

        def _glsl_header(self):
            fmt = self.context().format()
            if self.context().isOpenGLES():
                if fmt.majorVersion() < 3:
                    raise RuntimeError("OpenGL ES 3.0 needed for the shader, have ES %d.%d"
                                       % (fmt.majorVersion(), fmt.minorVersion()))
                return "#version 300 es\nprecision highp float;\nprecision highp int;\nprecision highp sampler2D;\n"
            return "#version 130\n"   # texelFetch and gl_VertexID need GL 3.0

        def _compile(self, frag, uniforms, samplers=()):
            """Full-screen-triangle program: ASCII_VERT + `frag`. Returns (program, {uniform: location});
            `samplers` are (name, texture unit) pairs bound once here."""
            header = self._glsl_header()
            prog = QOpenGLShaderProgram()
            if not prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, header + ASCII_VERT):
                raise RuntimeError("vertex shader: " + prog.log())
            if not prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, header + frag):
                raise RuntimeError("fragment shader: " + prog.log())
            if not prog.link():
                raise RuntimeError("link: " + prog.log())
            u = {name: prog.uniformLocation(name) for name in uniforms}
            if samplers:
                prog.bind()
                for name, unit in samplers:
                    prog.setUniformValue(prog.uniformLocation(name), unit)
                prog.release()
            return prog, u

        def _build_shader(self):
            self._prog, self._u = self._compile(GLSL_COMMON + ASCII_FRAG, (
                "u_frame", "u_atlas", "u_origin", "u_cell", "u_glyph", "u_grid", "u_fbh",
                "u_nchars", "u_gamma", "u_mode", "u_phosphor", "u_pal_off", "u_pal_n"))
            # core profiles refuse to draw without a vertex array object bound, even an
            # empty one; compatibility profiles don't care either way
            vao = QOpenGLVertexArrayObject()
            self._vao = vao if vao.create() else None

        def _build_filter_shaders(self):
            self._progs = {
                "bayer": self._compile(GLSL_COMMON + BAYER_FRAG, (
                    "u_origin", "u_cell", "u_grid", "u_fbh", "u_gamma", "u_mode", "u_phosphor", "u_order",
                    "u_spread", "u_pal_off", "u_pal_n"), (("u_frame", 0),)),
                "edge": self._compile(GLSL_COMMON + VECTOR_EDGE_FRAG, (
                    "u_grid", "u_mode", "u_phosphor", "u_pal_off", "u_pal_n", "u_lo", "u_hi"), (("u_frame", 0),)),
                "vector": self._compile(VECTOR_FRAG, ("u_origin", "u_cell", "u_grid", "u_fbh", "u_glow"),
                                        (("u_edge", 0),)),
                "video": self._compile(GLSL_COMMON + VIDEO_COLOR_FRAG, (
                    "u_res", "u_mode", "u_phosphor", "u_pal_off", "u_pal_n", "u_spread", "u_dither_px"),
                    (("u_frame", 0),)),
            }

        def _build_crt_shaders(self):
            self._crt_progs = {
                "persist": self._compile(CRT_PERSIST_FRAG, ("u_res", "u_decay", "u_floor", "u_dtn",
                                                            "u_tint", "u_tint_mix"),
                                         (("u_cur", 0), ("u_prev", 1))),
                "focus": self._compile(CRT_FOCUS_FRAG, ("u_res", "u_dir", "u_sigma"), (("u_src", 0),)),
                "blur": self._compile(CRT_BLUR_FRAG, ("u_res", "u_dir", "u_prep"), (("u_src", 0),)),
                "crt": self._compile(CRT_FRAG, (
                    "u_res", "u_rect", "u_curve", "u_corner", "u_mask", "u_mask_px", "u_scan", "u_scan_period",
                    "u_bloom_amt", "u_grain", "u_hum", "u_vignette", "u_aberr", "u_time", "u_seed"),
                    (("u_scene", 0), ("u_bloom", 1))),
            }

        def _make_fbo(self, gl, w, h):
            """An RGBA8 framebuffer whose texture samples smoothly (Qt's default is nearest),
            cleared to black - a fresh FBO's contents are undefined."""
            f = QOpenGLFramebufferObject(w, h)
            gl.ActiveTexture(GL_TEXTURE0)
            gl.BindTexture(GL_TEXTURE_2D, f.texture())
            for pname, val in ((GL_TEXTURE_MIN_FILTER, GL_LINEAR), (GL_TEXTURE_MAG_FILTER, GL_LINEAR),
                               (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE), (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)):
                gl.TexParameteri(GL_TEXTURE_2D, pname, val)
            gl.BindTexture(GL_TEXTURE_2D, 0)
            gl.BindFramebuffer(GL_FRAMEBUFFER, f.handle())
            gl.Viewport(0, 0, w, h)
            gl.ClearColor(0.0, 0.0, 0.0, 1.0)
            gl.Clear(GL_COLOR_BUFFER_BIT)
            return f

        def _color_params(self):
            """The colour mode as the shaders want it: (mode id, tube colour, palette slice).
            Mode ids are 0 colour, 1 raw, 2 phosphor, 3 palette - the same in every shader."""
            mode = self.ascii.color_mode
            if mode in PALETTES:
                return 3, (0.0, 0.0, 0.0), PAL_OFFSETS[mode], len(PALETTES[mode][1])
            if mode in PHOSPHOR:
                b, g, r = PHOSPHOR[mode]
                return 2, (r / 255.0, g / 255.0, b / 255.0), 0, 0
            return (1 if mode == "raw" else 0), (0.0, 0.0, 0.0), 0, 0

        def _ensure_video_fbo(self, gl, fw, fh):
            """The buffer mpv draws into when a colour pass has to run over its picture."""
            if self._video_size != (fw, fh) or self._video_fbo is None:
                self._video_fbo = self._make_fbo(gl, fw, fh)
                self._video_size = (fw, fh)
            return self._video_fbo

        def _ensure_crt_fbos(self, gl, fw, fh):
            if self._crt_size == (fw, fh) and self._scene_fbo is not None:
                return
            self._scene_fbo = self._make_fbo(gl, fw, fh)
            self._persist = [self._make_fbo(gl, fw, fh), self._make_fbo(gl, fw, fh)]
            self._focus = [self._make_fbo(gl, fw, fh), self._make_fbo(gl, fw, fh)]
            bw, bh = max(1, (fw + 1) // 2), max(1, (fh + 1) // 2)
            self._focus_half = [self._make_fbo(gl, bw, bh), self._make_fbo(gl, bw, bh)]
            self._bloom = [self._make_fbo(gl, bw, bh), self._make_fbo(gl, bw, bh)]
            self._crt_size = (fw, fh)
            self._crt_last_t = None
            self._persist_stale = True

        def _run_pass(self, gl, target, w, h, textures):
            """Draw the full-screen triangle with the bound program into framebuffer `target`,
            with `textures` on units 0, 1, ..."""
            gl.BindFramebuffer(GL_FRAMEBUFFER, target)
            gl.Viewport(0, 0, w, h)
            for unit, tex in enumerate(textures):
                gl.ActiveTexture(GL_TEXTURE0 + unit)
                gl.BindTexture(GL_TEXTURE_2D, tex)
            if self._vao is not None:
                self._vao.bind()
            gl.DrawArrays(GL_TRIANGLES, 0, 3)
            if self._vao is not None:
                self._vao.release()

        def _ensure_atlas_tex(self):
            key = self.ascii.atlas_key
            if key == self._atlas_key and self._atlas_tex is not None:
                return
            if self._atlas_tex is not None:
                self._atlas_tex.destroy()
            tex = QOpenGLTexture(self.ascii.atlas_image, QOpenGLTexture.MipMapGeneration.DontGenerateMipMaps)
            tex.setMinificationFilter(QOpenGLTexture.Filter.Linear)
            tex.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
            tex.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
            self._atlas_tex = tex
            self._atlas_key = key

        def _set_keepaspect(self, want):
            # normal mode: mpv letterboxes into the whole widget itself; ASCII mode: the
            # off-screen target is already the right shape, so fill it edge to edge
            if self._keepaspect != want:
                self.engine.set("keepaspect", want)
                self._keepaspect = want

        def _read_small_frame(self):
            """mpv's cell-sized render as a (rows, cols, 4) BGRX uint8 array (context must be current)."""
            if self._small_fbo is None:
                return None
            # mpv (flip_y off) writes row 0 = top, so no flip on the way out either
            img = self._small_fbo.toImage(False).convertToFormat(QImage.Format.Format_RGB32)
            ptr = img.constBits()
            ptr.setsize(img.sizeInBytes())
            arr = np.frombuffer(ptr, np.uint8).reshape(img.height(), img.bytesPerLine())[:, :img.width() * 4]
            return arr.reshape(img.height(), img.width(), 4).copy()

        # ---- drawing ----
        def paintGL(self):
            if not self._ready:
                # no usable render context (GL failed and --renderer gl forbade the fallback,
                # or we're being torn down): still show the idle screen / error flash
                p = QPainter(self)
                p.fillRect(self.rect(), QColor(0, 0, 0))
                self._paint_overlays(p)
                p.end()
                return
            gl = self._gl
            self.engine.take_update()
            dpr = self.devicePixelRatioF()
            W, H = self.width(), self.height()
            fw, fh = max(1, round(W * dpr)), max(1, round(H * dpr))
            fbo = self.defaultFramebufferObject()
            cpu_image = None
            try:
                if self.has_media and self.ascii_active:
                    cpu_image = self._draw_ascii(gl, fbo, fw, fh, dpr, W, H)
                elif self.has_media:
                    self._draw_video(gl, fbo, fw, fh, dpr)
                else:
                    gl.BindFramebuffer(GL_FRAMEBUFFER, fbo)
                    gl.Viewport(0, 0, fw, fh)
                    gl.ClearColor(0.0, 0.0, 0.0, 1.0)
                    gl.Clear(GL_COLOR_BUFFER_BIT)
            except Exception as exc:
                self.engine.log_message.emit("error", "render", str(exc))
            if self.has_media:
                self._count_frame()
            want_timer = self.has_media and self.paused and self.crt_active
            if want_timer != self._crt_timer.isActive():
                (self._crt_timer.start if want_timer else self._crt_timer.stop)()
            needs_painter = (cpu_image is not None or not self.has_media or self._osd_visible()
                             or (self.ascii_active and bool(self.sub_text)))
            if not needs_painter:
                return  # the common case while playing: no QPainter round trip at all
            p = QPainter(self)
            if cpu_image is not None:
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._cpu_smooth)
                p.drawImage(self._cpu_rect, cpu_image)
            self._paint_overlays(p)
            p.end()

        def _clear(self, gl, target, w, h):
            """Black out a render target before handing it to mpv, so a source with an
            alpha channel is composited over black whatever mpv's background mode does
            (and never over what the previous frame left in the buffer)."""
            gl.BindFramebuffer(GL_FRAMEBUFFER, target)
            gl.Viewport(0, 0, w, h)
            gl.ClearColor(0.0, 0.0, 0.0, 1.0)
            gl.Clear(GL_COLOR_BUFFER_BIT)

        def _draw_video(self, gl, fbo, fw, fh, dpr):
            """Plain video, no display filter: mpv draws straight into the widget - or, when
            a colour mode or the CRT screen is on, into an off-screen buffer that the colour
            pass and the CRT passes then take to the screen (so an ordinary film can be
            watched as a green-phosphor tube, or simply as if it were on a TV set)."""
            self._set_keepaspect(True)
            crt = self.crt_active
            mode_id, phosphor, pal_off, pal_n = self._color_params()
            tint = mode_id != 0 and self.video_color_supported()
            if crt:
                self._ensure_crt_fbos(gl, fw, fh)
                out = self._scene_fbo.handle()   # the CRT passes take it from here to the screen
            else:
                out = fbo
            # with a colour pass to run, mpv draws into its own buffer and that pass writes `out`
            target = self._ensure_video_fbo(gl, fw, fh).handle() if tint else out
            self._clear(gl, target, fw, fh)
            self.engine.render_gl(target, fw, fh, flip_y=True)
            gl.BindFramebuffer(GL_FRAMEBUFFER, target)
            # mpv letterboxes into the whole framebuffer; this is where the picture lands
            pw, ph = fit_rect(self.engine.display_aspect(), fw, fh)
            ox, oy = (fw - pw) // 2, (fh - ph) // 2
            self._picture_rect = QRect(ox, oy, pw, ph)
            if not (tint or crt):
                return
            # mpv leaves its own GL state behind; our passes need it as the quad wants it
            for cap in (GL_BLEND, GL_SCISSOR_TEST, GL_DEPTH_TEST, GL_CULL_FACE):
                gl.Disable(cap)
            if tint:
                spread = PALETTES[self.ascii.color_mode][0] if mode_id == 3 else 0.0
                prog, u = self._progs["video"]
                prog.bind()
                prog.setUniformValue(u["u_res"], QVector2D(float(fw), float(fh)))
                prog.setUniformValue(u["u_mode"], mode_id)
                prog.setUniformValue(u["u_phosphor"], QVector3D(*phosphor))
                prog.setUniformValue(u["u_pal_off"], pal_off)
                prog.setUniformValue(u["u_pal_n"], pal_n)
                prog.setUniformValue(u["u_spread"], float(spread))
                prog.setUniformValue(u["u_dither_px"], float(max(1, round(dpr))))
                self._run_pass(gl, out, fw, fh, (self._video_fbo.texture(),))
                prog.release()
                gl.ActiveTexture(GL_TEXTURE0)
                gl.BindTexture(GL_TEXTURE_2D, 0)
            if crt:
                self._draw_crt(gl, fbo, fw, fh, (ox, fh - oy - ph, pw, ph), 0.0, dpr, kind="video")

        def _draw_ascii(self, gl, fbo, fw, fh, dpr, W, H):
            """Draw the active display filter (ASCII, Bayer or vector). Returns a QImage to
            paint if the shader for it is unavailable, else None."""
            kind = self.ascii.filter
            if kind == "ascii":
                cols, rows = self.ascii.grid(W, H)  # already divided by the resolution divider
                cw, ch = self.ascii.cell_w, self.ascii.cell_h
                d = self.ascii.res_divider
                vc, vr = fit_rect(self.engine.display_aspect() * ch / cw, cols, rows)
                cell_x, cell_y = cw * d * dpr, ch * d * dpr
                shader_ok = self._shader_ok
            else:
                # Bayer / vector: a grid of square pixels instead of character cells
                cols, rows = self.ascii.pixel_grid(W, H)
                d = self.ascii.pixel_size()
                vc, vr = fit_rect(self.engine.display_aspect(), cols, rows)
                cell_x = cell_y = d * dpr
                shader_ok = self._shader_ok and self._filters_ok
            if self._small_fbo is None or self._small_fbo.size() != QSize(vc, vr):
                self._small_fbo = QOpenGLFramebufferObject(vc, vr)
            self._set_keepaspect(False)
            # one mpv-rendered pixel per character cell, scaled down by mpv on the GPU. With
            # flip_y off mpv writes the picture top-down (row 0 = top), which is what the
            # shader and the export readback assume.
            self._clear(gl, self._small_fbo.handle(), vc, vr)
            self.engine.render_gl(self._small_fbo.handle(), vc, vr, flip_y=False)
            crt = self.crt_active and shader_ok
            if crt:
                self._ensure_crt_fbos(gl, fw, fh)
                target = self._scene_fbo.handle()   # the CRT passes take it from here to the screen
            else:
                target = fbo
            gl.BindFramebuffer(GL_FRAMEBUFFER, target)
            gl.Viewport(0, 0, fw, fh)
            gl.ClearColor(0.0, 0.0, 0.0, 1.0)
            gl.Clear(GL_COLOR_BUFFER_BIT)
            ox, oy = (fw - vc * cell_x) / 2.0, (fh - vr * cell_y) / 2.0
            self._picture_rect = QRect(int(ox), int(oy), int(vc * cell_x), int(vr * cell_y))
            if not shader_ok:
                frame = self._read_small_frame()
                if kind == "ascii":
                    out = self.ascii.convert(frame)
                elif kind == "vector":
                    out = self.ascii.vector_convert(frame)
                else:
                    out = self.ascii.bayer_convert(frame)
                self._cpu_buf = out
                self._cpu_smooth = kind not in BAYER_ORDER
                h, w = out.shape[0], out.shape[1]
                self._cpu_rect = QRect(int(ox / dpr), int(oy / dpr), w * d, h * d)
                return QImage(out.data, w, h, out.strides[0], QImage.Format.Format_RGB32)
            # mpv leaves its own GL state behind; set what the quad needs explicitly
            for cap in (GL_BLEND, GL_SCISSOR_TEST, GL_DEPTH_TEST, GL_CULL_FACE):
                gl.Disable(cap)
            mode = self.ascii.color_mode
            mode_id, phosphor, pal_off, pal_n = self._color_params()
            common = dict(origin=QVector2D(ox, oy), cell=QVector2D(cell_x, cell_y), grid=QVector2D(float(vc), float(vr)),
                          fbh=float(fh), mode=mode_id, phosphor=QVector3D(*phosphor), pal_off=pal_off, pal_n=pal_n)
            if kind == "ascii":
                self._shade_ascii(gl, common)
            elif kind == "vector":
                self._shade_vector(gl, target, fw, fh, vc, vr, common)
            else:
                self._shade_bayer(gl, common, BAYER_ORDER[kind], PALETTES[mode][0] if mode in PALETTES else 0.0)
            gl.ActiveTexture(GL_TEXTURE0)
            gl.BindTexture(GL_TEXTURE_2D, 0)
            if crt:
                rect_bl = (ox, fh - oy - vr * cell_y, vc * cell_x, vr * cell_y)
                self._draw_crt(gl, fbo, fw, fh, rect_bl, cell_y, dpr, kind)
            return None

        def _draw_triangle(self, gl):
            if self._vao is not None:
                self._vao.bind()
            gl.DrawArrays(GL_TRIANGLES, 0, 3)
            if self._vao is not None:
                self._vao.release()

        def _shade_ascii(self, gl, c):
            """The ASCII shader: mpv's cell-sized render (unit 0) + glyph atlas (unit 1) -> the bound target."""
            self._ensure_atlas_tex()
            prog, u = self._prog, self._u
            prog.bind()
            prog.setUniformValue(u["u_frame"], 0)
            prog.setUniformValue(u["u_atlas"], 1)
            prog.setUniformValue(u["u_origin"], c["origin"])
            prog.setUniformValue(u["u_cell"], c["cell"])
            prog.setUniformValue(u["u_glyph"], QVector2D(float(self.ascii.cell_w), float(self.ascii.cell_h)))
            prog.setUniformValue(u["u_grid"], c["grid"])
            prog.setUniformValue(u["u_fbh"], c["fbh"])
            prog.setUniformValue(u["u_nchars"], float(len(self.ascii.chars)))
            prog.setUniformValue(u["u_gamma"], float(self.ascii.gamma))
            prog.setUniformValue(u["u_mode"], c["mode"])
            prog.setUniformValue(u["u_phosphor"], c["phosphor"])
            prog.setUniformValue(u["u_pal_off"], c["pal_off"])
            prog.setUniformValue(u["u_pal_n"], c["pal_n"])
            gl.ActiveTexture(GL_TEXTURE0)
            gl.BindTexture(GL_TEXTURE_2D, self._small_fbo.texture())
            self._atlas_tex.bind(1)
            self._draw_triangle(gl)
            self._atlas_tex.release(1)
            prog.release()

        def _shade_bayer(self, gl, c, order, spread):
            """The Bayer dither shader: mpv's grid-sized render (unit 0) -> the bound target."""
            prog, u = self._progs["bayer"]
            prog.bind()
            prog.setUniformValue(u["u_origin"], c["origin"])
            prog.setUniformValue(u["u_cell"], c["cell"])
            prog.setUniformValue(u["u_grid"], c["grid"])
            prog.setUniformValue(u["u_fbh"], c["fbh"])
            prog.setUniformValue(u["u_gamma"], float(self.ascii.gamma))
            prog.setUniformValue(u["u_mode"], c["mode"])
            prog.setUniformValue(u["u_phosphor"], c["phosphor"])
            prog.setUniformValue(u["u_order"], int(order))
            prog.setUniformValue(u["u_spread"], float(spread))
            prog.setUniformValue(u["u_pal_off"], c["pal_off"])
            prog.setUniformValue(u["u_pal_n"], c["pal_n"])
            gl.ActiveTexture(GL_TEXTURE0)
            gl.BindTexture(GL_TEXTURE_2D, self._small_fbo.texture())
            self._draw_triangle(gl)
            prog.release()

        def _shade_vector(self, gl, target, fw, fh, vc, vr, c):
            """The vector display: edge pass into the grid-sized edge framebuffer, then the
            beam pass onto `target` (fw x fh)."""
            if self._edge_fbo is None or self._edge_fbo.size() != QSize(vc, vr):
                self._edge_fbo = self._make_fbo(gl, vc, vr)
            prog, u = self._progs["edge"]
            prog.bind()
            prog.setUniformValue(u["u_grid"], c["grid"])
            prog.setUniformValue(u["u_mode"], c["mode"])
            prog.setUniformValue(u["u_phosphor"], c["phosphor"])
            prog.setUniformValue(u["u_pal_off"], c["pal_off"])
            prog.setUniformValue(u["u_pal_n"], c["pal_n"])
            prog.setUniformValue(u["u_lo"], float(VECTOR_EDGE_LO))
            prog.setUniformValue(u["u_hi"], float(VECTOR_EDGE_HI))
            self._run_pass(gl, self._edge_fbo.handle(), vc, vr, (self._small_fbo.texture(),))
            prog.release()
            prog, u = self._progs["vector"]
            prog.bind()
            prog.setUniformValue(u["u_origin"], c["origin"])
            prog.setUniformValue(u["u_cell"], c["cell"])
            prog.setUniformValue(u["u_grid"], c["grid"])
            prog.setUniformValue(u["u_fbh"], c["fbh"])
            prog.setUniformValue(u["u_glow"], float(VECTOR_GLOW))
            self._run_pass(gl, target, fw, fh, (self._edge_fbo.texture(),))
            prog.release()

        def _draw_crt(self, gl, fbo, fw, fh, rect, cell_y, dpr, kind="ascii"):
            """The CRT screen filter: afterglow, focus blur, bloom and tube composition on
            top of the picture sitting in self._scene_fbo. `rect` is the picture in framebuffer
            px with a bottom-left origin (GL convention), `cell_y` a character row's (or grid
            pixel's) height in px (0 for plain video, which has no cells), `kind` what drew the
            picture: a vector monitor has no shadow mask and no scanlines - just the beam on
            the phosphor, which lingers longer - so those are left out for `vector`."""
            lvl = CRT_LEVELS[self.ascii.crt_level][1]
            vector = kind == "vector"
            tau_scale = (1.8 if vector else 1.0) * max(0.0, self.ascii.crt_trail)
            now = time.monotonic()
            dt = 0.0 if self._crt_last_t is None else min(0.1, max(0.0, now - self._crt_last_t))
            self._crt_last_t = now
            self._crt_seed = (self._crt_seed + 1) & 0xFFFF
            # 1. phosphor persistence: ping-pong between the two buffers. With the trail knob
            # at zero the phosphor lets go instantly and the pass is skipped altogether.
            if tau_scale > 0.005:
                prev, cur = self._persist[self._persist_ix], self._persist[1 - self._persist_ix]
                self._persist_ix = 1 - self._persist_ix
                if self._persist_stale:
                    # coming back from trail 0: whatever is in there is old, don't smear it in
                    self._clear(gl, prev.handle(), fw, fh)
                    self._persist_stale = False
                prog, u = self._crt_progs["persist"]
                prog.bind()
                prog.setUniformValue(u["u_res"], QVector2D(float(fw), float(fh)))
                prog.setUniformValue(u["u_decay"], QVector3D(*(math.exp(-dt / (t * tau_scale)) for t in lvl["tau"])))
                prog.setUniformValue(u["u_floor"], float(dt * 0.5))
                prog.setUniformValue(u["u_dtn"], float(dt * 60.0))
                rgb = CRT_TRAIL_TINTS[self.ascii.crt_tint][1]
                prog.setUniformValue(u["u_tint"], QVector3D(*[v / 255.0 for v in rgb or (0, 0, 0)]))
                prog.setUniformValue(u["u_tint_mix"], 0.0 if rgb is None else 1.0)
                self._run_pass(gl, cur.handle(), fw, fh, (self._scene_fbo.texture(), prev.texture()))
                prog.release()
                lit = cur.texture()
            else:
                self._persist_stale = True
                lit = self._scene_fbo.texture()
            # 2. focus blur: the beam's spot, wider across than down. Two passes (horizontal
            # then vertical), and none at all when the knob is at zero (a perfectly focused,
            # i.e. digital, picture). A wide spot goes to the half-size buffers instead -
            # the first pass then doubles as the downsample, and the result is upscaled
            # again by the linear filter when the tube pass reads it.
            sigma = max(0.0, self.ascii.crt_blur) * lvl["blur"] * dpr
            if sigma > 0.02:
                half = sigma > CRT_BLUR_HALF_PX * dpr
                buf = self._focus_half if half else self._focus
                tw, th = buf[0].width(), buf[0].height()
                s_px = sigma * 0.5 if half else sigma
                prog, u = self._crt_progs["focus"]
                prog.bind()
                prog.setUniformValue(u["u_res"], QVector2D(float(tw), float(th)))
                prog.setUniformValue(u["u_dir"], QVector2D(1.0 / tw, 0.0))
                prog.setUniformValue(u["u_sigma"], float(s_px))
                self._run_pass(gl, buf[0].handle(), tw, th, (lit,))
                prog.setUniformValue(u["u_dir"], QVector2D(0.0, 1.0 / th))
                prog.setUniformValue(u["u_sigma"], float(s_px * CRT_BLUR_ASPECT))
                self._run_pass(gl, buf[1].handle(), tw, th, (buf[0].texture(),))
                prog.release()
                lit = buf[1].texture()
            # 3. bloom: highlight-weighted half-size copy, blurred horizontally then vertically.
            # Taps two px apart with linear filtering so every source pixel is seen once.
            bw, bh = self._bloom[0].width(), self._bloom[0].height()
            prog, u = self._crt_progs["blur"]
            prog.bind()
            prog.setUniformValue(u["u_res"], QVector2D(float(bw), float(bh)))
            prog.setUniformValue(u["u_dir"], QVector2D(2.0 * dpr / fw, 0.0))
            prog.setUniformValue(u["u_prep"], 1)
            self._run_pass(gl, self._bloom[0].handle(), bw, bh, (lit,))
            prog.setUniformValue(u["u_dir"], QVector2D(0.0, dpr / bh))
            prog.setUniformValue(u["u_prep"], 0)
            self._run_pass(gl, self._bloom[1].handle(), bw, bh, (self._bloom[0].texture(),))
            prog.release()
            # 4. the tube itself, onto the screen. Scanlines: a whole number per character
            # row; on the pixel grids of the Bayer filter a whole number of grid rows per
            # scanline instead, so the lines never beat against the dither pattern; on plain
            # video a whole number of lines over the picture, like a real tube's raster.
            if kind == "ascii":
                scan_period = cell_y / max(1, int(round(cell_y / (4.0 * dpr))))
            elif kind == "video":
                lines = max(1, min(CRT_VIDEO_LINES, int(rect[3] / (CRT_SCAN_MIN_PX * dpr))))
                scan_period = rect[3] / lines
            else:
                scan_period = cell_y * max(1, int(round(3.0 * dpr / cell_y)))
            prog, u = self._crt_progs["crt"]
            prog.bind()
            prog.setUniformValue(u["u_res"], QVector2D(float(fw), float(fh)))
            prog.setUniformValue(u["u_rect"], QVector4D(*(float(v) for v in rect)))
            prog.setUniformValue(u["u_curve"], float(lvl["curve"]))
            prog.setUniformValue(u["u_corner"], float(0.035 * min(rect[2], rect[3])))
            prog.setUniformValue(u["u_mask"], 0.0 if vector else float(lvl["mask"]))
            prog.setUniformValue(u["u_mask_px"], float(max(1, round(dpr))))
            prog.setUniformValue(u["u_scan"], 0.0 if vector else float(lvl["scan"]))
            prog.setUniformValue(u["u_scan_period"], float(scan_period))
            prog.setUniformValue(u["u_bloom_amt"], float(lvl["bloom"] * (1.3 if vector else 1.0)))
            prog.setUniformValue(u["u_grain"], float(lvl["grain"]))
            prog.setUniformValue(u["u_hum"], float(lvl["hum"]))
            prog.setUniformValue(u["u_vignette"], float(lvl["vignette"]))
            prog.setUniformValue(u["u_aberr"], float(lvl["aberr"] * max(0.0, self.ascii.crt_aberr) * dpr))
            prog.setUniformValue(u["u_time"], float((now - self._crt_t0) % 3600.0))
            prog.setUniformValue(u["u_seed"], int(self._crt_seed))
            self._run_pass(gl, fbo, fw, fh, (lit, self._bloom[1].texture()))
            prog.release()
            gl.ActiveTexture(GL_TEXTURE1)
            gl.BindTexture(GL_TEXTURE_2D, 0)
            gl.ActiveTexture(GL_TEXTURE0)
            gl.BindTexture(GL_TEXTURE_2D, 0)


class PlaylistView(QListWidget):
    """The playlist panel's list. Rows mirror mpv's playlist (rebuilt from the `playlist`
    property whenever mpv changes it), so every edit is sent to mpv as a command and the
    list follows - the widget never keeps state of its own. Drag rows to reorder, drop
    files/URLs from outside to append, double-click to play, Delete to remove."""
    files_dropped = pyqtSignal(list)
    move_requested = pyqtSignal(int, int)      # (from, to) in mpv playlist-move terms
    remove_requested = pyqtSignal(list)        # row indices
    play_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setUniformItemSizes(True)
        self.itemActivated.connect(lambda item: self.play_requested.emit(self.row(item)))

    def _external(self, event):
        return event.source() is not self and event.mimeData().hasUrls()

    def dragEnterEvent(self, event):
        if self._external(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._external(event):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if self._external(event):
            paths = [u.toLocalFile() if u.isLocalFile() else u.toString() for u in event.mimeData().urls()]
            event.acceptProposedAction()
            self.files_dropped.emit([p for p in paths if p])
            return
        # internal reorder: work out where the row would land, tell mpv, and let the
        # playlist property change rebuild the list (so Qt must not move anything itself)
        rows = sorted(self.row(i) for i in self.selectedItems())
        if not rows:
            event.ignore()
            return
        target = self.indexAt(event.position().toPoint()).row()
        pos = self.dropIndicatorPosition()
        if target < 0 or pos == QAbstractItemView.DropIndicatorPosition.OnViewport:
            target = self.count()
        elif pos == QAbstractItemView.DropIndicatorPosition.BelowItem:
            target += 1
        event.ignore()
        src = rows[0]   # one row at a time keeps mpv's index arithmetic simple
        if target not in (src, src + 1):
            self.move_requested.emit(src, target)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            rows = sorted(self.row(i) for i in self.selectedItems())
            if rows:
                self.remove_requested.emit(rows)
            return
        super().keyPressEvent(event)


class ClickSeekSlider(QSlider):
    """A QSlider where clicking anywhere on the groove jumps straight to that position.

    Qt's default QSlider only does that on some styles (e.g. GTK); on others (Fusion,
    most Qt/KDE themes) a plain click instead nudges the value by one page step, and only
    dragging the handle moves it freely - not what a seek bar should do. This replaces the
    press/move/release handling entirely so both a click and a drag always seek, on every
    platform and style, while still firing the same sliderMoved/sliderReleased signals the
    rest of the app already listens to."""

    def _value_at(self, event):
        ratio = event.position().x() / max(1, self.width())
        ratio = min(1.0, max(0.0, ratio))
        return round(self.minimum() + ratio * (self.maximum() - self.minimum()))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.setSliderDown(True)
        value = self._value_at(event)
        self.setValue(value)
        self.sliderMoved.emit(value)
        event.accept()

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        value = self._value_at(event)
        self.setValue(value)
        self.sliderMoved.emit(value)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        value = self._value_at(event)
        self.setValue(value)
        self.setSliderDown(False)  # emits sliderReleased()
        event.accept()


class CrtDialog(QDialog):
    """The CRT screen panel (Ctrl+G): the filter on/off, its intensity, and the three knobs
    an intensity level only sets the starting point for - focus blur, phosphor trail (the
    smudge behind moving things) and chromatic aberration. Modeless and always on top of
    the player, so the picture behind it changes while the sliders move."""

    TIPS = {
        "crt_blur": "How sharply the electron beam is focused. Up: a soft, slightly out-of-focus tube.\n"
                    "Down to zero: a perfectly sharp, digital picture.",
        "crt_trail": "How long the phosphor keeps glowing after the beam has passed, so bright\n"
                     "moving things smear behind themselves. Down to zero: no trail at all.",
        "crt_aberr": "Colour convergence error: the red and blue guns landing slightly off the\n"
                     "green one, a little everywhere and much more towards the edges.",
    }

    def __init__(self, win):
        super().__init__(win, Qt.WindowType.Tool)
        self.win = win
        self.setWindowTitle("CRT screen")
        self.setStyleSheet("QDialog { background: #101010; } QLabel { color: #d0d0d0; }")
        col = QVBoxLayout(self)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.on_btn = QToolButton()
        self.on_btn.setText("CRT")
        self.on_btn.setCheckable(True)
        self.on_btn.setToolTip("CRT screen on/off (g)")
        self.on_btn.clicked.connect(lambda: win.toggle_crt())
        top.addWidget(self.on_btn)
        top.addWidget(QLabel("intensity"))
        self.level_combo = QComboBox()
        for name in CRT_LEVEL_NAMES:
            self.level_combo.addItem(name)
        self.level_combo.setToolTip("How strong the whole CRT look is - and the starting point the three "
                                    "knobs below scale (Shift+G)")
        self.level_combo.currentIndexChanged.connect(win.set_crt_level)
        top.addWidget(self.level_combo, 1)
        col.addLayout(top)

        self.rows = {}
        for attr, label, _unit, key in CRT_KNOBS:
            name = QLabel(label)
            name.setMinimumWidth(78)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, int(round(CRT_KNOB_MAX / CRT_KNOB_STEP)))
            slider.setPageStep(4)
            slider.setFixedWidth(200)
            slider.valueChanged.connect(lambda v, a=attr: self._slider_moved(a, v))
            value = QLabel()
            value.setMinimumWidth(120)
            tip = f"{self.TIPS[attr]}\n\n{key} / {key.replace('Ctrl+', 'Ctrl+Shift+')} does the same from the video."
            for w in (name, slider, value):
                w.setToolTip(tip)
            row = QHBoxLayout()
            row.setSpacing(8)
            for w in (name, slider, value):
                row.addWidget(w)
            col.addLayout(row)
            self.rows[attr] = (slider, value)

        row = QHBoxLayout()
        row.setSpacing(8)
        name = QLabel("trail colour")
        name.setMinimumWidth(78)
        self.tint_combo = QComboBox()
        for tname in CRT_TINT_NAMES:
            self.tint_combo.addItem(tname)
        self.tint_combo.currentIndexChanged.connect(win.set_crt_tint)
        tip = ("What colour the trail glows as it fades. \"auto\" keeps whatever colour the picture\n"
               "had - which in the green/amber/mono colour modes is already that phosphor - and the\n"
               "rest force one, so a full-colour picture can still smear green.\n\n"
               "Ctrl+Shift+G steps through them from the video.")
        for w in (name, self.tint_combo):
            w.setToolTip(tip)
        row.addWidget(name)
        row.addWidget(self.tint_combo, 1)
        col.addLayout(row)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #8ce87a")
        col.addWidget(self.note)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        reset = QPushButton("Reset")
        reset.setToolTip("Blur, trail and aberration back to what the intensity level asks for (Ctrl+0)")
        reset.clicked.connect(win.reset_crt_knobs)
        buttons.addWidget(reset)
        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.hide)
        buttons.addWidget(close)
        col.addLayout(buttons)

    def _slider_moved(self, attr, value):
        self.win.set_crt_knob(attr, value * CRT_KNOB_STEP, flash=False)

    def refresh(self):
        """Pull the current state back out of the player (the keys change it too)."""
        self.on_btn.blockSignals(True)
        self.on_btn.setChecked(self.win.ascii.crt_on)
        self.on_btn.blockSignals(False)
        self.level_combo.blockSignals(True)
        self.level_combo.setCurrentIndex(self.win.ascii.crt_level)
        self.level_combo.blockSignals(False)
        self.tint_combo.blockSignals(True)
        self.tint_combo.setCurrentIndex(self.win.ascii.crt_tint)
        self.tint_combo.blockSignals(False)
        for attr, (slider, label) in self.rows.items():
            slider.blockSignals(True)
            slider.setValue(int(round(getattr(self.win.ascii, attr) / CRT_KNOB_STEP)))
            slider.blockSignals(False)
            label.setText(self.win.crt_knob_value_text(attr))
        if not self.win.video.crt_supported():
            self.note.setText("The CRT screen needs the OpenGL renderer, which is not available in this session.")
        elif not self.win.ascii.crt_on:
            self.note.setText("The CRT screen is off - turn it on to see any of this.")
        else:
            self.note.setText("Shown over the display filter, or straight over the video for a TV look.")


# --------------------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.setWindowTitle(APP_NAME)
        self.resize(1000, 640)
        self.setAcceptDrops(True)

        self.use_gl = HAVE_GL and args.renderer != "software"
        if args.renderer == "gl" and not HAVE_GL:
            raise RuntimeError("--renderer gl: PyQt6's QtOpenGL/QtOpenGLWidgets modules are not installed")
        self.engine = Engine(hwdec=args.hwdec, gl=self.use_gl, ytdl_format=args.ytdl_format,
                             ytdl_raw=Engine.ytdl_raw_options(args.ytdl_cookies_from_browser, args.ytdl_client,
                                                              args.ytdl_raw_options))
        family = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        self.ascii = AsciiRenderer(family, font_px=args.font_size)
        self.video = self._make_video_widget()
        start_filter = args.filter or ("ascii" if args.ascii else "off")
        self.video.ascii_mode = start_filter != "off"
        if start_filter != "off":
            self.ascii.filter = start_filter
        self.ascii.set_pixel_px(args.pixel_size)
        self.video.fps_log = bool(args.fps)
        self.ascii.crt_on = bool(args.crt)
        self.ascii.crt_level = CRT_LEVEL_NAMES.index(args.crt_level)
        for attr, value in (("crt_blur", args.crt_blur), ("crt_trail", args.crt_trail),
                            ("crt_aberr", args.crt_aberr)):
            setattr(self.ascii, attr, min(CRT_KNOB_MAX, max(0.0, value)))
        tint = args.crt_trail_color.lower()
        if tint not in CRT_TINT_NAMES:
            raise RuntimeError(f"--crt-trail-color: unknown colour {args.crt_trail_color!r} "
                               f"(pick one of {', '.join(CRT_TINT_NAMES)})")
        self.ascii.crt_tint = CRT_TINT_NAMES.index(tint)
        if args.color is not None:
            mode = args.color.lower()
            if mode not in COLOR_MODES:
                raise RuntimeError(f"--color: unknown mode {args.color!r} "
                                   f"(pick one of {', '.join(COLOR_MODES)})")
            self.ascii.color_mode = mode
        self.crt_dialog = None

        self.audio_mode = False       # current file has no real video -> visualiser
        self._ytdl_hint_until = 0.0   # while set, keep YTDL_BOT_HINT on screen (see _on_log)
        self.crop_index = 0           # index into CROP_RATIOS; 0 = no crop
        self.repeat_index = 0         # index into REPEAT_MODES
        self.shuffled = False         # playlist-shuffle applied (Ctrl+L toggles it back)
        self._playlist = []           # last `playlist` property value from mpv
        self._dock_was_visible = False
        self.viz_index = 0
        self.viz_aid = 1
        self.duration = 0.0
        self._time_pos = None
        self._time_ui_timer = QTimer(self)
        self._time_ui_timer.timeout.connect(self._refresh_time_ui)
        self._time_ui_timer.start(100)
        self._fs_timer = QTimer(self)
        self._fs_timer.setSingleShot(True)
        self._fs_timer.timeout.connect(self._hide_fs_ui)
        # When True (default), the seek bar fades in and stays up throughout fullscreen.
        # When False, it hides and reappears together with the rest of the controls instead.
        self.keep_seekbar_fullscreen = True

        self._build_controls()
        self._build_playlist()
        self._build_menus()

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.video, 1)
        lay.addWidget(self.seek_bar, 0)
        lay.addWidget(self.controls, 0)
        self.setCentralWidget(central)
        self.setStyleSheet("""
            QMainWindow, QWidget#controls { background: #101010; color: #d0d0d0; }
            QWidget#controls QLabel { color: #8ce87a; font-family: monospace; }
            QComboBox, QDoubleSpinBox { background: #1c1c1c; color: #d0d0d0; border: 1px solid #333; padding: 2px 4px; }
            QComboBox QAbstractItemView { background: #1c1c1c; color: #d0d0d0; selection-background-color: #2e5b2e; }
            QToolButton, QPushButton { background: #1c1c1c; color: #d0d0d0; border: 1px solid #333; padding: 3px 8px; }
            QToolButton:checked { background: #2e5b2e; color: #ffffff; }
            QSlider::groove:horizontal { height: 6px; background: #2a2a2a; border-radius: 3px; }
            QSlider::handle:horizontal { width: 12px; margin: -4px 0; background: #8ce87a; border-radius: 6px; }
            QSlider::sub-page:horizontal { background: #3f8f3a; border-radius: 3px; }
            QMenuBar { background: #101010; color: #d0d0d0; }
            QMenuBar::item:selected { background: #2e5b2e; }
            QMenu { background: #1c1c1c; color: #d0d0d0; }
            QMenu::item:selected { background: #2e5b2e; }
            QDockWidget { color: #8ce87a; font-family: monospace; }
            QDockWidget::title { background: #161616; padding: 4px 8px; }
            QListWidget { background: #0c0c0c; color: #c8c8c8; border: 1px solid #333; font-family: monospace; }
            QListWidget::item:selected { background: #2e5b2e; color: #ffffff; }
            QListWidget::item:hover { background: #1e1e1e; }
        """)

        # engine signals
        self.engine.prop_changed.connect(self._on_prop)
        self.engine.file_loaded.connect(self._on_file_loaded)
        self.engine.file_ended.connect(self._on_file_ended)
        self.engine.log_message.connect(self._on_log)
        self._connect_video_widget(self.video)

        self.ramp_combo.setCurrentIndex(max(0, self.ramp_combo.findData(self.ascii.ramp_name)))
        self.res_combo.setCurrentIndex(max(0, self.res_combo.findData(self.ascii.res_divider)))
        self.filter_combo.setCurrentIndex(max(0, self.filter_combo.findData(self.ascii.filter)))
        self._apply_ascii_state(flash=False)
        self._apply_crt_state(flash=False)
        # mpv can't show video until a render context exists; the GL one only comes into
        # being once the widget is on screen, so hold the command-line files until then.
        self._initial_files = list(args.files)
        if self.use_gl:
            self.video.render_ready.connect(self._open_initial_files)
        else:
            self._open_initial_files()

    # ------------------------------------------------------------------ video widget
    def _make_video_widget(self):
        if self.use_gl:
            w = GLVideoWidget(self.engine, self.ascii)
            w.gl_failed.connect(self._on_gl_failed)
            return w
        self.engine.init_render_sw()
        return SoftwareVideoWidget(self.engine, self.ascii)

    def _connect_video_widget(self, w):
        w.toggle_pause.connect(self.toggle_pause)
        w.toggle_fullscreen.connect(self.toggle_fullscreen)
        w.seek_relative.connect(self.seek_relative)

    def _open_initial_files(self):
        files, self._initial_files = self._initial_files, []
        for f in files:
            self.open_path(f, append=f is not files[0])

    def _on_gl_failed(self, message):
        """OpenGL is not usable here (no driver, remote display, ...): swap in the CPU renderer."""
        print(f"[warn] gl: {message}", file=sys.stderr)
        if self.args.renderer == "gl":
            self.video.flash(f"OpenGL renderer unavailable: {message}", 8)
            return
        print("[warn] gl: falling back to the software renderer (--renderer software to skip the attempt)",
              file=sys.stderr)
        old = self.video
        self.use_gl = False
        self.engine.free_render_ctx()
        if self.args.hwdec is None:
            self.engine.set("hwdec", "auto-copy")   # no GPU interop to hand direct-decoded frames to
        self.engine.init_render_sw()
        new = SoftwareVideoWidget(self.engine, self.ascii)
        new.copy_state_from(old)
        self._connect_video_widget(new)
        self.centralWidget().layout().replaceWidget(old, new)
        old.hide()
        old.deleteLater()
        self.video = new
        new.setFocus()
        new.flash("OpenGL unavailable - using the software renderer"
                  + (" (no CRT screen filter there)" if self.ascii.crt_on else ""), 4)
        self._open_initial_files()

    # ------------------------------------------------------------------ UI construction
    def _build_controls(self):
        # Two separate top-level widgets, not one - so in fullscreen the seek bar can stay
        # visible (fading in on its own) independently of the rest of the controls, which
        # still hide after inactivity as before. Same objectName as the button row so the
        # existing "#controls" stylesheet rules cover both without changes.
        self.seek_bar = QWidget()
        self.seek_bar.setObjectName("controls")
        seek_row = QHBoxLayout(self.seek_bar)
        seek_row.setContentsMargins(8, 4, 8, 4)
        seek_row.setSpacing(8)
        self.seek_slider = ClickSeekSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 10000)
        self.seek_slider.setToolTip("Seek")
        self.seek_slider.sliderReleased.connect(self._slider_seek)
        self.seek_slider.sliderMoved.connect(self._slider_preview)
        seek_row.addWidget(self.seek_slider, 1)

        self.seek_opacity = QGraphicsOpacityEffect(self.seek_bar)
        self.seek_opacity.setOpacity(1.0)
        self.seek_bar.setGraphicsEffect(self.seek_opacity)
        # A graphics effect makes Qt render the widget through an offscreen pixmap on every
        # repaint, which is measurably slower next to the GL video widget; only keep it
        # switched on while a fade is actually in progress.
        self.seek_opacity.opacityChanged.connect(lambda v: self.seek_opacity.setEnabled(v < 1.0))
        self.seek_opacity.setEnabled(False)
        self.seek_fade = QPropertyAnimation(self.seek_opacity, b"opacity", self)
        self.seek_fade.setDuration(350)
        self.seek_fade.setStartValue(0.0)
        self.seek_fade.setEndValue(1.0)

        self.controls = QWidget()
        self.controls.setObjectName("controls")
        lay = QHBoxLayout(self.controls)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)

        self.play_btn = QToolButton()
        self.play_btn.setText("▶")
        self.play_btn.setToolTip("Play/Pause (Space)")
        self.play_btn.clicked.connect(self.toggle_pause)
        lay.addWidget(self.play_btn)

        self.time_label = QLabel("--:-- / --:--")
        lay.addWidget(self.time_label)
        lay.addStretch(1)

        lay.addWidget(QLabel("speed"))
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.1, 8.0)
        self.speed_spin.setSingleStep(0.25)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setValue(1.0)
        self.speed_spin.setSuffix("×")
        self.speed_spin.setToolTip("Playback speed ([ ] keys, Backspace resets)")
        self.speed_spin.valueChanged.connect(lambda v: self.engine.set("speed", float(v)))
        lay.addWidget(self.speed_spin)

        lay.addWidget(QLabel("audio"))
        self.audio_combo = QComboBox()
        self.audio_combo.setToolTip("Audio track (a)")
        self.audio_combo.currentIndexChanged.connect(self._audio_combo_changed)
        lay.addWidget(self.audio_combo)

        lay.addWidget(QLabel("subs"))
        self.sub_combo = QComboBox()
        self.sub_combo.setToolTip("Subtitle track (j)")
        self.sub_combo.currentIndexChanged.connect(self._sub_combo_changed)
        lay.addWidget(self.sub_combo)

        self.viz_label = QLabel("viz")
        lay.addWidget(self.viz_label)
        self.viz_combo = QComboBox()
        for name, _ in VISUALIZERS:
            self.viz_combo.addItem(name)
        self.viz_combo.setToolTip("Audio visualiser (v)")
        self.viz_combo.currentIndexChanged.connect(self.set_visualizer)
        lay.addWidget(self.viz_combo)
        self.viz_label.hide()
        self.viz_combo.hide()

        self.filter_combo = QComboBox()
        for name, _label in FILTERS:
            self.filter_combo.addItem(FILTER_SHORT[name], name)
        self.filter_combo.setToolTip("Display filter: ASCII art, Bayer 1-bit dithering (2x2 / 4x4 / 8x8 matrix) "
                                     "or a vector display drawing the picture's edges (t cycles through them)")
        # size to the longest entry, not to a fixed sample string, but no wider than that
        self.filter_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.filter_combo.currentIndexChanged.connect(self._filter_combo_changed)
        lay.addWidget(self.filter_combo)

        self.ascii_btn = QToolButton()
        self.ascii_btn.setText("ASCII")
        self.ascii_btn.setCheckable(True)
        self.ascii_btn.setToolTip("Display filter on/off (Shift+T; t cycles through the filters)")
        self.ascii_btn.clicked.connect(self.toggle_ascii)
        # fixed to the widest of the three captions so switching filters never shifts the row
        _fm = QFontMetrics(self.ascii_btn.font())
        self.ascii_btn.setFixedWidth(max(_fm.horizontalAdvance(t) for t in FILTER_BUTTON.values()) + 26)
        lay.addWidget(self.ascii_btn)

        self.crt_btn = QToolButton()
        self.crt_btn.setText("CRT")
        self.crt_btn.setCheckable(True)
        self.crt_btn.setToolTip("CRT screen over the picture - with a display filter under it or on plain "
                                "video, for a TV look: curved glass, shadow mask, scanlines, focus blur, "
                                "bloom, grain, phosphor trail (g; Shift+G for the intensity, Ctrl+G for the "
                                "blur / trail / aberration knobs)")
        self.crt_btn.clicked.connect(self.toggle_crt)
        lay.addWidget(self.crt_btn)

        lay.addWidget(QLabel("chars"))
        self.ramp_combo = QComboBox()
        for name in CHAR_RAMPS:
            self.ramp_combo.addItem(f"{name} ({len(CHAR_RAMPS[name])})", name)
        self.ramp_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.ramp_combo.setToolTip("Character set for the ASCII filter, from just a few characters to a lot (r)")
        self.ramp_combo.currentIndexChanged.connect(self._ramp_combo_changed)
        lay.addWidget(self.ramp_combo)

        lay.addWidget(QLabel("res"))
        self.res_combo = QComboBox()
        for label, divider in RES_DIVIDERS:
            self.res_combo.addItem(label, divider)
        self.res_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.res_combo.setToolTip("Resolution divider: fewer, bigger characters / dither pixels - "
                                  "lower detail renders faster (d)")
        self.res_combo.currentIndexChanged.connect(self._res_combo_changed)
        lay.addWidget(self.res_combo)

        self.mute_btn = QToolButton()
        self.mute_btn.setText("vol")
        self.mute_btn.setToolTip("Mute (m)")
        self.mute_btn.clicked.connect(self.toggle_mute)
        lay.addWidget(self.mute_btn)
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 130)
        self.vol_slider.setValue(100)
        self.vol_slider.setFixedWidth(90)
        self.vol_slider.setToolTip("Volume (+/-)")
        self.vol_slider.valueChanged.connect(lambda v: self.engine.set("volume", float(v)))
        lay.addWidget(self.vol_slider)

        for w in (self.play_btn, self.seek_slider, self.speed_spin, self.audio_combo, self.sub_combo,
                  self.viz_combo, self.filter_combo, self.ascii_btn, self.crt_btn, self.ramp_combo, self.res_combo,
                  self.mute_btn, self.vol_slider):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _build_playlist(self):
        """The playlist panel: a dock on the right, hidden until `l` / Playback > Playlist."""
        self.playlist_view = PlaylistView()
        self.playlist_view.files_dropped.connect(self.add_to_playlist)
        self.playlist_view.move_requested.connect(self.move_playlist_entry)
        self.playlist_view.remove_requested.connect(self.remove_playlist_rows)
        self.playlist_view.play_requested.connect(self.play_playlist_index)

        def tool(text, tip, slot, checkable=False):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.clicked.connect(slot)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            return b

        row1 = QHBoxLayout()
        row1.setSpacing(4)
        for b in (tool("+ files", "Add files to the playlist (Shift+O)", self.add_files_dialog),
                  tool("+ URL", "Add a URL to the playlist", self.add_url_dialog),
                  tool("−", "Remove the selected entries (Delete)", self.remove_selected_playlist),
                  tool("clear", "Remove everything except what is playing", self.clear_playlist),
                  tool("▲", "Move the selected entry up", lambda: self.nudge_playlist_entry(-1)),
                  tool("▼", "Move the selected entry down", lambda: self.nudge_playlist_entry(1))):
            row1.addWidget(b)
        row1.addStretch(1)
        row2 = QHBoxLayout()
        row2.setSpacing(4)
        self.repeat_btn = tool("repeat: off", "Repeat mode: off / all / one (Shift+L)", self.cycle_repeat)
        self.shuffle_btn = tool("shuffle", "Shuffle the playlist; click again to restore the order (Ctrl+L)",
                                self.toggle_shuffle, checkable=True)
        row2.addWidget(self.repeat_btn)
        row2.addWidget(self.shuffle_btn)
        row2.addStretch(1)
        row2.addWidget(tool("save .m3u", "Save the playlist as an M3U file", self.save_playlist_dialog))

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)
        lay.addWidget(self.playlist_view, 1)
        lay.addLayout(row1)
        lay.addLayout(row2)
        self.playlist_dock = QDockWidget("Playlist", self)
        self.playlist_dock.setObjectName("playlist")
        self.playlist_dock.setWidget(body)
        self.playlist_dock.setMinimumWidth(260)
        self.playlist_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable
                                       | QDockWidget.DockWidgetFeature.DockWidgetMovable
                                       | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.playlist_dock)
        self.playlist_dock.hide()
        self.playlist_dock.visibilityChanged.connect(self._playlist_visibility_changed)

    def _act(self, menu, text, shortcut, slot, checkable=False):
        a = QAction(text, self)
        if shortcut:
            if isinstance(shortcut, (list, tuple)):
                a.setShortcuts([QKeySequence(s) for s in shortcut])
            else:
                a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        a.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        menu.addAction(a)
        self.addAction(a)
        return a

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&File")
        self._act(m, "Open file(s)…", "O", self.open_dialog)
        self._act(m, "Open URL…", "Ctrl+U", self.open_url_dialog)
        self._act(m, "Add subtitle file…", "Ctrl+J", self.open_subtitle_dialog)
        m.addSeparator()
        self._act(m, "Save ASCII frame as text…", "S", self.save_ascii_frame)
        self._act(m, "Save screenshot as JPG…", "Ctrl+C", self.save_screenshot)
        self._act(m, "Copy ASCII frame to clipboard", None, self.copy_ascii_frame)
        m.addSeparator()
        self._act(m, "Quit", ["Q", "Ctrl+Q"], self.close)

        m = mb.addMenu("&Playback")
        self._act(m, "Play / Pause", ["Space", "K", "P"], self.toggle_pause)
        self._act(m, "Stop", "Ctrl+S", self.stop)
        m.addSeparator()
        self._act(m, "Seek -5 s", "Left", lambda: self.seek_relative(-5))
        self._act(m, "Seek +5 s", "Right", lambda: self.seek_relative(5))
        self._act(m, "Seek -60 s", "Down", lambda: self.seek_relative(-60))
        self._act(m, "Seek +60 s", "Up", lambda: self.seek_relative(60))
        self._act(m, "Previous frame", ",", lambda: self.engine.command("frame-back-step"))
        self._act(m, "Next frame", ".", lambda: self.engine.command("frame-step"))
        m.addSeparator()
        self._act(m, "Speed slower", "[", lambda: self.change_speed(1 / 1.1))
        self._act(m, "Speed faster", "]", lambda: self.change_speed(1.1))
        self._act(m, "Speed halve", "{", lambda: self.change_speed(0.5))
        self._act(m, "Speed double", "}", lambda: self.change_speed(2.0))
        self._act(m, "Speed reset", "Backspace", lambda: self.set_speed(1.0))
        m.addSeparator()
        self._act(m, "Previous in playlist", ["PgUp", "<"], lambda: self.engine.command("playlist-prev"))
        self._act(m, "Next in playlist", ["PgDown", ">"], lambda: self.engine.command("playlist-next"))
        m.addSeparator()
        self.playlist_action = self._act(m, "Playlist panel", "L", self.toggle_playlist, checkable=True)
        self._act(m, "Add files to playlist…", "Shift+O", self.add_files_dialog)
        self._act(m, "Add URL to playlist…", None, self.add_url_dialog)
        self._act(m, "Save playlist as M3U…", None, self.save_playlist_dialog)
        self._act(m, "Clear playlist", None, self.clear_playlist)
        self._act(m, "Next repeat mode (off / all / one)", "Shift+L", self.cycle_repeat)
        self.repeat_menu = m.addMenu("Repeat")
        self.repeat_actions = []
        for i, (label, _, _) in enumerate(REPEAT_MODES):
            a = self._act(self.repeat_menu, label, None, lambda _=False, ix=i: self.set_repeat(ix), checkable=True)
            self.repeat_actions.append(a)
        self.repeat_actions[0].setChecked(True)
        self.shuffle_action = self._act(m, "Shuffle playlist", "Ctrl+L", self.toggle_shuffle, checkable=True)

        m = mb.addMenu("&Audio")
        self._act(m, "Next audio track", "A", lambda: self.cycle_track("audio"))
        self._act(m, "Mute", "M", self.toggle_mute)
        self._act(m, "Volume up", ["+", "="], lambda: self.change_volume(5))
        self._act(m, "Volume down", "-", lambda: self.change_volume(-5))
        self._act(m, "Next visualiser (audio files)", "V", self.next_visualizer)
        m.addSeparator()
        self.audio_menu = m.addMenu("Track")

        m = mb.addMenu("&Subtitles")
        self._act(m, "Next subtitle track", "J", lambda: self.cycle_track("sub"))
        self._act(m, "Subtitles off", "Shift+J", lambda: self.engine.set("sid", "no"))
        self._act(m, "Add subtitle file…", None, self.open_subtitle_dialog)
        self._act(m, "Subtitle delay -0.1 s", "Z", lambda: self.change_sub_delay(-0.1))
        self._act(m, "Subtitle delay +0.1 s", "X", lambda: self.change_sub_delay(0.1))
        m.addSeparator()
        self.sub_menu = m.addMenu("Track")

        m = mb.addMenu("&Video")
        self._act(m, "Next display filter (off / ASCII / Bayer 2×2, 4×4, 8×8 / vector)", "T", self.next_filter)
        self.ascii_action = self._act(m, "Display filter on/off", "Shift+T", self.toggle_ascii, checkable=True)
        self._act(m, "Cycle crop / aspect ratio", "C", self.cycle_crop)
        self._act(m, "Next colour mode", "E", self.next_color_mode)
        self._act(m, "Next character set (ASCII)", "R", self.next_ramp)
        self._act(m, "Next resolution (characters / dither pixels)", "D", self.next_res_divider)
        self._act(m, "Smaller characters / pixels", ["Ctrl+-", "Ctrl+_"], lambda: self.change_font_px(-1))
        self._act(m, "Bigger characters / pixels", ["Ctrl+=", "Ctrl++"], lambda: self.change_font_px(1))
        m.addSeparator()
        self.crt_action = self._act(m, "CRT screen (over the display filter, or over plain video)", "G",
                                    self.toggle_crt, checkable=True)
        self._act(m, "Next CRT intensity", "Shift+G", self.next_crt_level)
        self._act(m, "CRT screen settings…", "Ctrl+G", self.show_crt_dialog)
        m.addSeparator()
        self.crop_menu = m.addMenu("Crop / aspect ratio")
        for i, (label, _) in enumerate(CROP_RATIOS):
            self._act(self.crop_menu, label, None, lambda _=False, ix=i: self.set_crop(ix))
        self.filter_menu = m.addMenu("Display filter")
        self.filter_actions = {}
        for name, label in [("off", "off")] + FILTERS:
            self.filter_actions[name] = self._act(self.filter_menu, label, None,
                                                  lambda _=False, nm=name: self.set_filter(nm), checkable=True)
        self.color_menu = m.addMenu("Colour mode")
        for mode in COLOR_MODES:
            self._act(self.color_menu, COLOR_MODE_LABELS[mode], None, lambda _=False, md=mode: self.set_color_mode(md))
        self.ramp_menu = m.addMenu("Character set")
        for name in CHAR_RAMPS:
            self._act(self.ramp_menu, name, None, lambda _=False, nm=name: self.set_ramp(nm))
        self.res_menu = m.addMenu("Resolution")
        for label, divider in RES_DIVIDERS:
            self._act(self.res_menu, label, None, lambda _=False, dv=divider: self.set_res_divider(dv))
        self.crt_menu = m.addMenu("CRT screen")
        for i, name in enumerate(CRT_LEVEL_NAMES):
            self._act(self.crt_menu, name, None, lambda _=False, ix=i: self.set_crt_level(ix))
        # the three live knobs (see CRT_KNOBS); their shortcuts work everywhere, dialog included
        self.crt_menu.addSeparator()
        for attr, label, _unit, key in CRT_KNOBS:
            self._act(self.crt_menu, f"More CRT {label}", key, lambda _=False, a=attr: self.change_crt_knob(a, 1))
            self._act(self.crt_menu, f"Less CRT {label}", key.replace("Ctrl+", "Ctrl+Shift+"),
                      lambda _=False, a=attr: self.change_crt_knob(a, -1))
        self._act(self.crt_menu, "Reset CRT blur / trail / aberration", "Ctrl+0", self.reset_crt_knobs)
        self.crt_menu.addSeparator()
        self._act(self.crt_menu, "Next CRT trail colour", "Ctrl+Shift+G", self.next_crt_tint)
        tint_menu = self.crt_menu.addMenu("Trail colour")
        for i, name in enumerate(CRT_TINT_NAMES):
            self._act(tint_menu, name, None, lambda _=False, ix=i: self.set_crt_tint(ix))
        self.viz_menu = m.addMenu("Audio visualiser")
        for i, (name, _) in enumerate(VISUALIZERS):
            self._act(self.viz_menu, name, None, lambda _=False, ix=i: self.set_visualizer(ix))

        m = mb.addMenu("&View")
        self._act(m, "Fullscreen", ["F", "F11"], self.toggle_fullscreen)
        self._act(m, "Leave fullscreen", "Escape", self.leave_fullscreen)
        self.keep_seekbar_action = self._act(
            m, "Keep seek bar visible in fullscreen", "B", self.toggle_keep_seekbar, checkable=True)
        self.keep_seekbar_action.setChecked(self.keep_seekbar_fullscreen)
        m.addSeparator()
        self._act(m, "Keyboard shortcuts", ["H", "F1"], self.show_help)
        self._act(m, "About asciiplay", None, self.show_about)

    # ------------------------------------------------------------------ opening files
    def open_path(self, path, append=False):
        """Open a local file (media or subtitle) or a URL."""
        if path.startswith(("http://", "https://", "rtsp://", "rtmp://", "ftp://")):
            host = QUrl(path).host().lower()
            direct = path.lower().rsplit("?", 1)[0].endswith(
                (".mp4", ".mkv", ".webm", ".mp3", ".flac", ".ogg", ".opus", ".wav", ".m4a", ".aac", ".m3u8", ".ts"))
            if not direct and not self.engine.ytdl_tool and path.startswith("http"):
                self.video.flash("playing sites like YouTube needs yt-dlp - install it (e.g. sudo dnf install yt-dlp) "
                                 "and start asciiplay again", 8)
                return
            self._load_media(path, append)
            if not direct and self.engine.ytdl_tool:
                self.video.flash(f"resolving {host or 'URL'} with yt-dlp…", 6)
            return
        if path.startswith("file://"):
            # a desktop launcher ("Open With", double-click, %U in a .desktop Exec=) hands
            # us file:// URIs, not plain paths - unwrap those back into a real filesystem
            # path (also undoes the %-encoding, e.g. spaces as %20).
            local = QUrl(path).toLocalFile()
            if local:
                path = local
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(path):
            self.video.flash(f"not found: {path}")
            return
        ext = os.path.splitext(path)[1].lower()
        if ext in SUB_EXT and self.video.has_media:
            self.engine.command("sub-add", path, "select")
            self.video.flash(f"subtitle added: {os.path.basename(path)}")
            return
        self._load_media(path, append)

    def _load_media(self, target, append):
        if append and self.video.has_media:
            self.engine.command("loadfile", target, "append-play")
            self.video.flash(f"queued: {os.path.basename(target)}")
        else:
            self.engine.set("lavfi-complex", "")
            self.audio_mode = False
            self.engine.command("loadfile", target, "replace")
            self.engine.set("pause", False)
            self._set_shuffled(False)

    def open_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Open media", "", MEDIA_FILTER)
        for i, f in enumerate(files):
            self.open_path(f, append=i > 0)

    def open_subtitle_dialog(self):
        f, _ = QFileDialog.getOpenFileName(self, "Add subtitle", "", SUB_FILTER)
        if f:
            self.engine.command("sub-add", f, "select")

    def open_url_dialog(self):
        url, ok = QInputDialog.getText(self, "Open URL", "URL:")
        if ok and url.strip():
            self.open_path(url.strip())

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        md = event.mimeData()
        items = []
        if md.hasUrls():
            for url in md.urls():
                items.append(url.toLocalFile() if url.isLocalFile() else url.toString())
        elif md.hasText():
            items = [ln.strip() for ln in md.text().splitlines() if ln.strip()]
        first = True
        for item in items:
            ext = os.path.splitext(item)[1].lower()
            is_sub = ext in SUB_EXT and not item.startswith("http")
            self.open_path(item, append=not first and not is_sub)
            if not is_sub:
                first = False
        event.acceptProposedAction()

    # ------------------------------------------------------------------ engine events
    def _on_file_loaded(self):
        self.video.has_media = True
        self.video.sub_text = ""
        if self.crop_index:                     # a new file: drop any crop from the last one
            self.crop_index = 0
        self.engine.set("vf", "")
        real_video = self.engine.has_real_video()
        audio_tracks = self.engine.tracks("audio")
        if not real_video and audio_tracks:
            self.audio_mode = True
            aid = self.engine.prop("aid")
            # mpv reports False ("no") for a moment when a file is (re)started - and False
            # is an int to isinstance(), which once produced a "[aidFalse]" filter graph
            self.viz_aid = aid if isinstance(aid, int) and not isinstance(aid, bool) and aid > 0 else audio_tracks[0]["id"]
            self._apply_visualizer()
        else:
            self.audio_mode = False
            # Moving on from an audio file inside the playlist: the visualiser graph is
            # still installed and its [vo] output would replace this file's real video,
            # so take it down (a fresh "open" clears it before loading; playlist advances
            # don't go through that path).
            if self.engine.prop("lavfi-complex", ""):
                self.engine.set("lavfi-complex", "")
                # mpv leaves the tracks the graph had taken over deselected, and "auto"
                # does not bring them back at this point - pick them by id
                def pick(tracks):
                    tracks = [t for t in tracks if not t.get("albumart")]
                    if not tracks:
                        return "no"
                    return next((t["id"] for t in tracks if t.get("default")), tracks[0]["id"])
                self.engine.set("vid", pick(self.engine.tracks("video")))
                self.engine.set("aid", pick(audio_tracks))
        self.viz_label.setVisible(self.audio_mode)
        self.viz_combo.setVisible(self.audio_mode)
        self._apply_ascii_state(flash=False)
        self._refresh_tracks()
        title = self.engine.prop("media-title", "")
        self.setWindowTitle(f"{title} - {APP_NAME}" if title else APP_NAME)
        kind = "audio → ASCII visualiser" if self.audio_mode else "video"
        self.video.flash(f"{title}\n{kind}")

    def _on_file_ended(self, reason):
        if reason in ("error",) and time.monotonic() >= self._ytdl_hint_until:
            self.video.flash("could not play this file")
        if self.engine.prop("playlist-count", 0) == 0 or reason == "stop":
            self.video.has_media = False
            self.video.update()

    def _on_prop(self, name, value):
        if name == "time-pos":
            # mpv reports this once per video frame. Repainting the seek bar and time label
            # that often is the single biggest drag on fullscreen frame rate (every raster
            # repaint next to the GL video makes Qt recomposite the whole window), so just
            # note the value here and let a 10 Hz timer push it into the widgets.
            self._time_pos = value
        elif name == "duration":
            self.duration = float(value or 0)
            self.seek_slider.setEnabled(self.duration > 0)
        elif name == "pause":
            self.play_btn.setText("▶" if value else "⏸")
            self.video.paused = bool(value)
            self.video.update()   # the GL widget keeps its CRT idle timer in step from paintGL
        elif name == "speed":
            if value is not None:
                self.speed_spin.blockSignals(True)
                self.speed_spin.setValue(float(value))
                self.speed_spin.blockSignals(False)
        elif name == "volume":
            if value is not None:
                self.vol_slider.blockSignals(True)
                self.vol_slider.setValue(int(value))
                self.vol_slider.blockSignals(False)
        elif name == "mute":
            self.mute_btn.setText("MUTE" if value else "vol")
        elif name in ("track-list", "aid", "sid"):
            self._refresh_tracks()
        elif name == "sub-text":
            self.video.sub_text = value or ""
            if self.video.ascii_active:
                self.video.update()
        elif name == "media-title":
            if value:
                self.setWindowTitle(f"{value} - {APP_NAME}")
        elif name == "video-out-params":
            self.video.render_now()
        elif name == "playlist":
            self._playlist = list(value or [])
            self._refresh_playlist()
        elif name == "playlist-pos":
            self._refresh_playlist()
        elif name in ("loop-playlist", "loop-file"):
            self._sync_repeat_ui()

    def _on_log(self, level, prefix, text):
        if level in ("error", "fatal"):
            low = text.lower()
            # matched loosely: the wording is YouTube's and it uses a typographic apostrophe
            if "confirm you" in low and "bot" in low:
                self.video.flash(ytdl_bot_hint(), 15)
                # yt-dlp's failure is followed by mpv's own "failed to recognize file
                # format", which would replace the hint on screen a moment later
                self._ytdl_hint_until = time.monotonic() + 15
            elif time.monotonic() >= self._ytdl_hint_until:
                self.video.flash(f"{prefix}: {text}", 4)
        print(f"[{level}] {prefix}: {text}", file=sys.stderr)

    # ------------------------------------------------------------------ tracks
    def _track_label(self, t):
        parts = []
        if t.get("title"):
            parts.append(t["title"])
        if t.get("lang"):
            parts.append(t["lang"])
        if t.get("codec"):
            parts.append(t["codec"])
        if t.get("external"):
            parts.append("ext")
        return f"{t['id']}: " + (" · ".join(parts) if parts else "track")

    def _refresh_tracks(self):
        for kind, combo, menu in (("audio", self.audio_combo, self.audio_menu), ("sub", self.sub_combo, self.sub_menu)):
            tracks = self.engine.tracks(kind)
            current = self.viz_aid if (kind == "audio" and self.audio_mode) else self.engine.prop("aid" if kind == "audio" else "sid")
            combo.blockSignals(True)
            combo.clear()
            menu.clear()
            combo.addItem("off", "no")
            sel = 0
            for t in tracks:
                combo.addItem(self._track_label(t), t["id"])
                if t["id"] == current:
                    sel = combo.count() - 1
            combo.setCurrentIndex(sel)
            combo.blockSignals(False)
            combo.setEnabled(len(tracks) > 0)
            group_items = [("off", "no")] + [(self._track_label(t), t["id"]) for t in tracks]
            for label, tid in group_items:
                a = QAction(label, self)
                a.setCheckable(True)
                a.setChecked(tid == current or (tid == "no" and current in (None, False, "no")))
                a.triggered.connect(lambda _=False, k=kind, i=tid: self.select_track(k, i))
                menu.addAction(a)

    def select_track(self, kind, tid):
        if kind == "audio":
            if self.audio_mode:
                if tid == "no":
                    return
                self.viz_aid = tid
                self._apply_visualizer()
            else:
                self.engine.set("aid", tid)
        else:
            self.engine.set("sid", tid)
        self._refresh_tracks()
        name = "audio" if kind == "audio" else "subtitles"
        self.video.flash(f"{name}: {'off' if tid == 'no' else self._track_label_by_id(kind, tid)}")

    def _track_label_by_id(self, kind, tid):
        for t in self.engine.tracks(kind):
            if t["id"] == tid:
                return self._track_label(t)
        return str(tid)

    def cycle_track(self, kind):
        tracks = self.engine.tracks(kind)
        if not tracks:
            self.video.flash(f"no {kind} tracks")
            return
        ids = [t["id"] for t in tracks]
        if kind == "sub":
            ids = ["no"] + ids
        current = self.viz_aid if (kind == "audio" and self.audio_mode) else self.engine.prop("aid" if kind == "audio" else "sid")
        try:
            nxt = ids[(ids.index(current) + 1) % len(ids)]
        except ValueError:
            nxt = ids[0]
        self.select_track(kind, nxt)

    def _audio_combo_changed(self, idx):
        if idx >= 0:
            self.select_track("audio", self.audio_combo.itemData(idx))

    def _sub_combo_changed(self, idx):
        if idx >= 0:
            self.select_track("sub", self.sub_combo.itemData(idx))

    def change_sub_delay(self, d):
        v = float(self.engine.prop("sub-delay", 0.0)) + d
        self.engine.set("sub-delay", v)
        self.video.flash(f"subtitle delay: {v:+.1f} s")

    # ------------------------------------------------------------------ playback
    def toggle_pause(self):
        if not self.video.has_media:
            return
        self.engine.set("pause", not self.engine.prop("pause", False))
        self.video.flash("paused" if self.engine.prop("pause") else "playing")

    def stop(self):
        self.engine.command("stop")
        self.video.has_media = False
        self.setWindowTitle(APP_NAME)
        self.video.update()

    def seek_relative(self, secs):
        if self.video.has_media:
            self.engine.command("seek", secs, "relative")
            self.video.flash(f"seek {secs:+.0f} s  →  {fmt_time((self.engine.prop('time-pos') or 0) + secs)}")

    def _slider_preview(self, value):
        if self.duration > 0:
            self._set_time_label(value / 10000 * self.duration)

    def _slider_seek(self):
        if self.duration > 0:
            self.engine.command("seek", self.seek_slider.value() / 10000 * self.duration, "absolute")

    def _set_time_label(self, pos):
        text = f"{fmt_time(pos)} / {fmt_time(self.duration)}"
        if text != self.time_label.text():
            self.time_label.setText(text)

    def _refresh_time_ui(self):
        value = self._time_pos
        if value is None or self.seek_slider.isSliderDown():
            return
        self._set_time_label(value)
        if self.duration > 0:
            v = int(value / self.duration * 10000)
            if v != self.seek_slider.value():
                self.seek_slider.blockSignals(True)
                self.seek_slider.setValue(v)
                self.seek_slider.blockSignals(False)

    def set_speed(self, v):
        v = max(0.1, min(8.0, v))
        self.engine.set("speed", v)
        self.video.flash(f"speed: {v:.2f}×")

    def change_speed(self, factor):
        self.set_speed(float(self.engine.prop("speed", 1.0)) * factor)

    def toggle_mute(self):
        self.engine.set("mute", not self.engine.prop("mute", False))

    def change_volume(self, d):
        v = max(0, min(130, int(self.engine.prop("volume", 100)) + d))
        self.engine.set("volume", v)
        self.video.flash(f"volume: {v}%")

    # ------------------------------------------------------------------ visualiser
    def _apply_visualizer(self):
        name, graph = VISUALIZERS[self.viz_index]
        graph = graph.format(W=VIZ_W, H=VIZ_H)
        # `format=rgb24` at the end matters: showwaves, showfreqs and avectorscope emit RGBA
        # with a transparent background, and libmpv (0.41) leaves stale colour behind in
        # fully transparent pixels - every frame kept everything earlier frames had drawn,
        # and it never went back to black. Making the frame opaque inside the graph, before
        # mpv sees it, is the reliable fix (the CLI ffmpeg shows the same graphs correctly).
        self.engine.set("lavfi-complex", f"[aid{self.viz_aid}]asplit[ao][a];[a]{graph},format=rgb24[vo]")
        self.viz_combo.blockSignals(True)
        self.viz_combo.setCurrentIndex(self.viz_index)
        self.viz_combo.blockSignals(False)

    def set_visualizer(self, index):
        self.viz_index = index % len(VISUALIZERS)
        if self.audio_mode:
            self._apply_visualizer()
            self.video.flash(f"visualiser: {VISUALIZERS[self.viz_index][0]}")
        else:
            self.video.flash(f"visualiser for audio files: {VISUALIZERS[self.viz_index][0]}")

    def next_visualizer(self):
        self.set_visualizer(self.viz_index + 1)

    # ------------------------------------------------------------------ ASCII
    # ------------------------------------------------------------------ playlist
    def _refresh_playlist(self):
        view = self.playlist_view
        selected = {view.row(i) for i in view.selectedItems()}
        current_row = view.currentRow()
        scroll = view.verticalScrollBar().value()
        view.blockSignals(True)
        view.clear()
        for i, entry in enumerate(self._playlist):
            name = entry.get("title") or entry.get("filename", "")
            if not entry.get("title") and not name.startswith(("http://", "https://", "rtsp://", "rtmp://")):
                name = os.path.basename(name) or name
            current = bool(entry.get("current"))
            item = QListWidgetItem(f"{'▶' if current else ' '} {i + 1:>3}  {name}")
            item.setToolTip(entry.get("filename", ""))
            if current:
                f = item.font()
                f.setBold(True)
                item.setFont(f)
                item.setForeground(QColor(140, 232, 122))
            view.addItem(item)
        if 0 <= current_row < view.count():
            # NoUpdate: restore the keyboard cursor without touching the selection
            view.setCurrentRow(current_row, QItemSelectionModel.SelectionFlag.NoUpdate)
        for i in selected:
            if i < view.count():
                view.item(i).setSelected(True)
        view.verticalScrollBar().setValue(scroll)
        view.blockSignals(False)
        n = len(self._playlist)
        self.playlist_dock.setWindowTitle(f"Playlist ({n})" if n else "Playlist")

    def _playlist_visibility_changed(self, visible):
        self.playlist_action.blockSignals(True)
        self.playlist_action.setChecked(visible)
        self.playlist_action.blockSignals(False)
        if self.isFullScreen():
            self._dock_was_visible = visible   # keep whatever the user chose in fullscreen

    def toggle_playlist(self):
        show = not self.playlist_dock.isVisible()
        self.playlist_dock.setVisible(show)
        if show:
            self.playlist_view.setFocus()
            if self._playlist:
                cur = next((i for i, e in enumerate(self._playlist) if e.get("current")), -1)
                if cur >= 0:
                    self.playlist_view.scrollToItem(self.playlist_view.item(cur))
        else:
            self.video.setFocus()

    def add_to_playlist(self, paths):
        """Append files/URLs; starts playing if nothing is loaded."""
        added = 0
        for p in paths:
            ext = os.path.splitext(p)[1].lower()
            if ext in SUB_EXT and not p.startswith("http"):
                self.open_path(p)   # a subtitle file goes to the current video, not the playlist
                continue
            if self.video.has_media or added:
                self.engine.command("loadfile", p if p.startswith(("http", "rtsp", "rtmp", "ftp")) else
                                    os.path.abspath(os.path.expanduser(p)), "append-play")
            else:
                self.open_path(p)
            added += 1
        if added:
            self.video.flash(f"added {added} to the playlist" if added > 1 else f"added: {os.path.basename(paths[0])}")

    def add_files_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add to playlist", "", MEDIA_FILTER)
        if files:
            self.add_to_playlist(files)

    def add_url_dialog(self):
        url, ok = QInputDialog.getText(self, "Add URL to playlist", "URL:")
        if ok and url.strip():
            self.add_to_playlist([url.strip()])

    def play_playlist_index(self, row):
        if 0 <= row < len(self._playlist):
            self.engine.command("playlist-play-index", row)
            self.engine.set("pause", False)

    def remove_playlist_rows(self, rows):
        for row in sorted(set(rows), reverse=True):   # highest first so indices stay valid
            if 0 <= row < len(self._playlist):
                self.engine.command("playlist-remove", row)

    def remove_selected_playlist(self):
        self.remove_playlist_rows([self.playlist_view.row(i) for i in self.playlist_view.selectedItems()])

    def clear_playlist(self):
        self.engine.command("playlist-clear")   # mpv keeps the entry that is playing
        self.video.flash("playlist cleared" + (" (except what is playing)" if self.video.has_media else ""))

    def move_playlist_entry(self, src, dst):
        """mpv's playlist-move: entry `src` takes the place in front of entry `dst`."""
        n = len(self._playlist)
        if 0 <= src < n and 0 <= dst <= n and dst not in (src, src + 1):
            self.engine.command("playlist-move", src, dst)

    def nudge_playlist_entry(self, direction):
        rows = sorted(self.playlist_view.row(i) for i in self.playlist_view.selectedItems())
        if not rows:
            return
        row = rows[0]
        if direction < 0 and row > 0:
            self.engine.command("playlist-move", row, row - 1)
            new = row - 1
        elif direction > 0 and row < len(self._playlist) - 1:
            self.engine.command("playlist-move", row + 1, row)   # pull the next one up = push this one down
            new = row + 1
        else:
            return
        # mpv's playlist update arrives asynchronously; keep the selection on the moved entry
        QTimer.singleShot(60, lambda: self._select_playlist_row(new))

    def _select_playlist_row(self, row):
        view = self.playlist_view
        if 0 <= row < view.count():
            view.clearSelection()
            view.setCurrentRow(row, QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def save_playlist_dialog(self):
        if not self._playlist:
            self.video.flash("the playlist is empty")
            return
        base = os.path.join(os.path.expanduser("~"), f"asciiplay_playlist_{time.strftime('%Y%m%d_%H%M%S')}.m3u")
        path, _ = QFileDialog.getSaveFileName(self, "Save playlist", base, "M3U playlist (*.m3u *.m3u8)")
        if not path:
            return
        lines = ["#EXTM3U"]
        for e in self._playlist:
            fn = e.get("filename", "")
            title = e.get("title") or os.path.basename(fn) or fn
            lines += [f"#EXTINF:-1,{title}", fn]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        self.video.flash(f"saved {path}  ({len(self._playlist)} entries)")

    # ---- repeat / shuffle ----
    def set_repeat(self, index):
        self.repeat_index = index % len(REPEAT_MODES)
        label, loop_playlist, loop_file = REPEAT_MODES[self.repeat_index]
        self.engine.set("loop-playlist", loop_playlist)
        self.engine.set("loop-file", loop_file)
        self._sync_repeat_ui()
        self.video.flash({"off": "repeat: off", "all": "repeat: whole playlist",
                          "one": "repeat: this file"}[label])

    def cycle_repeat(self):
        self.set_repeat(self.repeat_index + 1)

    def _sync_repeat_ui(self):
        lp = str(self.engine.prop("loop-playlist", "no"))
        lf = str(self.engine.prop("loop-file", "no"))
        # mpv reports False/"no" for off and "inf" (or a count) for on
        loop_file_on = lf not in ("no", "False", "0", "None")
        loop_pl_on = lp not in ("no", "False", "0", "None")
        self.repeat_index = 2 if loop_file_on else (1 if loop_pl_on else 0)
        label = REPEAT_MODES[self.repeat_index][0]
        self.repeat_btn.setText(f"repeat: {label}")
        for i, a in enumerate(self.repeat_actions):
            a.blockSignals(True)
            a.setChecked(i == self.repeat_index)
            a.blockSignals(False)

    def _set_shuffled(self, on):
        self.shuffled = on
        for w in (self.shuffle_btn, self.shuffle_action):
            w.blockSignals(True)
            w.setChecked(on)
            w.blockSignals(False)

    def toggle_shuffle(self):
        if len(self._playlist) < 2:
            self._set_shuffled(False)
            self.video.flash("nothing to shuffle - add more to the playlist")
            return
        if self.shuffled:
            self.engine.command("playlist-unshuffle")
            self._set_shuffled(False)
            self.video.flash("playlist order restored")
        else:
            self.engine.command("playlist-shuffle")
            self._set_shuffled(True)
            self.video.flash("playlist shuffled (Ctrl+L again restores the order)")

    def _apply_ascii_state(self, flash=True):
        """Push the display filter state (on/off + which of FILTERS) into every control."""
        self.video.forced_ascii = self.audio_mode
        active = self.video.ascii_active
        kind = self.ascii.filter
        label = FILTER_LABELS[kind]
        for w in (self.ascii_btn, self.ascii_action):
            w.blockSignals(True)
            w.setChecked(active)
            w.blockSignals(False)
        self.ascii_btn.setText(FILTER_BUTTON[kind])
        self.ascii_btn.setEnabled(not self.audio_mode)
        ix = self.filter_combo.findData(kind)
        if ix >= 0 and ix != self.filter_combo.currentIndex():
            self.filter_combo.blockSignals(True)
            self.filter_combo.setCurrentIndex(ix)
            self.filter_combo.blockSignals(False)
        for name, a in self.filter_actions.items():
            a.blockSignals(True)
            a.setChecked((name == kind) if active else (name == "off"))
            a.blockSignals(False)
        self.ramp_combo.setEnabled(kind == "ascii")
        # with a filter on mpv must not burn subtitles into the tiny frame; we draw them ourselves
        self.engine.set("sub-visibility", not active)
        self.video.render_now()
        if flash:
            if self.audio_mode:
                self.video.flash(f"filter: {label}  (audio files always show the visualiser)")
            else:
                self.video.flash("filter: " + (label if active else "off"))

    def toggle_ascii(self):
        """The filter button / Shift+T: the current display filter on or off."""
        if self.audio_mode:
            self._apply_ascii_state()
            return
        self.video.ascii_mode = not self.video.ascii_mode
        self._apply_ascii_state()

    def set_filter(self, name):
        """Switch to display filter `name` (one of FILTERS) or turn the filter "off"."""
        if name == "off":
            if not self.audio_mode:
                self.video.ascii_mode = False
        else:
            self.ascii.filter = name
            self.video.ascii_mode = True
        self._apply_ascii_state()

    def next_filter(self):
        """`t`: off -> ASCII -> Bayer 2x2 -> 4x4 -> 8x8 -> vector -> off (audio files, which
        always show a filtered visualiser, skip the "off" step)."""
        if not self.video.ascii_active:
            self.set_filter(FILTER_NAMES[0])
            return
        i = FILTER_NAMES.index(self.ascii.filter) + 1
        if i < len(FILTER_NAMES):
            self.set_filter(FILTER_NAMES[i])
        else:
            self.set_filter(FILTER_NAMES[0] if self.audio_mode else "off")

    def _filter_combo_changed(self, idx):
        if idx >= 0:
            self.set_filter(self.filter_combo.itemData(idx))

    def set_color_mode(self, mode):
        """The colour modes apply to the display filters and, with none of them on, to the
        video itself (green/amber/mono phosphor, greyscale, or one of the palettes)."""
        self.ascii.color_mode = mode
        self.video.render_now()
        msg = f"colour mode: {COLOR_MODE_LABELS.get(mode, mode)}"
        if not self.video.ascii_active and mode != "color" and not self.video.video_color_supported():
            msg += "   (on plain video it needs the OpenGL renderer)"
        self.video.flash(msg)

    def next_color_mode(self):
        i = COLOR_MODES.index(self.ascii.color_mode)
        self.set_color_mode(COLOR_MODES[(i + 1) % len(COLOR_MODES)])

    # ------------------------------------------------------------------ CRT screen filter
    def _apply_crt_state(self, flash=True):
        on = self.ascii.crt_on
        for w in (self.crt_btn, self.crt_action):
            w.blockSignals(True)
            w.setChecked(on)
            w.blockSignals(False)
        if self.crt_dialog is not None:
            self.crt_dialog.refresh()
        self.video.render_now()
        if not flash and not (on and not self.use_gl):
            return   # (but do say so when --crt was asked for and there is no GL to draw it with)
        if on and not self.video.crt_supported():
            msg = "CRT screen needs the OpenGL renderer (unavailable here)"
        elif on:
            msg = f"CRT screen: on ({CRT_LEVEL_NAMES[self.ascii.crt_level]})"
        else:
            msg = "CRT screen: off"
        self.video.flash(msg)

    def toggle_crt(self):
        self.ascii.crt_on = not self.ascii.crt_on
        self._apply_crt_state()

    def set_crt_level(self, index):
        self.ascii.crt_level = index % len(CRT_LEVELS)
        self.ascii.crt_on = True   # picking an intensity means you want to see it
        self._apply_crt_state()

    def next_crt_level(self):
        # off -> on at the current intensity; on -> the next one
        self.set_crt_level(self.ascii.crt_level + 1 if self.ascii.crt_on else self.ascii.crt_level)

    def crt_knob_value_text(self, attr):
        """One knob's value: the factor, then what it comes to on the current intensity level
        (blur and aberration in pixels, the trail in seconds - the green phosphor's decay
        time, which is the longest of the three)."""
        unit = next(un for at, _lb, un, _k in CRT_KNOBS if at == attr)
        factor = getattr(self.ascii, attr)
        lvl = CRT_LEVELS[self.ascii.crt_level][1]
        base = lvl["tau"][1] if attr == "crt_trail" else lvl["blur" if attr == "crt_blur" else "aberr"]
        return f"×{factor:.2f}" + (f"  ({base * factor:.2f} {unit})" if factor > 0 else "  (off)")

    def crt_knob_text(self, attr):
        """The same with the knob's name in front, for the OSD."""
        label = next(lb for at, lb, _un, _k in CRT_KNOBS if at == attr)
        return f"CRT {label}: {self.crt_knob_value_text(attr)}"

    def set_crt_knob(self, attr, value, flash=True):
        setattr(self.ascii, attr, min(CRT_KNOB_MAX, max(0.0, round(value / CRT_KNOB_STEP) * CRT_KNOB_STEP)))
        if self.crt_dialog is not None:
            self.crt_dialog.refresh()
        self.video.render_now()
        if flash:
            self.video.flash(self.crt_knob_text(attr)
                             + ("" if self.ascii.crt_on else "   (CRT screen is off - g turns it on)"))

    def change_crt_knob(self, attr, d):
        self.set_crt_knob(attr, getattr(self.ascii, attr) + d * CRT_KNOB_STEP)

    def reset_crt_knobs(self):
        for attr, _, _, _ in CRT_KNOBS:
            setattr(self.ascii, attr, 1.0)
        if self.crt_dialog is not None:
            self.crt_dialog.refresh()
        self.video.render_now()
        self.video.flash("CRT blur, trail and aberration back to the intensity level's defaults")

    def set_crt_tint(self, index, flash=True):
        """Which colour the phosphor trail glows as it fades (see CRT_TRAIL_TINTS)."""
        self.ascii.crt_tint = index % len(CRT_TRAIL_TINTS)
        if self.crt_dialog is not None:
            self.crt_dialog.refresh()
        self.video.render_now()
        if flash:
            name = CRT_TINT_NAMES[self.ascii.crt_tint]
            self.video.flash(f"CRT trail colour: {name}"
                             + ("  (whatever colour the picture has)" if name == "auto" else ""))

    def next_crt_tint(self):
        self.set_crt_tint(self.ascii.crt_tint + 1)

    def show_crt_dialog(self):
        """The CRT screen panel: on/off, intensity and the three knobs, live while playing."""
        if self.crt_dialog is None:
            self.crt_dialog = CrtDialog(self)
        self.crt_dialog.refresh()
        self.crt_dialog.show()
        self.crt_dialog.raise_()
        self.crt_dialog.activateWindow()

    # ------------------------------------------------------------------ crop / aspect
    def _apply_crop(self, flash=True):
        """Centre-crop the video to CROP_RATIOS[self.crop_index] with mpv's crop filter."""
        label, ratio = CROP_RATIOS[self.crop_index]
        if ratio is None:
            self.engine.set("vf", "")
            self.video.render_now()
            if flash:
                self.video.flash("crop: off")
            return
        p = self.engine.prop("video-params") or {}
        w, h = int(p.get("w") or 0), int(p.get("h") or 0)
        if w < 2 or h < 2:
            self.video.flash("crop: no video")
            return
        # pixel aspect ratio, so `ratio` is matched as a *display* ratio even for
        # anamorphic sources (dw/dh is the aspect-corrected size mpv would show)
        dw, dh = float(p.get("dw") or w), float(p.get("dh") or h)
        par = (dw / dh) / (w / h) if w and h and dh else 1.0
        cur = (w * par) / h
        if ratio >= cur:                       # target wider -> trim top/bottom
            cw, ch = w, int(round(w * par / ratio))
        else:                                  # target narrower -> trim left/right
            cw, ch = int(round(h * ratio / par)), h
        cw = max(2, min(w, cw - cw % 2))
        ch = max(2, min(h, ch - ch % 2))
        x, y = (w - cw) // 2, (h - ch) // 2
        self.engine.set("vf", f"crop={cw}:{ch}:{x}:{y}")
        self.video.render_now()
        if flash:
            self.video.flash(f"crop: {label}   {cw}×{ch}")

    def set_crop(self, index):
        self.crop_index = index % len(CROP_RATIOS)
        self._apply_crop()

    def cycle_crop(self):
        if not self.video.has_media:
            return
        self.set_crop(self.crop_index + 1)

    def set_ramp(self, name):
        self.ascii.set_ramp(name)
        ix = self.ramp_combo.findData(name)
        if ix >= 0 and ix != self.ramp_combo.currentIndex():
            self.ramp_combo.blockSignals(True)
            self.ramp_combo.setCurrentIndex(ix)
            self.ramp_combo.blockSignals(False)
        self.video.render_now()
        self.video.flash(f"character set: {name}  ({len(CHAR_RAMPS[name])} chars: {CHAR_RAMPS[name].strip()[:20]})")

    def next_ramp(self):
        names = list(CHAR_RAMPS)
        self.set_ramp(names[(names.index(self.ascii.ramp_name) + 1) % len(names)])

    def _ramp_combo_changed(self, idx):
        if idx >= 0:
            self.set_ramp(self.ramp_combo.itemData(idx))

    def set_res_divider(self, divider):
        self.ascii.res_divider = divider
        ix = self.res_combo.findData(divider)
        if ix >= 0 and ix != self.res_combo.currentIndex():
            self.res_combo.blockSignals(True)
            self.res_combo.setCurrentIndex(ix)
            self.res_combo.blockSignals(False)
        self.video.render_now()
        label = next(lbl for lbl, dv in RES_DIVIDERS if dv == divider)
        if self.video.ascii_active and not self.ascii.is_ascii:
            cols, rows = self.ascii.pixel_grid(self.video.width(), self.video.height())
            self.video.flash(f"resolution: {label}   {self.ascii.pixel_size()}px pixels, grid {cols}×{rows}")
        else:
            self.video.flash(f"resolution: {label}")

    def next_res_divider(self):
        dividers = [dv for _, dv in RES_DIVIDERS]
        i = dividers.index(self.ascii.res_divider)
        self.set_res_divider(dividers[(i + 1) % len(dividers)])

    def _res_combo_changed(self, idx):
        if idx >= 0:
            self.set_res_divider(self.res_combo.itemData(idx))

    def change_font_px(self, d):
        """Ctrl+-/=: character size for the ASCII filter, pixel size for the Bayer and
        vector filters (whichever is showing)."""
        if self.video.ascii_active and not self.ascii.is_ascii:
            self.ascii.set_pixel_px(self.ascii.pixel_px + d)
            cols, rows = self.ascii.pixel_grid(self.video.width(), self.video.height())
            self.video.render_now()
            self.video.flash(f"pixels: {self.ascii.pixel_size()}px  grid {cols}×{rows}")
            return
        self.ascii.set_font_px(self.ascii.font_px + d)
        cols, rows = self.ascii.grid(self.video.width(), self.video.height())
        self.video.render_now()
        self.video.flash(f"characters: {self.ascii.font_px}px  grid {cols}×{rows}")

    def _ascii_text_ready(self):
        """The text export needs the ASCII filter itself on screen (not Bayer/vector)."""
        if not self.video.ascii_active or not self.ascii.is_ascii or not self.video.snapshot_ascii():
            self.video.flash("switch to the ASCII filter first (t)")
            return False
        return True

    def save_ascii_frame(self):
        if not self._ascii_text_ready():
            return
        was_paused = self.engine.prop("pause", False)
        self.engine.set("pause", True)
        base = os.path.join(os.path.expanduser("~"), f"ascii_frame_{time.strftime('%Y%m%d_%H%M%S')}")
        path, _ = QFileDialog.getSaveFileName(self, "Save ASCII frame", base + ".txt",
                                              "Plain text (*.txt);;ANSI coloured text (*.ans)")
        if path:
            ansi = path.lower().endswith(".ans")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.ascii.as_text(ansi=ansi))
            self.video.flash(f"saved {path}" + ("  (view with: cat file)" if ansi else ""))
        self.engine.set("pause", was_paused)

    def save_screenshot(self):
        """Save what is on screen right now - the video, or the ASCII picture when the
        filter is on - as a JPG (or PNG), cropped to the picture itself."""
        if not self.video.has_media:
            self.video.flash("nothing to screenshot - open a file first")
            return
        was_paused = self.engine.prop("pause", False)
        self.engine.set("pause", True)
        img = self.video.grab_picture()
        if img is None:
            self.video.flash("could not grab the picture")
            self.engine.set("pause", was_paused)
            return
        kind = self.ascii.filter if self.video.ascii_active else "shot"
        base = os.path.join(os.path.expanduser("~"), f"asciiplay_{kind}_{time.strftime('%Y%m%d_%H%M%S')}")
        path, _ = QFileDialog.getSaveFileName(self, "Save screenshot", base + ".jpg",
                                              "JPEG image (*.jpg);;PNG image (*.png)")
        if path:
            fmt = "PNG" if path.lower().endswith(".png") else "JPG"
            if img.save(path, fmt, 92):
                self.video.flash(f"saved {path}  ({img.width()}×{img.height()})")
            else:
                self.video.flash(f"could not write {path}", 4)
        self.engine.set("pause", was_paused)

    def copy_ascii_frame(self):
        if not self._ascii_text_ready():
            return
        QApplication.clipboard().setText(self.ascii.as_text())
        self.video.flash("ASCII frame copied to clipboard")

    # ------------------------------------------------------------------ view
    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.leave_fullscreen()
        else:
            self._dock_was_visible = self.playlist_dock.isVisible()
            self.playlist_dock.hide()
            self.showFullScreen()
            self.menuBar().hide()
            self.controls.hide()
            if self.keep_seekbar_fullscreen:
                # Stays up throughout fullscreen (unlike the rest of the controls, which
                # still hide after inactivity) - just fade it in on entry.
                self.seek_fade.stop()
                self.seek_opacity.setOpacity(0.0)
                self.seek_bar.show()
                self.seek_fade.start()
            else:
                self.seek_bar.hide()
            self._fs_timer.start(2500)

    def leave_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            if self._dock_was_visible:
                self.playlist_dock.show()
        self.menuBar().show()
        self.controls.show()
        self.seek_fade.stop()
        self.seek_opacity.setOpacity(1.0)
        self.seek_bar.show()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._fs_timer.stop()

    def toggle_keep_seekbar(self):
        self.keep_seekbar_fullscreen = not self.keep_seekbar_fullscreen
        self.keep_seekbar_action.setChecked(self.keep_seekbar_fullscreen)
        self.video.flash("seek bar in fullscreen: " +
                          ("always visible" if self.keep_seekbar_fullscreen else "hides with the rest"))
        if not self.isFullScreen():
            return
        if self.keep_seekbar_fullscreen:
            self.seek_fade.stop()
            self.seek_opacity.setOpacity(0.0)
            self.seek_bar.show()
            self.seek_fade.start()
        else:
            # fall in with whatever state the rest of the controls are currently in
            self.seek_opacity.setOpacity(1.0)
            self.seek_bar.setVisible(self.controls.isVisible())

    def _hide_fs_ui(self):
        if self.isFullScreen():
            self.controls.hide()
            if not self.keep_seekbar_fullscreen:
                self.seek_bar.hide()
            self.setCursor(Qt.CursorShape.BlankCursor)

    def mouseMoveEvent(self, event):
        if self.isFullScreen():
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.controls.setVisible(event.position().y() > self.height() - 80)
            if not self.keep_seekbar_fullscreen:
                self.seek_bar.setVisible(self.controls.isVisible())
            self._fs_timer.start(2500)
        super().mouseMoveEvent(event)

    def show_help(self):
        text = "\n".join(
            f"{a.shortcut().toString() or '·':<12} {a.text().replace('&', '').replace('…', '')}"
            for a in self.actions() if a.text() and not a.menu()
        )
        box = QMessageBox(self)
        box.setWindowTitle("Keyboard shortcuts")
        box.setFont(self.video.mono_font)
        box.setText(text)
        box.exec()

    def show_about(self):
        from PyQt6.QtCore import QT_VERSION_STR, qVersion  # noqa: F401
        try:
            mpv_ver = str(self.engine.m.mpv_version)
        except Exception:
            mpv_ver = "libmpv"
        if self.use_gl:
            ctx = self.video.context() if hasattr(self.video, "context") else None
            f = ctx.format() if ctx is not None else None
            renderer = (f"OpenGL {f.majorVersion()}.{f.minorVersion()}" if f is not None else "OpenGL")
            renderer += ", ASCII on the GPU" if getattr(self.video, "_shader_ok", False) else ", ASCII on the CPU"
            renderer += (", Bayer/vector on the GPU" if getattr(self.video, "_filters_ok", False)
                         else ", Bayer/vector on the CPU")
            renderer += ", CRT screen available" if self.video.crt_supported() else ", no CRT screen"
        else:
            renderer = "software (CPU), no CRT screen"
        link = f'<p><a href="{HOMEPAGE}" style="color:#8ce87a">{HOMEPAGE}</a></p>' if HOMEPAGE else ""
        html = f"""
        <h2 style="margin-bottom:2px">asciiplay <span style="font-weight:normal;color:#8ce87a">{VERSION}</span></h2>
        <p>A native video and audio player with a terminal soul: anything it plays can be
        turned into live, coloured ASCII art, 1-bit Bayer-dithered pixels or the glowing
        edge traces of a vector display, and that picture - or the plain video, run through
        the same phosphor and retro-palette colour modes - can be put behind the glass of a
        simulated CRT monitor.</p>
        <p>What makes it different from the many terminal ASCII players: the text rendering
        is a fragment shader running inside a real desktop window, so a 5120x1440 fullscreen
        picture keeps the video's frame rate with hardware decoding staying on the GPU; the
        character ramps are sorted by the measured ink of your actual font so gradients do not
        band; the CRT look (curved glass, shadow mask, scanlines, beam focus blur, bloom,
        grain, chromatic aberration, phosphor trail) is a second shader chain on top, with
        the blur, the trail, its colour and the aberration on live sliders (Ctrl+G); and
        audio files run through the same path as five ffmpeg visualisers. Around that sits an ordinary player: tracks,
        subtitles, crop presets, speed, frame stepping, screenshots, text export, playlist
        with repeat and shuffle.</p>
        <p style="color:#a0a0a0">Built on {mpv_ver} (decoding, tracks, filters), PyQt6 {QT_VERSION_STR}
        (window and OpenGL), numpy (text export and the CPU fallback) and ffmpeg's libavfilter
        (visualisers).<br>Renderer in this session: {renderer}.</p>
        {link}
        <p style="color:#a0a0a0">Written together with Claude (Anthropic) in September 2026.</p>
        """
        dlg = QDialog(self)
        dlg.setWindowTitle("About asciiplay")
        dlg.setStyleSheet("QDialog { background: #101010; } QLabel { color: #d0d0d0; }")
        row = QHBoxLayout(dlg)
        row.setContentsMargins(20, 20, 20, 16)
        row.setSpacing(20)
        icon = self.windowIcon()
        if not icon.isNull():
            pic = QLabel()
            pic.setPixmap(icon.pixmap(96, 96))
            pic.setAlignment(Qt.AlignmentFlag.AlignTop)
            row.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        text = QLabel(html)
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setWordWrap(True)
        text.setOpenExternalLinks(True)
        text.setFixedWidth(620)
        col.addWidget(text)
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(dlg.accept)
        col.addWidget(ok, 0, Qt.AlignmentFlag.AlignRight)
        row.addLayout(col)
        dlg.exec()

    def closeEvent(self, event):
        self.video.release_gl()   # mpv's GL render context must go while the GL context is alive
        self.engine.shutdown()
        super().closeEvent(event)


# --------------------------------------------------------------------------------------

def _find_app_icon():
    """Look for the icon next to this script - works whether or not it was ever
    "installed" anywhere, since the app is meant to run as a portable single file plus
    its icon/asciiplay.desktop siblings."""
    base = os.path.dirname(os.path.abspath(__file__))
    svg = os.path.join(base, "asciiplay.svg")
    if os.path.isfile(svg):
        icon = QIcon(svg)
        if not icon.isNull():
            return icon
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256, 512):
        png = os.path.join(base, "icons", f"asciiplay-{size}.png")
        if os.path.isfile(png):
            icon.addFile(png)
    return icon if not icon.isNull() else None


def _excepthook(exc_type, exc, tb):
    """PyQt6 aborts the whole process when a Python exception escapes a slot or timer;
    a misbehaving menu action shouldn't take the movie down with it, so just report it."""
    import traceback
    traceback.print_exception(exc_type, exc, tb)


def main():
    args = ARGS if "ARGS" in globals() else parse_args(sys.argv[1:])
    sys.excepthook = _excepthook
    QApplication.setApplicationName(APP_NAME)
    if HAVE_GL and args.renderer != "software":
        # must be set before the first window exists; vsync so the swap paces our redraws
        fmt = QSurfaceFormat.defaultFormat()
        fmt.setSwapInterval(1)
        # Ask for desktop OpenGL: on some EGL setups Qt otherwise picks OpenGL ES, which
        # works too (the shader adapts) but gives mpv's renderer fewer features.
        fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
        QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv)
    # Ties this running window to asciiplay.desktop for icon/grouping purposes - matters
    # most on Wayland, where the compositor identifies windows by desktop-file id rather
    # than any X11-style WM_CLASS guess.
    app.setDesktopFileName(APP_NAME)
    icon = _find_app_icon()
    if icon is not None:
        app.setWindowIcon(icon)
    try:
        win = MainWindow(args)
    except RuntimeError as exc:
        print(f"{APP_NAME}: {exc}", file=sys.stderr)
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 1
    if icon is not None:
        win.setWindowIcon(icon)
    win.show()
    if args.fullscreen:
        win.toggle_fullscreen()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
