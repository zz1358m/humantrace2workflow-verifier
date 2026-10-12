"""Live recorder: structured events first, screenshots only on triggers.

Keystroke *content* is never stored: typing becomes a count, shortcuts become their combo name.
"""
from __future__ import annotations

import hashlib
import queue
import shutil
import threading
import time
from pathlib import Path

from .. import config, store
from ..redact import is_private, redact
from . import win32

SRC = "screen"
COMMIT_COMBOS = {"ctrl+s", "ctrl+enter", "ctrl+p", "ctrl+shift+s"}
_SKIP_PARTS = {".git", "node_modules", "__pycache__", ".venv", "$RECYCLE.BIN"}


def dhash(img) -> int:
    g = img.convert("L").resize((9, 8))
    px = list(g.getdata())
    bits = 0
    for r in range(8):
        for c in range(8):
            bits = (bits << 1) | (px[r * 9 + c] > px[r * 9 + c + 1])
    return bits


class Recorder:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or config.load()
        self.sc = self.cfg["screen"]
        self.deny = self.cfg["privacy"]["deny"]
        self.extra = self.cfg["privacy"]["redact_extra"]
        self.w = store.Writer()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.private = False
        self.win = ("", "")
        self.mods: set[str] = set()
        self.burst = None  # typing burst in progress: [t0, t1, n, bs]
        self.clicks = None  # [t0, t1, n]
        self.scrolls = None
        self.shots: queue.Queue = queue.Queue()
        self.file_seen: dict[str, float] = {}

    def emit(self, k, **f):
        return self.w.emit(SRC, k, **f)

    # ---- aggregation -------------------------------------------------
    def _flush(self, force=False):
        now = time.time()
        with self.lock:
            for name, kind in (("burst", "type"), ("clicks", "click"), ("scrolls", "scroll")):
                b = getattr(self, name)
                if b and (force or now - b[1] > 3):
                    extra = {"bs": b[3]} if kind == "type" else {}
                    self.w.emit(SRC, kind, t=b[0], t1=round(b[1], 3), n=b[2], **extra)
                    setattr(self, name, None)

    def _bump(self, name, bs=0):
        now = time.time()
        with self.lock:
            b = getattr(self, name)
            if b is None:
                b = [now, now, 0, 0]
                setattr(self, name, b)
            b[1] = now
            b[2] += 1
            b[3] += bs

    # ---- input -------------------------------------------------------
    def _on_press(self, key):
        from pynput import keyboard as kb

        name = getattr(key, "name", None)
        if name:
            base = name.split("_")[0]
            if base in ("ctrl", "alt", "shift", "cmd"):
                self.mods.add(base)
                return
        if self.private:
            return
        vk = getattr(key, "vk", None)
        label = name or (chr(vk).lower() if vk and (48 <= vk <= 57 or 65 <= vk <= 90) else None)
        if self.mods & {"ctrl", "alt", "cmd"} and label:
            combo = "+".join([m for m in ("ctrl", "alt", "shift", "cmd") if m in self.mods] + [label])
            self._flush(force=True)
            self.emit("key", combo=combo)
            if combo in COMMIT_COMBOS:
                self.shots.put("commit")
            return
        if key in (kb.Key.backspace, kb.Key.delete):
            self._bump("burst", bs=1)
        else:
            self._bump("burst")

    def _on_release(self, key):
        name = getattr(key, "name", None)
        if name:
            self.mods.discard(name.split("_")[0])

    def _on_click(self, x, y, button, pressed):
        if pressed and not self.private:
            self._bump("clicks")

    def _on_scroll(self, x, y, dx, dy):
        if not self.private:
            self._bump("scrolls")

    # ---- polling: window, idle, clipboard ----------------------------
    def _poll(self):
        seq = win32.clipboard_seq()
        idle_since = None
        while not self.stop.wait(self.sc["poll_s"]):
            self._flush()
            idle = win32.idle_seconds()
            if idle >= self.sc["idle_s"] and idle_since is None:
                idle_since = time.time() - idle
            elif idle < self.sc["idle_s"] and idle_since is not None:
                self.emit("idle", t=idle_since, t1=round(time.time(), 3))
                idle_since = None
            fg = win32.foreground()
            if fg and fg != self.win:
                self._flush(force=True)
                self.win = fg
                self.private = is_private(fg[0], fg[1], self.deny)
                title = "[private]" if self.private else redact(fg[1], self.extra)
                self.emit("win", app=fg[0], title=title)
                self.shots.put("win")
            s = win32.clipboard_seq()
            if s != seq:
                seq = s
                if self.private:
                    continue
                text = win32.clipboard_text()
                if text:
                    ev = {"n": len(text), "h": hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:10]}
                    if self.sc["clip_preview"]:
                        ev["preview"] = redact(text[: self.sc["clip_preview"]], self.extra)
                    self.emit("clip", **ev)

    # ---- screenshots -------------------------------------------------
    def _shooter(self):
        import mss
        from PIL import Image

        last_hash, last_t = None, 0.0
        with mss.mss() as sct:
            while not self.stop.is_set():
                try:
                    reason = self.shots.get(timeout=self.sc["shot_interval_s"])
                    time.sleep(1.2)  # let the new window paint
                    while not self.shots.empty():
                        self.shots.get_nowait()
                except queue.Empty:
                    reason = "tick"
                if self.private or win32.idle_seconds() >= self.sc["idle_s"]:
                    continue
                raw = sct.grab(sct.monitors[0])
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
                h = dhash(img)
                if last_hash is not None and bin(h ^ last_hash).count("1") < 4 and time.time() - last_t < 600:
                    continue
                last_hash, last_t = h, time.time()
                if img.width > self.sc["shot_max_width"]:
                    r = self.sc["shot_max_width"] / img.width
                    img = img.resize((self.sc["shot_max_width"], int(img.height * r)))
                d = config.day_dir(store.day_of(last_t)) / "shots"
                d.mkdir(exist_ok=True)
                name = time.strftime("%H%M%S", time.localtime(last_t)) + ".jpg"
                img.save(d / name, quality=self.sc["shot_quality"])
                self.emit("shot", t=last_t, path=f"shots/{name}", reason=reason)

    # ---- files -------------------------------------------------------
    def on_file(self, op: str, path: str):
        p = Path(path)
        if p.name.startswith(("~$", ".~")) or p.suffix.lower() in (".tmp", ".crdownload", ".lock") or _SKIP_PARTS & set(p.parts):
            return
        now = time.time()
        if now - self.file_seen.get(path, 0) < 2:
            return
        self.file_seen[path] = now
        ev = {"op": op, "path": str(p)}
        try:
            if op != "deleted" and p.is_file():
                size = p.stat().st_size
                ev["size"] = size
                if size <= self.sc["blob_max_bytes"] and p.suffix.lower() in self.sc["blob_exts"]:
                    data = p.read_bytes()
                    sha = hashlib.sha256(data).hexdigest()[:16]
                    bdir = config.day_dir(store.day_of(now)) / "blobs"
                    bdir.mkdir(exist_ok=True)
                    blob = bdir / f"{sha}{p.suffix.lower()}"
                    if not blob.exists():
                        shutil.copyfile(p, blob)
                    ev["sha"] = sha
        except OSError:
            pass
        self.emit("file", t=now, **ev)

    def _watch(self):
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        rec = self

        class H(FileSystemEventHandler):
            def on_created(self, e):
                e.is_directory or rec.on_file("created", e.src_path)

            def on_modified(self, e):
                e.is_directory or rec.on_file("modified", e.src_path)

            def on_deleted(self, e):
                e.is_directory or rec.on_file("deleted", e.src_path)

            def on_moved(self, e):
                e.is_directory or rec.on_file("modified", e.dest_path)

        obs = Observer()
        for d in self.sc["watch_dirs"]:
            d = config.expand(d)
            if d.is_dir():
                obs.schedule(H(), str(d), recursive=True)
        obs.start()
        return obs

    # ---- lifecycle ---------------------------------------------------
    def run(self, seconds: float | None = None):
        from pynput import keyboard, mouse

        if not win32.AVAILABLE:
            raise SystemExit("live recording currently supports Windows only; use `ht2w collect video` elsewhere")
        threads = [threading.Thread(target=self._poll, daemon=True)]
        if self.sc["screenshots"]:
            threads.append(threading.Thread(target=self._shooter, daemon=True))
        kl = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        ml = mouse.Listener(on_click=self._on_click, on_scroll=self._on_scroll)
        obs = self._watch() if self.sc["watch_dirs"] else None
        for t in threads:
            t.start()
        kl.start()
        ml.start()
        t_end = time.time() + seconds if seconds else None
        try:
            while not self.stop.is_set() and (t_end is None or time.time() < t_end):
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop.set()
            kl.stop()
            ml.stop()
            if obs:
                obs.stop()
            self._flush(force=True)
            self.w.close()
