"""Screen-recording video -> deduplicated keyframes the coding agent can look at.

No VLM here on purpose: the agent that distills the trace reads the frames itself, and only the
ones the timeline makes it curious about.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from .. import config, store
from .screen import dhash

SRC = "video"


def ingest(path: str, start: float | None = None, every_s: float = 2.0, min_dist: int = 6, max_width: int = 1280) -> int:
    """`start` = wall-clock epoch of the first frame (defaults to file mtime minus duration)."""
    import cv2
    from PIL import Image

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"cannot open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    if start is None:
        start = os.path.getmtime(path) - total / fps
    tag = Path(path).stem[:24]
    step = max(1, int(round(fps * every_s)))
    events, last, i, last_kept = [], None, 0, -1e9
    while True:
        if not cap.grab():
            break
        if i % step == 0:
            ok, frame = cap.retrieve()
            if ok:
                img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                h = dhash(img)
                t = start + i / fps
                # keep on visible change; also keep a heartbeat frame every 5 minutes
                if last is None or bin(h ^ last).count("1") >= min_dist or t - last_kept > 300:
                    last, last_kept = h, t
                    if img.width > max_width:
                        img = img.resize((max_width, int(img.height * max_width / img.width)))
                    d = config.day_dir(store.day_of(t)) / "shots"
                    d.mkdir(exist_ok=True)
                    name = f"{tag}-{time.strftime('%H%M%S', time.localtime(t))}.jpg"
                    img.save(d / name, quality=60)
                    events.append({"t": round(t, 3), "src": f"{SRC}:{tag}", "k": "shot", "path": f"shots/{name}", "reason": "scene"})
        i += 1
    cap.release()
    store.replace_source(f"{SRC}:{tag}", events)
    return len(events)
