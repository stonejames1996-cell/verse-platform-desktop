"""
Other ways to save a clip besides the keyboard shortcut:
  * Voice: say "clip that". Uses Windows' own offline speech recognition (System.Speech), so
    nothing is sent anywhere and there's nothing extra to download. Listens on the Windows
    default microphone, only while the setting is on.
  * Controller: a button combo on any Xbox-style (XInput) controller, e.g. View + RB.
"""

import ctypes
import logging
import sys
import threading
import time

log = logging.getLogger("verse.triggers")
IS_WINDOWS = sys.platform == "win32"

PHRASES = ["clip that", "clip it", "verse clip that", "save that", "clip that verse"]

# XInput button bits
BTN = {"up": 0x0001, "down": 0x0002, "left": 0x0004, "right": 0x0008, "menu": 0x0010, "view": 0x0020,
       "ls": 0x0040, "rs": 0x0080, "lb": 0x0100, "rb": 0x0200, "a": 0x1000, "b": 0x2000, "x": 0x4000, "y": 0x8000}
COMBOS = {
    "view_rb": ("View + RB", BTN["view"] | BTN["rb"]),
    "view_y": ("View + Y", BTN["view"] | BTN["y"]),
    "sticks": ("Click both sticks", BTN["ls"] | BTN["rs"]),
    "lb_rb_down": ("LB + RB + D-pad down", BTN["lb"] | BTN["rb"] | BTN["down"]),
}


class VoiceTrigger:
    def __init__(self, on_trigger):
        self.on_trigger = on_trigger
        self.engine = None
        self.last = 0.0
        self.error = ""

    @property
    def running(self):
        return self.engine is not None

    def start(self):
        if self.engine or not IS_WINDOWS:
            return self.running
        try:
            import clr  # pythonnet, already used by the app window
            clr.AddReference("System.Speech")
            from System.Globalization import CultureInfo
            from System.Speech.Recognition import (Choices, Grammar, GrammarBuilder, RecognizeMode,
                                                   SpeechRecognitionEngine)
            try:
                eng = SpeechRecognitionEngine(CultureInfo("en-US"))
            except Exception:
                eng = SpeechRecognitionEngine()  # whatever language Windows has installed
            choices = Choices()
            for p in PHRASES:
                choices.Add(p)
            eng.LoadGrammar(Grammar(GrammarBuilder(choices)))
            eng.SetInputToDefaultAudioDevice()
            eng.SpeechRecognized += self._heard
            eng.RecognizeAsync(RecognizeMode.Multiple)
            self.engine = eng
            self.error = ""
            log.info("Voice command on: say \"clip that\"")
        except Exception as e:
            self.error = "Windows speech recognition isn't available on this PC"
            log.warning("Voice command unavailable: %s", e)
            self.engine = None
        return self.running

    def stop(self):
        if self.engine:
            try:
                from System.Speech.Recognition import RecognizeMode  # noqa: F401
                self.engine.RecognizeAsyncCancel()
                self.engine.Dispose()
            except Exception:
                pass
            self.engine = None
            log.info("Voice command off")

    def _heard(self, sender, e):
        try:
            conf, text = float(e.Result.Confidence), str(e.Result.Text)
        except Exception:
            return
        if conf < 0.72 or time.time() - self.last < 4:
            return
        self.last = time.time()
        log.info("Heard \"%s\" (%.2f)", text, conf)
        threading.Thread(target=self.on_trigger, daemon=True).start()


class _GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", ctypes.c_ushort), ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short),
                ("sThumbRX", ctypes.c_short), ("sThumbRY", ctypes.c_short)]


class _STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", _GAMEPAD)]


class ControllerTrigger:
    """Polls XInput controllers and fires when the chosen combo is pressed."""

    def __init__(self, get_combo, on_trigger):
        self.get_combo, self.on_trigger = get_combo, on_trigger
        self.dll = None
        if IS_WINDOWS:
            for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
                try:
                    self.dll = getattr(ctypes.windll, name)
                    break
                except OSError:
                    continue
        if self.dll:
            self.dll.XInputGetState.argtypes = [ctypes.c_uint, ctypes.POINTER(_STATE)]
            self.dll.XInputGetState.restype = ctypes.c_uint

    def start(self):
        if self.dll:
            threading.Thread(target=self._loop, daemon=True, name="controller").start()

    def _loop(self):
        held = [False] * 4
        last_fire = 0.0
        pads = []
        last_scan = 0.0
        state = _STATE()
        while True:
            combo = COMBOS.get(self.get_combo() or "")
            if not combo:
                time.sleep(1)
                continue
            mask = combo[1]
            now = time.time()
            if now - last_scan > 3 or not pads:  # look for newly plugged in controllers now and then
                pads = [i for i in range(4) if self.dll.XInputGetState(i, ctypes.byref(state)) == 0]
                last_scan = now
                if not pads:
                    time.sleep(1)
                    continue
            for i in pads:
                if self.dll.XInputGetState(i, ctypes.byref(state)) != 0:
                    continue
                down = (state.Gamepad.wButtons & mask) == mask
                if down and not held[i] and now - last_fire > 2:
                    last_fire = now
                    log.info("Controller combo %s pressed", combo[0])
                    threading.Thread(target=self.on_trigger, daemon=True).start()
                held[i] = down
            time.sleep(0.04)
