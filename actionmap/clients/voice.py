"""Voice I/O for the laptop (D-007, D-009, D-013). Mouth and ears only: the
conversation agent does the thinking, so the same commands work typed on the
map, spoken here, or relayed by an outside AI.

Listening presets come from the hub (versioned control events), per machine and
per app, and can be combined:
  ptt     hold the push-to-talk key (default: right Ctrl) and speak
  wake    say the wake word ("hey jarvis" by default), then speak
  always  every spoken sentence is transcribed (never while the agent is talking)
Pressing push-to-talk while the agent is talking cuts it off (barge-in).

Speech-to-text runs locally on CPU (faster-whisper, English). Audio never leaves
the machine; only the transcript goes to the hub.

    pip install -r requirements-voice.txt
    python -m clients.voice              # microphone + speakers
    python -m clients.voice --text       # type instead of speaking (any OS)
"""
from __future__ import annotations

import argparse
import queue
import sys
import threading
import time

from .common import Spine, config

VCFG = config().get("voice", {})
RATE = 16000


# ------------------------------------------------------------------ speaking
class Speaker:
    """Windows SAPI with real interrupt; pyttsx3 elsewhere; print as last resort."""

    def __init__(self, enabled: bool = True):
        self.busy_until = 0.0
        self.kind = "print"
        if not enabled:
            return
        if sys.platform == "win32":
            try:
                import win32com.client
                self.sapi = win32com.client.Dispatch("SAPI.SpVoice")
                self.sapi.Rate = int(VCFG.get("rate", 1))
                self.kind = "sapi"
                return
            except Exception as e:
                print("[voice] SAPI unavailable:", e)
        try:
            import pyttsx3
            self.engine = pyttsx3.init()
            self.kind = "pyttsx3"
        except Exception:
            pass

    def say(self, text: str):
        print(f"🔊 {text}")
        self.busy_until = time.time() + 0.07 * len(text.split()) * 6 + 0.5
        if self.kind == "sapi":
            self.sapi.Speak(text, 1 | 2)          # async + purge whatever was playing
        elif self.kind == "pyttsx3":
            threading.Thread(target=self._py, args=(text,), daemon=True).start()

    def _py(self, text):
        try:
            self.engine.say(text); self.engine.runAndWait()
        except RuntimeError:
            pass

    def stop(self):
        self.busy_until = 0
        if self.kind == "sapi":
            self.sapi.Speak("", 2)
        elif self.kind == "pyttsx3":
            try:
                self.engine.stop()
            except Exception:
                pass

    @property
    def speaking(self) -> bool:
        if self.kind == "sapi":
            try:
                return self.sapi.Status.RunningState == 2
            except Exception:
                pass
        return time.time() < self.busy_until


# ------------------------------------------------------------------ listening
class Ears:
    def __init__(self, sp: Spine, speaker: Speaker, human: str):
        import numpy as np
        import sounddevice as sd
        from faster_whisper import WhisperModel
        self.np, self.sd, self.sp, self.speaker, self.human = np, sd, sp, speaker, human
        print("[voice] loading speech model (first run downloads it)…")
        self.stt = WhisperModel(VCFG.get("stt_model", "base.en"), device="cpu", compute_type="int8")
        self.frames: "queue.Queue" = queue.Queue()
        self.ptt_down = False
        self.ptt_buf: list = []
        self.wake = None
        self.armed_until = 0.0       # after the wake word, listen for one sentence
        self.prefs = {"ptt": True, "wake": False, "always": False}
        self.thr = float(VCFG.get("vad_rms", 0.012))
        self.silence = float(VCFG.get("silence_ms", 700)) / 1000

    # -- settings from the hub (versioned) ---------------------------------
    def refresh_prefs(self):
        while True:
            try:
                app = foreground_app()
                self.prefs = self.sp.get("/listening", node_id=self.sp.node_id, app_name=app)
                if self.prefs.get("wake") and self.wake is None:
                    self._load_wake()
            except Exception as e:
                print("[voice] prefs:", e)
            time.sleep(3)

    def _load_wake(self):
        try:
            from openwakeword.model import Model
            self.wake = Model(wakeword_models=[VCFG.get("wake_model", "hey_jarvis")], inference_framework="onnx")
            print("[voice] wake word ready:", VCFG.get("wake_model", "hey_jarvis"))
        except Exception as e:
            self.wake = False
            print("[voice] wake word unavailable (pip install openwakeword):", e)

    # -- push to talk ---------------------------------------------------------
    def start_ptt(self):
        from pynput import keyboard
        want = VCFG.get("ptt_key", "ctrl_r")
        target = getattr(keyboard.Key, want, None) or keyboard.KeyCode.from_char(want)

        def down(k):
            if k == target and not self.ptt_down and self.prefs.get("ptt", True):
                self.ptt_down, self.ptt_buf = True, []
                if self.speaker.speaking:
                    self.speaker.stop()           # barge-in
                print("🎙  listening (release to send)")

        def up(k):
            if k == target and self.ptt_down:
                self.ptt_down = False
                audio = self.np.concatenate(self.ptt_buf) if self.ptt_buf else None
                if audio is not None and len(audio) > RATE * 0.3:
                    threading.Thread(target=self.send, args=(audio, "ptt"), daemon=True).start()

        keyboard.Listener(on_press=down, on_release=up, daemon=True).start()

    # -- audio loop -----------------------------------------------------------
    def run(self):
        np = self.np
        threading.Thread(target=self.refresh_prefs, daemon=True).start()
        self.start_ptt()
        seg, quiet_since, in_speech = [], None, False

        def cb(indata, frames, t, status):
            self.frames.put(indata[:, 0].copy())

        with self.sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=1280, callback=cb):
            print(f"[voice] ready on {self.sp.node_id}. Hold {VCFG.get('ptt_key', 'ctrl_r')} to talk.")
            while True:
                f = self.frames.get()
                if self.ptt_down:
                    self.ptt_buf.append(f); continue
                if self.speaker.speaking:                 # don't transcribe ourselves
                    seg, in_speech = [], False; continue
                p = self.prefs
                if p.get("wake") and self.wake:
                    scores = self.wake.predict((f * 32767).astype(np.int16))
                    if max(scores.values(), default=0) > float(VCFG.get("wake_threshold", 0.5)):
                        self.armed_until = time.time() + 6
                        self.wake.reset()
                        print("👂 yes?")
                        seg, in_speech = [], False
                        continue
                listening = p.get("always") or time.time() < self.armed_until
                if not listening:
                    continue
                loud = float(np.sqrt(np.mean(f ** 2))) > self.thr
                if loud:
                    in_speech, quiet_since = True, None
                if in_speech:
                    seg.append(f)
                    if not loud:
                        quiet_since = quiet_since or time.time()
                        if time.time() - quiet_since > self.silence:
                            audio = np.concatenate(seg)
                            seg, in_speech, quiet_since = [], False, None
                            self.armed_until = 0
                            if len(audio) > RATE * 0.4:
                                via = "always" if p.get("always") else "wake"
                                threading.Thread(target=self.send, args=(audio, via), daemon=True).start()

    def send(self, audio, via: str):
        segs, _ = self.stt.transcribe(audio, language="en", vad_filter=True, beam_size=1)
        text = " ".join(s.text.strip() for s in segs).strip()
        if len(text) < 2:
            return
        print(f"🗣  {text}")
        self.sp.post("/say", {"actor_id": self.human, "text": text, "via": f"voice:{via}",
                              "node_id": self.sp.node_id, "session_id": f"voice-{self.sp.node_id}"})


def foreground_app() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import psutil, win32gui, win32process
        _, pid = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())
        return psutil.Process(pid).name()
    except Exception:
        return None


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", action="store_true", help="type instead of speaking")
    ap.add_argument("--mute", action="store_true", help="print replies instead of speaking them")
    a = ap.parse_args()
    cfg = config()
    sp = Spine()
    human = "human:" + cfg.get("client", {}).get("human_id", "local")
    sp.register_node(["voice.io", "stt.local.en"] if not a.text else ["voice.text"])
    speaker = Speaker(enabled=not a.mute and not a.text)
    session = f"voice-{sp.node_id}"

    def on_event(ev):
        p = ev.get("payload") or {}
        if ev["kind"] == "utterance" and ev["actor"]["kind"] == "agent" and p.get("speak"):
            speaker.say(p.get("text", ""))
        elif ev["kind"] == "interaction" and ev["action"] == "privacy_question":
            speaker.say(p.get("question", "") + " Say private or allow.")

    threading.Thread(target=sp.listen, args=(on_event,), daemon=True).start()

    if a.text:
        time.sleep(1.0)                      # let the reply listener connect first
        print("Type to talk (Ctrl+C to quit).")
        for line in sys.stdin:
            if line.strip():
                sp.post("/say", {"actor_id": human, "text": line.strip(), "via": "text",
                                 "node_id": sp.node_id, "session_id": session})
        time.sleep(2)
        return
    Ears(sp, speaker, human).run()


if __name__ == "__main__":
    main()
