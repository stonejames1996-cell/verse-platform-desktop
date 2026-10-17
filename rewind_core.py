"""
Verse Platform desktop core: recording, game detection and settings.
The app window and tray live in verse_desktop.py.

The recorder: an always-on replay buffer for Windows (like Xbox Game Bar / ShadowPlay).

It quietly records your screen + desktop audio into a rolling buffer.
Press the hotkey (default Alt+F10) and the last 60 seconds are saved as an MP4.

How it works:
  * FFmpeg captures the screen (Desktop Duplication API) and encodes it on the GPU
    (NVENC / AMF / QuickSync, falls back to CPU x264).
  * Desktop audio is grabbed with WASAPI loopback and piped into FFmpeg so the
    audio and video stay in sync.
  * FFmpeg writes tiny 2 second chunks into a temp folder. Old chunks get deleted,
    so only ~80 seconds ever exist at once.
  * When you press the hotkey, the newest chunks are stitched into one MP4
    (no re-encoding, so it's instant).
"""

import collections
import datetime
import glob
import json
import logging
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time

APP_NAME = "Verse Platform"
APP_VERSION = "1.1.2"
VERSE_URL = "https://verseplatform.gg"
# GitHub repo the app updates itself from ("owner/repo"). Release.bat fills this in. Blank = no auto update.
UPDATE_REPO = "stonejames1996-cell/verse-platform-desktop"
SEGMENT_SECONDS = 2  # length of each chunk in the rolling buffer
IS_WINDOWS = sys.platform == "win32"
FROZEN = getattr(sys, "frozen", False)  # True when running as the installed .exe
# folder with the program itself (the .exe, or this .py file)
HERE = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
# bundled files (logo, ffmpeg) live in PyInstaller's _internal folder when frozen
RES = getattr(sys, "_MEIPASS", HERE)
# Program Files isn't writable, so the installed app keeps settings in %APPDATA%\Verse Platform
_APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
DATA_DIR = os.path.join(_APPDATA, APP_NAME) if FROZEN else HERE
if FROZEN and not os.path.exists(DATA_DIR) and os.path.isdir(os.path.join(_APPDATA, "Verse Rewind")):
    # the app used to be called Verse Rewind: carry its settings and clip list over
    try:
        shutil.copytree(os.path.join(_APPDATA, "Verse Rewind"), DATA_DIR,
                        ignore=shutil.ignore_patterns("*.log", "account.json", "instance.json", "webview"))
    except OSError:
        pass
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LOG_PATH = os.path.join(DATA_DIR, "verse_platform.log")

DEFAULT_CONFIG = {
    "hotkey": "alt+f10",           # any combo the 'keyboard' library understands
    "buffer_seconds": 60,          # how far back a clip goes
    "fps": 60,
    "bitrate": "20M",              # 20M is great for 1080p60, try 40M for 1440p/4K
    "output_height": 0,            # 0 = native resolution, or e.g. 1080 to downscale
    "monitor": 0,                  # 0 = main monitor, 1 = second monitor...
    "encoder": "auto",             # auto | h264_nvenc | h264_amf | h264_qsv | hevc_nvenc | libx264
    "capture": "auto",             # auto | ddagrab (fast, GPU) | gdigrab (old, slow fallback)
    "draw_mouse": True,
    "record_desktop_audio": True,
    "mic_device": "",              # pick it from the tray menu, blank = no mic
    "audio_offset_ms": 0,          # nudge audio if it's out of sync (positive = later)
    "clips_folder": "~/Videos/Verse Platform",
    "sort_clips_by_game": True,    # clips go into a subfolder per game
    "record_mode": "games",        # games = only record while a game is running | always
    "detect_fullscreen_apps": True,  # also record anything running fullscreen (catches unlisted games)
    "stop_delay_seconds": 20,      # keep recording this long after a game closes
    "custom_games": {},            # extra games: {"SomeGame.exe": "Some Game"}
    "ignored_apps": [],            # exe names that should never trigger recording
    "ffmpeg_path": "",             # blank = find ffmpeg automatically
    "play_sound_on_save": True,
    "show_save_overlay": True,
    "clip_watermark": True,
    "voice_command": False,        # say "clip that" to save a clip (Windows speech recognition, offline)
    "controller_combo": "view_rb", # controller buttons that save a clip, blank = off (see triggers.COMBOS)
    "auto_clean_days": 0,          # remove unstarred, unposted clips older than this, 0 = never
    "auto_clean_permanent": False, # skip the Recycle Bin when cleaning up        # "Clipped by Verse Platform" in the first 2 seconds of every clip     # "Last 60s saved by Verse Platform" pop-up over the game
    "auto_highlights": True,       # clip big plays by themselves (League of Legends)
    "highlight_events": {},        # which moments count, see highlights.DEFAULT_EVENTS (blank = defaults)
    "highlight_before": 5,         # seconds kept before the first moment of a play
    "highlight_after": 5,          # seconds kept after the last moment
    "highlight_max_per_game": 10,  # 0 = no limit
    "max_post_seconds": 60,        # Verse posts are 60 seconds max
    "verse_url": "",               # blank = https://verseplatform.gg
    "last_seen_version": "",       # newest version whose "What's new" was shown
}

log = logging.getLogger(APP_NAME)
NO_WINDOW = 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW so ffmpeg doesn't flash a console


# --------------------------------------------------------------------------- config / setup

def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError as e:
        log.error("Could not save settings: %s", e)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:  # broken json shouldn't brick the app
            log.error("config.json could not be read (%s), using defaults", e)
    save_config(cfg)  # write back so new options show up for the user
    cfg["clips_folder"] = os.path.abspath(os.path.expanduser(cfg["clips_folder"]))
    return cfg


def find_ffmpeg(cfg):
    candidates = [cfg.get("ffmpeg_path") or "", os.path.join(RES, "ffmpeg.exe"),
                  os.path.join(HERE, "ffmpeg.exe"), os.path.join(HERE, "ffmpeg", "bin", "ffmpeg.exe")]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise RuntimeError(
        "FFmpeg not found. Install it with:  winget install Gyan.FFmpeg\n"
        "or reinstall Verse Platform")


def run_quiet(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout, creationflags=NO_WINDOW)
        return r.returncode, r.stderr.decode(errors="replace")
    except Exception as e:
        return -1, str(e)


def pick_encoder(ff, wanted):
    if wanted and wanted != "auto":
        return wanted
    for enc in ("h264_nvenc", "h264_amf", "h264_qsv"):
        code, _ = run_quiet([ff, "-hide_banner", "-f", "lavfi", "-i", "color=black:s=640x360:r=30",
                             "-frames:v", "10", "-vf", "format=nv12", "-c:v", enc, "-f", "null", "-"])
        if code == 0:
            log.info("GPU encoder found: %s", enc)
            return enc
    log.warning("No GPU encoder worked, falling back to CPU (libx264). Expect some FPS loss.")
    return "libx264"


def pick_capture(ff, wanted, monitor):
    if wanted and wanted != "auto":
        return wanted
    if not IS_WINDOWS:
        return "x11grab"
    code, _ = run_quiet([ff, "-hide_banner", "-f", "lavfi", "-i",
                         f"ddagrab=output_idx={monitor}:framerate=30", "-frames:v", "2",
                         "-vf", "hwdownload,format=bgra", "-f", "null", "-"])
    if code == 0:
        return "ddagrab"
    log.warning("ddagrab not available (old FFmpeg?). Using gdigrab, which is slower.")
    return "gdigrab"


def encoder_args(enc, bitrate, fps):
    gop = str(fps * SEGMENT_SECONDS)
    common = ["-g", gop, "-force_key_frames", f"expr:gte(t,n_forced*{SEGMENT_SECONDS})",
              "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", bitrate]
    if "nvenc" in enc:
        return ["-c:v", enc, "-preset", "p4", "-tune", "ll", "-rc", "cbr", "-bf", "0"] + common
    if "amf" in enc:
        return ["-c:v", enc, "-quality", "speed", "-rc", "cbr", "-bf", "0"] + common
    if "qsv" in enc:
        return ["-c:v", enc, "-preset", "veryfast"] + common
    return ["-c:v", enc, "-preset", "superfast", "-tune", "zerolatency"] + common


# --------------------------------------------------------------------------- desktop audio

class AudioFeeder:
    """Captures desktop audio (WASAPI loopback) and feeds FFmpeg a steady, real-time stream.

    WASAPI loopback goes quiet (sends nothing at all) when no sound is playing, which would
    make the audio drift out of sync. So a writer thread runs on its own clock and fills any
    gaps with silence, and trims any build up so latency never grows.
    """

    CUSHION = 0.06   # seconds of audio we keep in hand to absorb jitter
    MAX_BACKLOG = 0.25

    def __init__(self, rate, channels, source):
        self.rate, self.channels = rate, channels
        self.bpf = 2 * channels  # bytes per frame, 16 bit samples
        self.source = source     # callable(stop_event, out_queue) that produces raw s16le bytes
        self.q = queue.Queue()
        self.stop_event = threading.Event()
        self.threads = []

    def start(self, sink):
        self.stop_event.clear()
        self.threads = [threading.Thread(target=self.source, args=(self.stop_event, self.q), daemon=True),
                        threading.Thread(target=self._writer, args=(sink,), daemon=True)]
        for t in self.threads:
            t.start()

    def stop(self):
        self.stop_event.set()

    def _writer(self, sink):
        buf = bytearray()
        written = 0
        start = time.perf_counter()
        while not self.stop_event.is_set():
            time.sleep(0.01)
            while True:
                try:
                    buf += self.q.get_nowait()
                except queue.Empty:
                    break
            target = int((time.perf_counter() - start - self.CUSHION) * self.rate)
            need = target - written
            if need <= 0:
                continue
            need_bytes = need * self.bpf
            max_bytes = need_bytes + int(self.MAX_BACKLOG * self.rate) * self.bpf
            if len(buf) > max_bytes:            # running behind: drop the oldest audio
                del buf[:len(buf) - max_bytes]
            take = min(len(buf), need_bytes)
            take -= take % self.bpf
            chunk = bytes(buf[:take])
            del buf[:take]
            if take < need_bytes:               # nothing playing: pad with silence
                chunk += b"\x00" * (need_bytes - take)
            try:
                sink.write(chunk)
                sink.flush()
            except (BrokenPipeError, OSError, ValueError):
                return
            written += need


def open_loopback():
    """Returns (rate, channels, source_fn) for the default speakers' loopback, or None."""
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        log.error("pyaudiowpatch missing, desktop audio disabled (pip install pyaudiowpatch)")
        return None
    pa = pyaudio.PyAudio()
    try:
        wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        speakers = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        if not speakers.get("isLoopbackDevice"):
            for lb in pa.get_loopback_device_info_generator():
                if speakers["name"] in lb["name"]:
                    speakers = lb
                    break
            else:
                log.error("No loopback device found for %s", speakers["name"])
                return None
    except Exception as e:
        log.error("Could not open desktop audio: %s", e)
        return None

    rate = int(speakers["defaultSampleRate"])
    channels = max(1, min(2, int(speakers["maxInputChannels"])))
    index = speakers["index"]
    log.info("Desktop audio: %s (%d Hz, %d ch)", speakers["name"], rate, channels)

    def source(stop_event, out_q):
        stream = pa.open(format=pyaudio.paInt16, channels=channels, rate=rate,
                         input=True, input_device_index=index, frames_per_buffer=rate // 100)
        try:
            while not stop_event.is_set():
                # blocks while nothing is playing, that's fine, the writer pads silence
                out_q.put(stream.read(rate // 100, exception_on_overflow=False))
        finally:
            stream.close()

    return rate, channels, source


# --------------------------------------------------------------------------- the recorder

class Recorder:
    def __init__(self, cfg, ff):
        self.cfg, self.ff = cfg, ff
        self.seg_dir = os.path.join(tempfile.gettempdir(), "VersePlatform", f"buffer_{os.getpid()}")
        self.proc = None
        self.audio = None
        self.running = False      # threads alive
        self.capturing = False    # ffmpeg should be recording right now
        self.run = 0              # bumps every time ffmpeg (re)starts, keeps chunk names in order
        self.label = ""           # what's being recorded (game name), used in clip names
        self.last_tag = ""        # highlight name of the clip being saved, if any
        self.subfolder = ""       # match folder inside the game's folder, e.g. "2026-10-17 4.08pm ARAM - Brand"
        self.last_seconds = 0
        self.save_lock = threading.Lock()
        self.on_saved = None  # callback(path or None, message)
        self.encoder = pick_encoder(ff, cfg["encoder"])
        self.capture = pick_capture(ff, cfg["capture"], cfg["monitor"])
        self.audio_info = open_loopback() if (cfg["record_desktop_audio"] and IS_WINDOWS) else None

    # these two methods are separate so the self test can swap in fake sources
    def video_input_args(self):
        c = self.cfg
        if self.capture == "ddagrab":
            return (["-f", "lavfi", "-i",
                     f"ddagrab=output_idx={c['monitor']}:framerate={c['fps']}:draw_mouse={int(c['draw_mouse'])}"],
                    "hwdownload,format=bgra")
        if self.capture == "gdigrab":
            return (["-f", "gdigrab", "-framerate", str(c["fps"]),
                     "-draw_mouse", str(int(c["draw_mouse"])), "-i", "desktop"], "")
        return (["-f", "x11grab", "-framerate", str(c["fps"]), "-i", os.environ.get("DISPLAY", ":0")], "")

    def build_command(self):
        c = self.cfg
        cmd = [self.ff, "-hide_banner", "-loglevel", "warning", "-y"]
        vin, vpre = self.video_input_args()
        cmd += ["-thread_queue_size", "1024"] + vin
        n_inputs = 1
        audio_labels = []
        if self.audio_info:
            rate, ch, _ = self.audio_info
            if c.get("audio_offset_ms"):
                cmd += ["-itsoffset", str(c["audio_offset_ms"] / 1000)]
            cmd += ["-thread_queue_size", "1024", "-f", "s16le", "-ar", str(rate), "-ac", str(ch), "-i", "pipe:0"]
            audio_labels.append(f"[{n_inputs}:a]")
            n_inputs += 1
        if c["mic_device"] and IS_WINDOWS:
            cmd += ["-thread_queue_size", "1024", "-f", "dshow", "-i", f"audio={c['mic_device']}"]
            audio_labels.append(f"[{n_inputs}:a]")
            n_inputs += 1

        vf = [f for f in (vpre,) if f]
        if c["output_height"]:
            vf.append(f"scale=-2:{int(c['output_height'])}")
        vf.append("format=yuv420p" if self.encoder == "libx264" else "format=nv12")
        graph = f"[0:v]{','.join(vf)}[v]"
        two_tracks = len(audio_labels) == 2 and bool(self.audio_info)
        if audio_labels:
            if two_tracks:
                # track 1: game + mic (what you hear when you play the clip)
                # track 2: game only, so your voice can be taken out before posting
                desk, mic = audio_labels
                graph += (f";{desk}aresample=48000:async=1000,asplit=2[d1][d2]"
                          f";{mic}aresample=48000:async=1000[m]"
                          f";[d1][m]amix=inputs=2:duration=longest:normalize=0[a];[d2]anull[g]")
            elif len(audio_labels) == 2:
                graph += f";{''.join(audio_labels)}amix=inputs=2:duration=longest:normalize=0,aresample=48000:async=1000[a]"
            else:
                graph += f";{audio_labels[0]}aresample=48000:async=1000[a]"
        cmd += ["-filter_complex", graph, "-map", "[v]"]
        if audio_labels:
            cmd += ["-map", "[a]"]
            if two_tracks:
                cmd += ["-map", "[g]", "-metadata:s:a:0", "title=Game and mic", "-metadata:s:a:1", "title=Game only"]
            cmd += ["-c:a", "aac", "-b:a", "192k", "-ac", "2"]
        cmd += encoder_args(self.encoder, c["bitrate"], c["fps"])
        cmd += ["-f", "segment", "-segment_time", str(SEGMENT_SECONDS), "-segment_format", "mpegts",
                "-reset_timestamps", "0", os.path.join(self.seg_dir, f"seg_{self.run:05d}_%07d.ts")]
        return cmd

    def start(self, capture=True):
        """Starts the background threads. capture=False means wait for begin_capture()
        (used by game detection mode)."""
        shutil.rmtree(self.seg_dir, ignore_errors=True)
        os.makedirs(self.seg_dir, exist_ok=True)
        os.makedirs(self.cfg["clips_folder"], exist_ok=True)
        self.running = True
        threading.Thread(target=self._watchdog, daemon=True).start()
        threading.Thread(target=self._cleanup_loop, daemon=True).start()
        log.info("Ready. Encoder=%s Capture=%s Buffer=%ss Hotkey=%s",
                 self.encoder, self.capture, self.cfg["buffer_seconds"], self.cfg["hotkey"])
        if capture:
            self.begin_capture()

    def begin_capture(self, label=""):
        """Start recording. Old footage from the last session is thrown away."""
        if self.capturing:
            self.label = label or self.label
            return
        with self.save_lock:  # don't wipe chunks in the middle of a save
            for old in self.segments():
                try:
                    os.remove(old)
                except OSError:
                    pass
        self.label = label
        self.capturing = True
        log.info("Capture started%s", f" for {label}" if label else "")

    def end_capture(self):
        """Stop recording but KEEP the buffer, so the hotkey still saves the last moments
        (like the end of a League game, which closes the window straight after)."""
        if self.capturing:
            self.capturing = False
            log.info("Capture paused (buffer kept)")

    def _launch(self):
        self.run += 1
        cmd = self.build_command()
        log.debug("ffmpeg: %s", subprocess.list2cmdline(cmd))
        self._ff_log = open(os.path.join(self.seg_dir, "ffmpeg.log"), "ab")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if self.audio_info else subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=self._ff_log, creationflags=NO_WINDOW)
        if self.audio_info:
            rate, ch, source = self.audio_info
            self.audio = AudioFeeder(rate, ch, source)
            self.audio.start(self.proc.stdin)

    def _kill(self):
        if self.audio:
            self.audio.stop()
            self.audio = None
        if self.proc and self.proc.poll() is None:
            try:
                if self.proc.stdin:
                    self.proc.stdin.close()
            except OSError:
                pass
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def _watchdog(self):
        """Runs ffmpeg while capturing is on. Fullscreen switches and resolution changes can
        kill the Desktop Duplication session, so capture restarts by itself when that happens."""
        failures = 0
        while self.running:
            if not self.capturing:
                time.sleep(0.2)
                continue
            started = time.time()
            self._launch()
            while self.running and self.capturing and self.proc and self.proc.poll() is None:
                time.sleep(0.2)
            code = self.proc.returncode if self.proc else None
            self._kill()
            if not (self.running and self.capturing):
                continue  # stopped on purpose
            failures = failures + 1 if time.time() - started < 10 else 0
            log.warning("Capture stopped (exit code %s), restarting...", code)
            time.sleep(min(30, 1 + failures * 2))

    def segments(self):
        return sorted(glob.glob(os.path.join(self.seg_dir, "seg_*.ts")))

    def _cleanup_loop(self):
        while self.running:
            time.sleep(SEGMENT_SECONDS)
            keep = math.ceil((self.cfg["buffer_seconds"] + 20) / SEGMENT_SECONDS)
            if self.save_lock.locked():
                continue  # don't delete chunks while a clip is being saved
            for old in self.segments()[:-keep]:
                try:
                    os.remove(old)
                except OSError:
                    pass

    def save_clip(self, seconds=None, tag="", window=None):
        """Saves the last 'seconds', or with window=(start, end) (time.time() values) just that stretch."""
        if not self.save_lock.acquire(blocking=False):
            return None  # already saving, ignore button mashing
        try:
            self.last_tag = tag   # e.g. "Triple kill" when an auto highlight saved it
            seconds = seconds or self.cfg["buffer_seconds"]
            segs = self.segments()
            if segs and self.capturing:
                # the newest chunk is still being written, so wait (max ~2s) for it to finish.
                # that way the clip includes the exact moment you hit the key, with no broken frames
                current = segs[-1]
                deadline = time.time() + SEGMENT_SECONDS + 1.5
                while time.time() < deadline and self.segments()[-1] == current:
                    time.sleep(0.05)
                segs = self.segments()
                if segs[-1] != current:
                    segs = segs[:segs.index(current) + 1] if current in segs else segs[:-1]
            segs = [x for x in segs if _size(x) > 4096]  # skip empty chunks left by a capture crash
            count = math.ceil(seconds / SEGMENT_SECONDS)
            if not self.capturing:
                count += 1  # the last chunk was cut short when capture stopped, so take one more
            pick = segs[-count:]
            if window:
                # each chunk's file time is when it finished, so it covers [time - 2s, time]
                start, end = window
                pick = [x for x in segs if _mtime(x) > start and _mtime(x) - SEGMENT_SECONDS < end]
            self.last_seconds = len(pick) * SEGMENT_SECONDS if window else min(seconds, len(pick) * SEGMENT_SECONDS)
            if not pick:
                self._notify(None, "Nothing recorded yet" if self.capturing else
                             "Not recording right now. Start a game, or switch to Always record")
                return None
            snap = tempfile.mkdtemp(prefix="verse_platform_save_")
            # glue chunks byte for byte, one file per ffmpeg run (.ts files allow this)
            groups = collections.OrderedDict()
            for seg in pick:
                run_id = os.path.basename(seg).split("_")[1]
                try:
                    with open(seg, "rb") as r:
                        groups.setdefault(run_id, bytearray()).extend(r.read())
                except OSError:
                    pass
            parts = []
            for run_id, data in groups.items():
                path = os.path.join(snap, f"run_{run_id}.ts")
                with open(path, "wb") as w:
                    w.write(data)
                parts.append(path)
            if len(parts) > 1:
                # a piece cut off by a capture crash can be too broken to read, so drop those
                parts = [p for p in parts if run_quiet([self.ff, "-v", "error", "-i", p, "-t", "0.2",
                                                        "-f", "null", "-"], timeout=20)[0] == 0] or parts[-1:]
            # read the whole clip when working out its streams, not just the first 5 seconds. Late in a
            # long game the first audio packet can sit further in than that ("sample rate not set")
            probe = ["-fflags", "+genpts+discardcorrupt", "-analyzeduration", "120M", "-probesize", "200M"]
            if len(parts) == 1:
                inputs = probe + ["-i", parts[0]]
            else:  # capture restarted mid-clip: let the concat demuxer line the pieces up
                lst = os.path.join(snap, "list.txt")
                with open(lst, "w", encoding="utf-8") as f:
                    f.writelines(f"file '{p.replace(chr(92), '/')}'\n" for p in parts)
                inputs = probe + ["-f", "concat", "-safe", "0", "-i", lst]
            folder = self.cfg["clips_folder"]
            if self.label and self.cfg.get("sort_clips_by_game", True):
                folder = os.path.join(folder, safe_name(self.label))
                if self.subfolder:
                    folder = os.path.join(folder, safe_name(self.subfolder))
            os.makedirs(folder, exist_ok=True)
            if self.subfolder and self.label:
                stamp = datetime.datetime.now().strftime("%H-%M-%S")
                name = f"{safe_name(tag) or 'Clip'} {stamp}"
            else:
                stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                name = " ".join(x for x in (safe_name(self.label) or "Verse Platform", safe_name(tag), stamp) if x)
            out = os.path.join(folder, f"{name}.mp4")
            base = [self.ff, "-hide_banner", "-loglevel", "error", "-y"] + inputs
            tail = ["-avoid_negative_ts", "make_zero", "-movflags", "+faststart", out]
            attempts = [
                ("normal", ["-map", "0", "-c", "copy"]),
                # sound is damaged: rebuild it, keep the picture as is
                ("fixed audio", ["-map", "0:v", "-map", "0:a?", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                                 "-ar", "48000", "-ac", "2"]),
                # last resort: keep the moment, even without sound
                ("no audio", ["-map", "0:v", "-c", "copy", "-an"]),
            ]
            msg = "Clip saved"
            code, err, first_err = 1, "", ""
            for how, args in attempts:
                code, err = run_quiet(base + args + tail, timeout=180)
                if code == 0 and os.path.exists(out) and _size(out) > 4096:
                    if how != "normal":
                        log.warning("Saved with %s after: %s", how, first_err.strip()[-300:])
                        if how == "no audio":
                            msg = "Clip saved (no sound this time)"
                    break
                if how == "normal":
                    first_err = err
                try:
                    os.remove(out)
                except OSError:
                    pass
            shutil.rmtree(snap, ignore_errors=True)
            if not os.path.exists(out):
                log.error("Saving clip failed: %s", err.strip()[-500:])
                self._notify(None, "Saving the clip failed, check the log")
                return None
            log.info("Saved %s", out)
            self._notify(out, msg)
            return out
        finally:
            self.save_lock.release()

    def _notify(self, path, msg):
        if self.on_saved:
            try:
                self.on_saved(path, msg)
            except Exception:
                log.exception("notify failed")

    def stop(self):
        self.running = False
        self.capturing = False
        self._kill()
        time.sleep(0.3)
        shutil.rmtree(self.seg_dir, ignore_errors=True)


# --------------------------------------------------------------------------- game detection

# Built-in games, matched by the program (exe) name, lowercase.
# The exe is the actual MATCH window, not the launcher. For League that's
# "League of Legends.exe", which only exists while you're in a game. The lobby
# (LeagueClientUx.exe) doesn't count, so lobby time never gets recorded.
KNOWN_GAMES = {
    "league of legends.exe": "League of Legends",      # also TFT and Arena
    "valorant-win64-shipping.exe": "VALORANT",
    "cs2.exe": "Counter-Strike 2",
    "fortniteclient-win64-shipping.exe": "Fortnite",
    "r5apex.exe": "Apex Legends",
    "r5apex_dx12.exe": "Apex Legends",
    "overwatch.exe": "Overwatch 2",
    "rocketleague.exe": "Rocket League",
    "dota2.exe": "Dota 2",
    "gta5.exe": "GTA V",
    "gta5_enhanced.exe": "GTA V",
    "rainbowsix.exe": "Rainbow Six Siege",
    "rainbowsix_vulkan.exe": "Rainbow Six Siege",
    "cod.exe": "Call of Duty",
    "marvel-win64-shipping.exe": "Marvel Rivals",
    "robloxplayerbeta.exe": "Roblox",
    "minecraft.windows.exe": "Minecraft",
    "runelite.exe": "Old School RuneScape",
    "osclient.exe": "Old School RuneScape",
    "eldenring.exe": "Elden Ring",
    "tslgame.exe": "PUBG",
    "deadbydaylight-win64-shipping.exe": "Dead by Daylight",
    "escapefromtarkov.exe": "Escape from Tarkov",
    "destiny2.exe": "Destiny 2",
    "rustclient.exe": "Rust",
    "wow.exe": "World of Warcraft",
}

# Games that share a generic exe, matched by exe + window title instead
TITLE_GAMES = [
    ("javaw.exe", "Minecraft", "Minecraft"),   # Minecraft Java (and modpacks like Cobblemon)
]

# Fullscreen apps that are NOT games (so watching YouTube fullscreen doesn't record)
NOT_GAMES = {
    "explorer.exe", "chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "opera_gx.exe", "brave.exe",
    "vlc.exe", "mpc-hc64.exe", "mpv.exe", "potplayermini64.exe", "wmplayer.exe", "netflix.exe",
    "discord.exe", "spotify.exe", "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe",
    "leagueclientux.exe", "leagueclient.exe", "riotclientux.exe", "riot client.exe", "battle.net.exe",
    "obs64.exe", "powerpnt.exe", "applicationframehost.exe", "lockapp.exe", "searchhost.exe",
    "shellexperiencehost.exe", "startmenuexperiencehost.exe", "verse rewind.exe", "python.exe", "pythonw.exe",
}


class Window:
    __slots__ = ("pid", "exe", "title", "foreground", "fullscreen")

    def __init__(self, pid, exe, title, foreground=False, fullscreen=False):
        self.pid, self.exe, self.title = pid, exe.lower(), title
        self.foreground, self.fullscreen = foreground, fullscreen


def running_exes():
    """Lowercase names of every running program. Only reads the process list,
    never touches game memory, so anti-cheat doesn't care."""
    import psutil
    names = set()
    for p in psutil.process_iter(["name"]):
        n = p.info.get("name")
        if n:
            names.add(n.lower())
    return names


def visible_windows():
    """Top level windows with a title, plus which one is in front and whether it's fullscreen."""
    if not IS_WINDOWS:
        return []
    import ctypes
    from ctypes import wintypes
    import psutil
    u32 = ctypes.windll.user32
    pid_names = {p.info["pid"]: p.info["name"] or "" for p in psutil.process_iter(["pid", "name"])}
    fg = u32.GetForegroundWindow()

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    def is_fullscreen(hwnd):
        r = wintypes.RECT()
        if not u32.GetWindowRect(hwnd, ctypes.byref(r)):
            return False
        mon = u32.MonitorFromWindow(hwnd, 2)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not u32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            return False
        m = mi.rcMonitor
        return r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom

    out = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if not u32.IsWindowVisible(hwnd) or u32.IsIconic(hwnd):
            return True
        n = u32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(hwnd, buf, n + 1)
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        is_fg = hwnd == fg
        out.append(Window(pid.value, pid_names.get(pid.value, ""), buf.value, is_fg, is_fg and is_fullscreen(hwnd)))
        return True

    u32.EnumWindows(proto(cb), 0)
    return out


class GameWatcher:
    """Works out which game (if any) is being played right now."""

    def __init__(self, get_cfg, list_exes=running_exes, list_windows=visible_windows):
        self.get_cfg, self.list_exes, self.list_windows = get_cfg, list_exes, list_windows
        self.last_fullscreen_app = None

    def games(self):
        cfg = self.get_cfg()
        g = dict(KNOWN_GAMES)
        g.update({k.lower(): v for k, v in cfg.get("custom_games", {}).items()})
        for ign in cfg.get("ignored_apps", []):
            g.pop(ign.lower(), None)
        return g

    def detect(self):
        """Returns the name of the game being played, or None."""
        cfg = self.get_cfg()
        ignored = {x.lower() for x in cfg.get("ignored_apps", [])}
        games = self.games()
        exes = self.list_exes()
        for exe in sorted(exes):
            if exe in games:
                return games[exe]
        windows = self.list_windows()
        for w in windows:
            for exe, title, name in TITLE_GAMES:
                if w.exe == exe and w.title.startswith(title) and exe not in ignored:
                    return name
        if cfg.get("detect_fullscreen_apps", True):
            for w in windows:
                if w.fullscreen and w.exe and w.exe not in NOT_GAMES and w.exe not in ignored:
                    self.last_fullscreen_app = w
                    return w.title.strip() or os.path.splitext(w.exe)[0]
        return None


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def safe_name(text):
    return "".join(ch for ch in (text or "") if ch not in '<>:"/\\|?*').strip()


# --------------------------------------------------------------------------- windows helpers

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def message_box(text, error=False):
    if IS_WINDOWS:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, APP_NAME, 0x10 if error else 0x40)
    else:
        print(text)


def already_running():
    """Only allow one copy of the app at a time (a named Windows mutex)."""
    if not IS_WINDOWS:
        return False
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\VersePlatformDesktop")
    return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


def startup_command():
    if FROZEN:
        return f'"{sys.executable}" --background'
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    main_py = os.path.join(HERE, "verse_desktop.py")
    return f'"{pyw if os.path.exists(pyw) else sys.executable}" "{main_py}" --background'


def get_autostart():
    if not IS_WINDOWS:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(enabled):
    if not IS_WINDOWS:
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass


def open_path(path):
    if IS_WINDOWS:
        os.startfile(path)


def list_mics(ff):
    _, err = run_quiet([ff, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"])
    mics = []
    for line in err.splitlines():
        if "(audio)" in line:
            name = line.split("]", 1)[-1].strip().split(" (audio)")[0].strip().strip('"')
            if name and name not in mics:
                mics.append(name)
    return mics


def load_icon_image():
    from PIL import Image
    for p in (os.path.join(RES, "assets", "logo.png"), os.path.join(HERE, "assets", "logo.png")):
        if os.path.exists(p):
            return Image.open(p)
    from PIL import ImageDraw  # fallback if the logo file went missing
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((8, 8, 56, 56), fill=(30, 120, 200, 255))
    return img


# --------------------------------------------------------------------------- tray app
