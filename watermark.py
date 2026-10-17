"""
"Clipped by Verse Platform" watermark: the same look as the save pop-up, burned into the first
2 seconds of a clip (slides and fades in, fades out). Being part of the video, it shows wherever
the clip ends up: Verse, Discord, TikTok...
"""

import os
import tempfile

from overlay import render

SECONDS = 2.0
_cache = {}


def png_for(height):
    """Watermark picture sized for a video of this height (cached)."""
    height = int(height or 1080)
    if height not in _cache or not os.path.exists(_cache[height]):
        img = render("Clipped by", accent="Verse Platform", scale=max(0.7, height / 620))
        folder = os.path.join(tempfile.gettempdir(), "VersePlatformWatermark")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"wm_{height}.png")
        img.save(path)
        _cache[height] = path
    return _cache[height]


def inputs(png):
    return ["-loop", "1", "-framerate", "30", "-t", f"{SECONDS:.1f}", "-i", png]


def filter_graph(pix_fmt="yuv420p"):
    """Overlay input 1 on input 0 for the first 2 seconds. Output label: [vo]."""
    return ("[1:v]format=rgba,fade=t=in:st=0:d=0.25:alpha=1,"
            f"fade=t=out:st={SECONDS - 0.3:.2f}:d=0.3:alpha=1[wm];"
            "[0:v][wm]overlay=x='W*0.022-max(0\\,1-t/0.3)*H*0.03':y='H*0.035':eval=frame:eof_action=pass,"
            f"format={pix_fmt}[vo]")
