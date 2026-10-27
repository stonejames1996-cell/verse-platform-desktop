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
import uuid

APP_NAME = "Verse Platform"
APP_VERSION = "1.2.9"
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
    "monitor": 0,                  # 0 = main monitor, 1 = second monitor... (when the game's screen isn't known)
    "follow_game_screen": True,    # record whichever screen the game is on
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
    "clip_watermark": True,        # always on, see load_config
    "death_review": False,         # save the lead up to every death in a private Deaths folder
    "death_review_before": 10,
    "squad_code": "",              # squad POV: friends with the same code clip each other's highlights
    "squad_name": "",              # how you show up to your squad, blank = your in-game name
    "squad_share": True,           # send your POV of a squad mate's highlight to them
    "device_id": "",
    "gsi_port": 3517,              # Counter-Strike 2 and Dota 2 send live game info to this local port
    "voice_command": False,        # say "clip that" to save a clip (Windows speech recognition, offline)
    "controller_combo": "view_rb", # controller buttons that save a clip, blank = off (see triggers.COMBOS)
    "auto_clean_days": 0,          # remove unstarred, unposted clips older than this, 0 = never
    "auto_clean_permanent": False, # skip the Recycle Bin when cleaning up        # "Clipped by Verse Platform" in the first 2 seconds of every clip     # "Last 60s saved by Verse Platform" pop-up over the game
    "auto_highlights": True,       # clip big plays by themselves (League of Legends)
    "lol_item_ideas": True,        # League: while you're dead, your numbers, lane gold and counter item ideas
    "lol_objective_timers": True,  # League: Dragon, Baron and inhibitor respawn timers on the right
    "lol_match_summary": True,     # League: a summary card when the game ends
    "item_ideas_hotkey": "alt+shift+i",  # show the item ideas any time in a League match
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

FREEZE_SECONDS = 8   # a picture that hasn't changed at all for this long means capture went stale


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
    if not cfg.get("device_id"):
        cfg["device_id"] = uuid.uuid4().hex
    cfg["clip_watermark"] = True  # "Clipped by Verse Platform" is always on, it isn't a setting any more
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


def windows_build():
    try:
        return sys.getwindowsversion().build
    except AttributeError:
        return 0


def pick_capture(ff, wanted, monitor):
    if wanted and wanted != "auto":
        return wanted
    if not IS_WINDOWS:
        return "x11grab"
    # Windows 11: Windows Graphics Capture. It shares the screen nicely with Discord, OBS and other
    # recorders. (Windows 10 draws a yellow border around the screen while it records, so not there.)
    if windows_build() >= 22000:
        code, err = run_quiet([ff, "-hide_banner", "-f", "lavfi", "-i",
                               f"gfxcapture=monitor_idx={monitor}:max_framerate=30", "-frames:v", "2",
                               "-vf", "hwdownload,format=bgra", "-f", "null", "-"])
        if code == 0:
            return "gfxcapture"
        log.warning("Windows Graphics Capture didn't start, using Desktop Duplication: %s", (err or "").strip()[-200:])
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
        last_warn = -999.0
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
            t0 = time.perf_counter()
            try:
                sink.write(chunk)
                sink.flush()
            except (BrokenPipeError, OSError, ValueError):
                return
            stalled = time.perf_counter() - t0
            if stalled > 1.0 and time.perf_counter() - last_warn > 30:
                last_warn = time.perf_counter()
                log.warning("Sound was held up for %.1fs (the recorder wasn't taking it)", stalled)
            written += need


class Loopback:
    """Desktop audio from one output device (WASAPI loopback). Unpacks like the old
    (rate, channels, source) tuple. close() frees the device so another can be opened."""

    def __init__(self, pa, info):
        self.pa, self.info = pa, info
        self.rate = int(info["defaultSampleRate"])
        self.channels = max(1, min(2, int(info["maxInputChannels"])))
        self.name = info["name"]

    def __iter__(self):
        return iter((self.rate, self.channels, self.source))

    def source(self, stop_event, out_q):
        """Runs in its own thread. Uses a callback stream, so nothing blocks while no sound plays
        (the writer pads silence) and stopping is instant."""
        import pyaudiowpatch as pyaudio

        def got(data, frame_count, time_info, status):
            out_q.put(data)
            return (None, pyaudio.paContinue)

        stream = self.pa.open(format=pyaudio.paInt16, channels=self.channels, rate=self.rate, input=True,
                              input_device_index=self.info["index"], frames_per_buffer=self.rate // 100,
                              stream_callback=got)
        try:
            stream.start_stream()
            stop_event.wait()
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass

    def close(self):
        try:
            self.pa.terminate()
        except Exception:
            pass


def open_loopback():
    """Loopback for the CURRENT default speakers/headset, or None. Starts a fresh PyAudio each time
    so a headset plugged in after the app started is found."""
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
                pa.terminate()
                return None
    except Exception as e:
        log.error("Could not open desktop audio: %s", e)
        pa.terminate()
        return None
    lb = Loopback(pa, speakers)
    log.info("Desktop audio: %s (%d Hz, %d ch)", lb.name, lb.rate, lb.channels)
    return lb


def default_output_id():
    """Windows' current default speakers/headset (its endpoint id), straight from Core Audio, so a
    change is seen even while PortAudio still has the old device list. None if it can't be read."""
    if not IS_WINDOWS:
        return None
    import ctypes
    from ctypes import POINTER, byref, c_void_p, c_wchar_p
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx(None, 0)          # fine if this thread already has COM
    clsid, iid = (ctypes.c_byte * 16)(), (ctypes.c_byte * 16)()
    ole32.CLSIDFromString(c_wchar_p("{BCDE0395-E52F-467C-8E3D-C4579291692E}"), byref(clsid))
    ole32.CLSIDFromString(c_wchar_p("{A95664D2-9614-4F35-A746-DE8DB63617E6}"), byref(iid))
    enum = c_void_p()
    if ole32.CoCreateInstance(byref(clsid), None, 23, byref(iid), byref(enum)) != 0 or not enum:
        return None

    def method(obj, index, *argtypes):
        vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, *argtypes)(vtbl[index])

    device = c_void_p()
    try:
        # IMMDeviceEnumerator::GetDefaultAudioEndpoint(eRender, eConsole, &device)
        if method(enum, 4, ctypes.c_int, ctypes.c_int, POINTER(c_void_p))(enum, 0, 0, byref(device)) != 0 or not device:
            return None
        text = c_wchar_p()
        try:
            # IMMDevice::GetId(&text)
            if method(device, 5, POINTER(c_wchar_p))(device, byref(text)) != 0:
                return None
            value = text.value
            ole32.CoTaskMemFree(text)
            return value
        finally:
            method(device, 2)(device)      # Release
    finally:
        method(enum, 2)(enum)              # Release


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
        self.last_start = 0.0
        self.freeze_path = ""
        self.last_freeze = 0.0
        self.freezes = 0
        self.unfreeze_path = ""
        self._tried = set()
        self.zero_copy = True
        self._audio_reload = False   # the default speakers/headset changed: reopen desktop audio
        self._screen_reload = False  # the game moved to (or opened on) another screen
        self.screen = None           # HMONITOR of the game's screen, None = the screen picked in Settings
        self._hmonitor_ok = None     # does this FFmpeg's gfxcapture take hmonitor=? (checked once)
        self._out_id = None
        self.save_lock = threading.Lock()
        self.on_saved = None  # callback(path or None, message)
        self.encoder = pick_encoder(ff, cfg["encoder"])
        self.capture = pick_capture(ff, cfg["capture"], cfg["monitor"])
        self.audio_info = open_loopback() if (cfg["record_desktop_audio"] and IS_WINDOWS) else None

    # these two methods are separate so the self test can swap in fake sources
    def follow_screen(self, hmon):
        """Record the screen the game is on (hmon), or the one picked in Settings (None).
        Restarts capture when it changes."""
        if hmon == self.screen:
            return
        self.screen = hmon
        log.info("Recording %s", f"the game's screen ({screen_name(hmon)})" if hmon else "the screen picked in Settings")
        if self.capturing:
            self._screen_reload = True

    def _source(self, kind, fps, cursor=None):
        """The lavfi source for ddagrab / gfxcapture, aimed at the game's screen when we know it."""
        c = self.cfg
        dda_idx = c["monitor"]
        if self.screen:
            i = dxgi_output_index(self.screen)
            if i is not None:
                dda_idx = i
        if kind == "ddagrab":
            src = f"ddagrab=output_idx={dda_idx}:framerate={fps}"
            return src + (f":draw_mouse={int(cursor)}" if cursor is not None else "")
        where = f"monitor_idx={c['monitor']}"
        if self.screen:
            if self._hmonitor_ok is None:
                code, err = run_quiet([self.ff, "-hide_banner", "-f", "lavfi", "-i",
                                       f"gfxcapture=hmonitor={self.screen}:max_framerate=30", "-frames:v", "2",
                                       "-vf", "hwdownload,format=bgra", "-f", "null", "-"])
                self._hmonitor_ok = code == 0
                if not self._hmonitor_ok:
                    log.info("gfxcapture can't aim at a screen directly here, using its number: %s",
                             (err or "").strip()[-200:])
            where = f"hmonitor={self.screen}" if self._hmonitor_ok else f"monitor_idx={dda_idx}"
        src = f"gfxcapture={where}:max_framerate={fps}"
        return src + (f":capture_cursor={int(cursor)}" if cursor is not None else "")

    def video_input_args(self):
        c = self.cfg
        if self.capture == "ddagrab":
            return (["-f", "lavfi", "-i", self._source("ddagrab", c["fps"], c["draw_mouse"])],
                    "hwdownload,format=bgra")
        if self.capture == "gfxcapture":
            # Windows Graphics Capture: the newer capture path, which keeps working while Discord
            # (or OBS) is sharing the screen. It only sends a frame when something changes, so fps
            # turns it back into a steady frame rate
            return (["-f", "lavfi", "-i", self._source("gfxcapture", c["fps"], c["draw_mouse"])],
                    f"hwdownload,format=bgra,fps={c['fps']}")
        if self.capture == "gdigrab":
            area = []
            r = screen_rect(self.screen) if self.screen else None
            if r:   # just the game's screen, not every screen glued together
                area = ["-offset_x", str(r[0]), "-offset_y", str(r[1]), "-video_size", f"{r[2] - r[0]}x{r[3] - r[1]}"]
            return (["-f", "gdigrab", "-framerate", str(c["fps"]),
                     "-draw_mouse", str(int(c["draw_mouse"]))] + area + ["-i", "desktop"], "")
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

        # GPU only: the captured frames stay on the graphics card and go straight into its encoder, no
        # copy to the processor and no conversion there. Only a 4 fps copy comes down for the freeze check.
        zero = self.zero_copy_ok()
        if zero:
            keep_fps = f"fps={c['fps']}," if self.capture == "gfxcapture" else ""
            graph = f"[0:v]{keep_fps}split=2[v][fz0];[fz0]fps=4,hwdownload,format=bgra,"
        vf = [f for f in (vpre,) if f]
        if c["output_height"]:
            vf.append(f"scale=-2:{int(c['output_height'])}")
        vf.append("format=yuv420p" if self.encoder == "libx264" else "format=nv12")
        # a small copy of the picture goes through freezedetect. Every time the picture stops changing
        # for 2s it notes the start (and later the end) in two small files the watchdog reads:
        #  * one freeze that lasts 8s: Windows' screen capture went stale -> restart it
        #  * lots of short freezes: capture is being starved, which Discord screen share does to the
        #    old capture method -> switch to Windows Graphics Capture
        self.freeze_path = os.path.join(self.seg_dir, f"freeze_{self.run:05d}.txt")
        self.unfreeze_path = os.path.join(self.seg_dir, f"unfreeze_{self.run:05d}.txt")
        esc = lambda p: p.replace("\\", "/").replace(":", "\\:")
        if not zero:
            graph = f"[0:v]{','.join(vf)},split=2[v][fz];[fz]"
        graph += (f"scale=160:-2,freezedetect=n=0.001:d=2,"
                 f"metadata=mode=print:key=lavfi.freezedetect.freeze_start:file='{esc(self.freeze_path)}':direct=1,"
                 f"metadata=mode=print:key=lavfi.freezedetect.freeze_end:file='{esc(self.unfreeze_path)}':direct=1,nullsink")
        # sound gets its own filter graph so a slow picture can never hold up the sound (or the other way)
        agraph = ""
        two_tracks = len(audio_labels) == 2 and bool(self.audio_info)
        if audio_labels:
            if two_tracks:
                # track 1: game + mic (what you hear when you play the clip)
                # track 2: game only, so your voice can be taken out before posting
                desk, mic = audio_labels
                agraph = (f"{desk}aresample=48000:async=1000,asplit=2[d1][d2]"
                          f";{mic}aresample=48000:async=1000[m]"
                          f";[d1][m]amix=inputs=2:duration=longest:normalize=0[a];[d2]anull[g]")
            elif len(audio_labels) == 2:
                agraph = f"{''.join(audio_labels)}amix=inputs=2:duration=longest:normalize=0,aresample=48000:async=1000[a]"
            else:
                agraph = f"{audio_labels[0]}aresample=48000:async=1000[a]"
        if agraph:
            cmd += ["-filter_complex", agraph]
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
        if self.cfg["record_desktop_audio"] and IS_WINDOWS:
            threading.Thread(target=self._device_loop, daemon=True, name="audio-device").start()
        log.info("Ready. Encoder=%s Capture=%s%s Buffer=%ss Hotkey=%s", self.encoder, self.capture,
                 " (GPU only)" if self.zero_copy_ok() else "", self.cfg["buffer_seconds"], self.cfg["hotkey"])
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

    def zero_copy_ok(self):
        """Frames can stay on the GPU when Windows captures them there (ddagrab / gfxcapture), the
        encoder is NVIDIA or AMD, and there's no resize. Turned off for good if it ever fails."""
        return (self.zero_copy and self.capture in ("ddagrab", "gfxcapture") and not self.cfg["output_height"]
                and ("nvenc" in self.encoder or "amf" in self.encoder))

    def _device_loop(self):
        """Follows Windows' default speakers/headset. Switch to your headset after the app started
        (or turn it on) and recording follows within a few seconds."""
        failed = False
        while self.running:
            time.sleep(3)
            try:
                now = default_output_id()
            except Exception:
                if not failed:
                    log.debug("Couldn't read the default sound device", exc_info=True)
                failed = True
                continue
            if not now:
                continue
            if self._out_id and now != self._out_id:
                log.info("Sound output changed, recording follows it")
                self._audio_reload = True
            elif self._out_id is None and not self.audio_info:
                self._audio_reload = True    # no sound device at start, there is one now
            self._out_id = now

    def _launch(self):
        if self._audio_reload:
            self._audio_reload = False
            old, self.audio_info = self.audio_info, None
            if old is not None and hasattr(old, "close"):
                old.close()
            self.audio_info = open_loopback()
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
            for t in self.audio.threads[:1]:   # let the sound device let go before it might be reopened
                t.join(2)
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
            problem = self._watch_picture(started)
            code = self.proc.returncode if self.proc else None
            self._kill()
            if not (self.running and self.capturing):
                continue  # stopped on purpose
            if problem in ("audio", "screen"):
                continue          # relaunches straight away on the new sound device / screen
            if problem:
                self.freezes += 1
                self.last_freeze = time.time()
                alt = self.fallback_capture() if problem == "starved" or self.freezes >= 2 else None
                if alt and alt != self.capture:
                    log.warning("Screen capture is being starved (%s). Switching from %s to %s for this session",
                                "the picture keeps stalling" if problem == "starved" else "it froze again",
                                self.capture, alt)
                    self._tried.add(self.capture)
                    self.capture = alt
                else:
                    log.warning("Capture froze (the screen stopped updating for %ss), restarting it", FREEZE_SECONDS)
                time.sleep(0.3)
                continue
            failures = failures + 1 if time.time() - started < 10 else 0
            log.warning("Capture stopped (exit code %s), restarting...", code)
            if failures >= 2 and self.zero_copy_ok():
                log.warning("GPU-only recording didn't work on this PC, using the standard path")
                self.zero_copy = False
                failures = 0
                continue
            if failures >= 3:
                alt = self.fallback_capture()
                if alt:
                    log.warning("%s keeps stopping, switching to %s for this session", self.capture, alt)
                    self._tried.add(self.capture)
                    self.capture = alt
                    failures = 0
            time.sleep(min(30, 1 + failures * 2))

    def _watch_picture(self, started):
        """Waits while ffmpeg runs. Returns "frozen", "starved" or None (ffmpeg stopped / capture stopped)."""
        starts_seen, open_since, recent = 0, None, []
        while self.running and self.capturing and self.proc and self.proc.poll() is None:
            time.sleep(0.25)
            if self._audio_reload:
                return "audio"
            if self._screen_reload:
                self._screen_reload = False
                return "screen"
            starts = _count(self.freeze_path, "freeze_start=")
            ends = _count(self.unfreeze_path, "freeze_end=")
            now = time.time()
            if starts > starts_seen:
                recent += [now] * (starts - starts_seen)
                starts_seen = starts
            recent = [t for t in recent if now - t < 40]
            open_since = (open_since or now) if starts > ends else None
            if now - self.last_freeze < 30:
                continue          # just restarted, give it a moment
            if open_since and now - open_since > FREEZE_SECONDS - 2:
                return "frozen"   # one picture for 8s straight
            # loading screens can be still for a while, so only judge after the first 2 minutes
            if len(recent) >= 4 and now - started > 120 and self.capture != "gdigrab":
                return "starved"  # the picture keeps stalling: capture is being starved
        return None

    def fallback_capture(self):
        """The capture method to switch to when the current one gets starved or keeps freezing:
        Windows Graphics Capture <-> Desktop Duplication, then the old GDI capture as a last resort."""
        if not IS_WINDOWS:
            return ""
        order = ["gfxcapture", "ddagrab", "gdigrab"] if windows_build() >= 22000 else ["ddagrab", "gfxcapture", "gdigrab"]
        for alt in order:
            if alt == self.capture or alt in self._tried:
                continue
            self._tried.add(alt)
            if alt == "gdigrab":
                return alt
            src = self._source(alt, 30)
            code, err = run_quiet([self.ff, "-hide_banner", "-f", "lavfi", "-i", src, "-frames:v", "2",
                                   "-vf", "hwdownload,format=bgra", "-f", "null", "-"], timeout=20)
            if code == 0:
                return alt
            log.info("%s isn't available here: %s", alt, (err or "").strip()[-200:])
        return ""

    def segments(self):
        return sorted(glob.glob(os.path.join(self.seg_dir, "seg_*.ts")))

    def _cleanup_loop(self):
        while self.running:
            time.sleep(SEGMENT_SECONDS)
            # keep at least 2 minutes: a CS round's kills, a death review and a squad mate's
            # highlight can reach further back than a short clip length
            keep = math.ceil((max(self.cfg["buffer_seconds"], 120) + 20) / SEGMENT_SECONDS)
            if self.save_lock.locked():
                continue  # don't delete chunks while a clip is being saved
            for old in self.segments()[:-keep]:
                try:
                    os.remove(old)
                except OSError:
                    pass

    def save_clip(self, seconds=None, tag="", window=None, wait=False, quiet=False, folder_extra=""):
        """Saves the last 'seconds', or with window=(start, end) (time.time() values) just that stretch.
        wait: queue behind a save that's already running (auto clips) instead of skipping it (key mashing).
        quiet: don't announce it (death reviews, squad clips handle their own messages).
        folder_extra: a subfolder inside the match folder, e.g. "Deaths"."""
        if not self.save_lock.acquire(timeout=60) if wait else not self.save_lock.acquire(blocking=False):
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
            # when the saved video really starts (each chunk's file time is when it ended), for lining up squad POVs
            self.last_start = (_mtime(pick[0]) - SEGMENT_SECONDS) if pick else 0.0
            if not pick:
                if quiet:
                    return None
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
                    if folder_extra:
                        folder = os.path.join(folder, safe_name(folder_extra))
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
                if not quiet:
                    self._notify(None, "Saving the clip failed, check the log")
                return None
            log.info("Saved %s", out)
            if not quiet:
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


# ---------------------------------------------------------------- screens
def monitor_of(hwnd):
    """The screen (HMONITOR, as an int) a window is mostly on."""
    if not IS_WINDOWS or not hwnd:
        return None
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.WinDLL("user32")   # own copy, so these argtypes don't leak into other code
    u32.IsWindow.argtypes = [wintypes.HWND]
    u32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    u32.MonitorFromWindow.restype = ctypes.c_void_p   # a handle, keep all 64 bits
    if not u32.IsWindow(hwnd):
        return None
    return u32.MonitorFromWindow(hwnd, 2) or None    # MONITOR_DEFAULTTONEAREST


def _monitor_info(hmon):
    import ctypes
    from ctypes import wintypes

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]
    u32 = ctypes.WinDLL("user32")
    u32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    mi = MONITORINFOEXW()
    mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
    if not u32.GetMonitorInfoW(ctypes.c_void_p(hmon), ctypes.byref(mi)):
        return None
    m = mi.rcMonitor
    return (m.left, m.top, m.right, m.bottom), mi.szDevice, bool(mi.dwFlags & 1)


def screen_rect(hmon):
    """(left, top, right, bottom) of a screen, or None."""
    if not IS_WINDOWS or not hmon:
        return None
    try:
        info = _monitor_info(hmon)
        return info[0] if info else None
    except Exception:
        return None


def screen_name(hmon):
    try:
        info = _monitor_info(hmon)
        if info:
            (l, t, r, b), dev, primary = info
            return f"{dev.replace(chr(92) * 2 + '.' + chr(92), '')} {r - l}x{b - t}{', main' if primary else ''}"
    except Exception:
        pass
    return "unknown"


def dxgi_output_index(hmon):
    """Which output_idx Desktop Duplication (ddagrab) uses for this screen: its place in the list of
    screens on the main graphics card. None if it isn't on that card (or anything goes wrong)."""
    if not IS_WINDOWS or not hmon:
        return None
    import ctypes
    try:
        class GUID(ctypes.Structure):
            _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]

        class RECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]

        class DXGI_OUTPUT_DESC(ctypes.Structure):
            _fields_ = [("DeviceName", ctypes.c_wchar * 32), ("DesktopCoordinates", RECT),
                        ("AttachedToDesktop", ctypes.c_int), ("Rotation", ctypes.c_uint), ("Monitor", ctypes.c_void_p)]

        def vcall(obj, index, *args):
            vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *[type(a) for a in args])(vtbl[index])
            return fn(obj, *args)

        iid = GUID(0x770AAE78, 0xF26F, 0x4DBA, (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
        factory = ctypes.c_void_p()
        if ctypes.WinDLL("dxgi").CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory)) != 0:
            return None
        adapter = ctypes.c_void_p()
        try:
            # IDXGIFactory1::EnumAdapters1 is slot 12, IDXGIAdapter::EnumOutputs 7, IDXGIOutput::GetDesc 7, Release 2
            if vcall(factory, 12, ctypes.c_uint(0), ctypes.pointer(adapter)) != 0:
                return None
            want = int(hmon)
            for i in range(16):
                out = ctypes.c_void_p()
                if vcall(adapter, 7, ctypes.c_uint(i), ctypes.pointer(out)) != 0:
                    break
                desc = DXGI_OUTPUT_DESC()
                ok = vcall(out, 7, ctypes.pointer(desc)) == 0
                vcall(out, 2)
                if ok and (desc.Monitor or 0) == want:
                    return i
            return None
        finally:
            if adapter:
                vcall(adapter, 2)
            vcall(factory, 2)
    except Exception:
        log.debug("Couldn't match the screen to Desktop Duplication", exc_info=True)
        return None


class Window:
    __slots__ = ("pid", "exe", "title", "foreground", "fullscreen", "hwnd", "area")

    def __init__(self, pid, exe, title, foreground=False, fullscreen=False, hwnd=0, area=0):
        self.pid, self.exe, self.title = pid, exe.lower(), title
        self.foreground, self.fullscreen = foreground, fullscreen
        self.hwnd, self.area = hwnd, area   # window handle and size, to find the screen a game is on


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
        r = wintypes.RECT()
        area = (r.right - r.left) * (r.bottom - r.top) if u32.GetWindowRect(hwnd, ctypes.byref(r)) else 0
        out.append(Window(pid.value, pid_names.get(pid.value, ""), buf.value, is_fg, is_fg and is_fullscreen(hwnd),
                          hwnd or 0, area))
        return True

    u32.EnumWindows(proto(cb), 0)
    return out


class GameWatcher:
    """Works out which game (if any) is being played right now."""

    def __init__(self, get_cfg, list_exes=running_exes, list_windows=visible_windows):
        self.get_cfg, self.list_exes, self.list_windows = get_cfg, list_exes, list_windows
        self.last_fullscreen_app = None
        self.game_window = None   # the game's main window, so recording can follow it to its screen

    def game_screen(self):
        """HMONITOR of the screen the game is on, or None if we can't tell."""
        w = self.game_window
        return monitor_of(w.hwnd) if w and w.hwnd else None

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
        windows = None
        for exe in sorted(exes):
            if exe in games:
                windows = self.list_windows()
                mine = [w for w in windows if w.exe == exe and w.hwnd]
                # the window in front, else the biggest one (games often have small helper windows)
                self.game_window = max(mine, key=lambda w: (w.foreground, w.area)) if mine else self.game_window
                return games[exe]
        windows = windows if windows is not None else self.list_windows()
        for w in windows:
            for exe, title, name in TITLE_GAMES:
                if w.exe == exe and w.title.startswith(title) and exe not in ignored:
                    self.game_window = w
                    return name
        if cfg.get("detect_fullscreen_apps", True):
            for w in windows:
                if w.fullscreen and w.exe and w.exe not in NOT_GAMES and w.exe not in ignored:
                    self.last_fullscreen_app = w
                    self.game_window = w
                    return w.title.strip() or os.path.splitext(w.exe)[0]
        self.game_window = None
        return None


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _count(path, text):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().count(text)
    except OSError:
        return 0


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
