"""Wrist Agent: talk to your coding agent through the Vexo band.

    tap         start listening (the band's light goes solid blue: the mic is on)
    double-tap  stop listening and send what you said to the coding agent
    tap         while listening: cancel, nothing is sent
    tap         while the reply is being spoken: stop talking and listen again
    double-tap  when the agent asked a yes/no question: answer "yes"

Light (when the mic is off): white = ready, yellow = agent working, green = done,
red = problem.

Run it (in the folder that holds vexo-open-kit/):

    python3 wrist-agent/wrist_agent.py NN --sim                 pretend band, type what you "say"
    python3 wrist-agent/wrist_agent.py NN --sim --agent echo    no coding agent either: test the loop
    python3 wrist-agent/wrist_agent.py NN                       real band, Deepgram speech
    python3 wrist-agent/wrist_agent.py NN --workdir ~/code/my-app

NN is your team's band number, written on the band's bag.

Keys (environment variables or a .env file in the folder you start in):
    DEEPGRAM_API_KEY    speech to text (real band, or --sim --deepgram)
    ELEVENLABS_API_KEY  optional: nicer voice. Without it macOS `say` is used.
"""
import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent / "vexo-open-kit"
sys.path.insert(0, str(KIT / "examples" / "python"))     # speech.py, kit.py (kit.py finds the library)

import kit  # noqa: E402
import speech  # noqa: E402
from vexo_open.sync import Band, VexoError  # noqa: E402
from vexo_open.transports.sim import SimTransport  # noqa: E402

DOUBLE_TAP_GRACE = 0.4        # seconds to wait after a tap in case it is the start of a double-tap
COLOURS = {"ready": "#202020", "working": "#ffaa00", "done": "#00ff40", "error": "#ff0000"}

SPOKEN_STYLE = (
    "The user is talking to you through a microphone on a wristband; their words were "
    "transcribed from speech, so expect small transcription mistakes and guess the intent. "
    "Do the task in the working directory. Your FINAL message is read aloud by a speech "
    "engine: keep it to one to three short sentences in plain spoken English, no code, no "
    "markdown, no lists, and no file paths unless essential. If you need a decision from "
    "the user before going further, end your final message with a single yes/no question."
)


JSON_EVENTS = False             # --json-events: machine-readable lines for the control panel


def emit(kind, **data):
    if JSON_EVENTS:
        print("@@" + json.dumps(dict(type=kind, **data)), flush=True)


def log(who, text):
    if JSON_EVENTS:
        emit("log", who=who, text=text)
    else:
        print("%-6s %s" % (who, text), flush=True)


def secret(name):
    """A key from the environment or ./.env, or None. Never printed."""
    try:
        return speech.find_key(name)
    except speech.SpeechError:
        return None


# ---- ears: band audio -> text --------------------------------------------------------

class TypedEars:
    """For the pretend band: the 'speech' is the line typed in the terminal."""

    def __init__(self, inbox):
        self.inbox = inbox

    def start(self, on_text=None):
        return self

    def feed(self, *_):
        pass                                   # the pretend band's audio is silence: ignore it

    def stop(self):
        return self.inbox.pop() if self.inbox else ""


# ---- agents: text -> work -> short spoken summary --------------------------------------

class ClaudeCodeAgent:
    """Claude Code in headless mode. One session, resumed every turn, so it remembers."""

    def __init__(self, workdir, permission_mode, extra):
        if not shutil.which("claude"):
            raise SystemExit("Claude Code (the `claude` command) is not installed. Use --agent echo to test without it.")
        self.workdir, self.permission_mode, self.extra = workdir, permission_mode, extra
        self.session = None

    def ask(self, text):
        cmd = ["claude", "-p", text, "--output-format", "json",
               "--permission-mode", self.permission_mode,
               "--append-system-prompt", SPOKEN_STYLE, *self.extra]
        if self.session:
            cmd += ["--resume", self.session]
        done = subprocess.run(cmd, cwd=self.workdir, capture_output=True, text=True, timeout=900)
        try:
            out = json.loads(done.stdout)
        except ValueError:
            raise RuntimeError((done.stderr or done.stdout or "no output").strip()[-300:])
        self.session = out.get("session_id") or self.session
        if out.get("is_error"):
            raise RuntimeError(out.get("result") or "the agent reported an error")
        return (out.get("result") or "").strip() or "Done."


class EchoAgent:
    """No real agent: answers at once. For testing the band loop."""

    def ask(self, text):
        time.sleep(1)
        if "?" in text or "should" in text.lower():
            return "I can do that. Shall I go ahead?"
        return "Pretend agent here. You said: %s" % text


# ---- voice: text -> sound --------------------------------------------------------------

class Voice:
    """Speaks in the background so a tap can interrupt it."""

    def __init__(self, quiet=False, voice_id="21m00Tcm4TXvDq3nzCVL"):
        self.quiet, self.voice_id = quiet, voice_id
        self.eleven = secret("ELEVENLABS_API_KEY")
        self.proc = None
        self.lock = threading.Lock()

    @property
    def label(self):
        return "off" if self.quiet else ("ElevenLabs" if self.eleven else "macOS say")

    def speak(self, text, then=None):
        self.stop()

        def run():
            try:
                if not self.quiet:
                    self._play(text)
            finally:
                if then:
                    then()
        threading.Thread(target=run, daemon=True).start()

    def _play(self, text):
        cmd = None
        if self.eleven:
            try:
                req = urllib.request.Request(
                    "https://api.elevenlabs.io/v1/text-to-speech/%s" % self.voice_id,
                    data=json.dumps({"text": text, "model_id": "eleven_flash_v2_5"}).encode(),
                    headers={"xi-api-key": self.eleven, "Content-Type": "application/json", "Accept": "audio/mpeg"})
                with urllib.request.urlopen(req, timeout=20) as r, \
                        tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                    f.write(r.read())
                cmd = ["afplay", f.name]
            except Exception as e:                       # fall back to the built-in voice
                log("voice", "ElevenLabs failed (%s), using say" % type(e).__name__)
        if cmd is None:
            if not shutil.which("say"):
                return
            cmd = ["say", text]
        with self.lock:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.proc.wait()

    def stop(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()


# ---- the loop --------------------------------------------------------------------------

class WristAgent:
    def __init__(self, band, agent, voice, make_ears):
        self.band, self.agent, self.voice, self.make_ears = band, agent, voice, make_ears
        self.inbox = queue.Queue()
        self.state = "ready"            # ready, listening, working, speaking
        self.ears = None
        self.question_pending = False
        self.tap_at = None              # a single tap waiting to see if a double-tap follows
        band.on("tap", lambda e: self.inbox.put(("tap", None)))
        band.on("double-tap", lambda e: self.inbox.put(("double-tap", None)))
        band.on("disconnect", lambda e: self.inbox.put(("lost", getattr(e, "reason", ""))))
        band.configure(events=True)

    def set_state(self, state):
        self.state = state
        emit("state", state=state)

    def light(self, name):
        try:
            self.band.set_led(COLOURS[name])
            emit("led", colour=COLOURS[name], name=name)
        except VexoError:
            pass                        # refused while the mic is on: fine

    # gestures -------------------------------------------------------------------------
    def on_tap(self):
        if self.state == "ready":
            self.start_listening()
        elif self.state == "listening":
            self.stop_listening()
            log("band", "cancelled, nothing sent")
            self.set_ready()
        elif self.state == "speaking":
            self.voice.stop()
            self.start_listening()
        elif self.state == "working":
            log("band", "still working...")

    def on_double_tap(self):
        if self.state == "listening":
            text = self.stop_listening()
            log("you", text or "(nothing heard)")
            if text:
                self.send(text)
            else:
                self.say("I didn't catch that.", "ready")
        elif self.state in ("ready", "speaking") and self.question_pending:
            self.voice.stop()
            log("you", "yes (double-tap)")
            self.send("Yes, go ahead.")

    # steps ----------------------------------------------------------------------------
    def start_listening(self):
        self.set_state("listening")
        emit("led", colour="#0040ff", name="mic on")
        self.ears = self.make_ears().start(lambda t, final: final and t and log("...", t))
        self.band.on("audio", self.ears.feed)
        self.band.configure(audio=True)            # solid blue: mic is on
        log("band", "listening. double-tap to send, tap to cancel")

    def stop_listening(self):
        self.band.configure(audio=False)
        self.band.off("audio", self.ears.feed)
        text = self.ears.stop()
        self.ears = None
        return (text or "").strip()

    def send(self, text):
        self.set_state("working")
        self.question_pending = False
        self.light("working")

        def work():
            try:
                self.inbox.put(("reply", self.agent.ask(text)))
            except Exception as e:
                self.inbox.put(("failed", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def say(self, text, colour):
        self.set_state("speaking")
        self.light(colour)
        self.voice.speak(text, then=lambda: self.inbox.put(("spoken", None)))

    def set_ready(self):
        self.set_state("ready")
        self.light("ready")

    # main loop ------------------------------------------------------------------------
    def run(self, seconds=None):
        end = time.time() + seconds if seconds else None
        self.set_ready()
        log("band", "%s ready. tap to talk." % self.band.name)
        while end is None or time.time() < end:
            if self.tap_at and time.time() - self.tap_at > DOUBLE_TAP_GRACE:
                self.tap_at = None
                self.on_tap()
            try:
                kind, data = self.inbox.get(timeout=0.05)
            except queue.Empty:
                continue
            if kind == "tap":
                self.tap_at = time.time()
            elif kind == "double-tap":
                self.tap_at = None             # the tap that began it does not count
                self.on_double_tap()
            elif kind == "reply":
                log("agent", data)
                self.question_pending = data.rstrip().endswith("?")
                emit("question", pending=self.question_pending)
                self.say(data, "done")
            elif kind == "failed":
                log("agent", "problem: " + data)
                self.say("Something went wrong. " + data[:200], "error")
            elif kind == "spoken":
                if self.state == "speaking":
                    self.set_ready()
                    if self.question_pending:
                        log("band", "double-tap for yes, or tap to answer out loud")
            elif kind == "lost":
                log("band", "link lost (%s)" % data)
                return


def type_to_band(band, typed, events):
    """Pretend-band driver: a typed line becomes tap -> words -> double-tap."""
    sim = band.transport
    print("\nPretend band. Type what you would say and press Enter.\n"
          "  /tap and /double send raw gestures, /quit ends.\n", flush=True)
    for line in sys.stdin:
        line = line.strip()
        if line in ("/quit", "/q"):
            break
        if line == "/tap":
            sim.tap("tap")
        elif line in ("/double", "/yes"):
            sim.tap("double-tap")
        elif line:
            typed.append(line)
            sim.tap("tap")
            time.sleep(DOUBLE_TAP_GRACE + 0.6)           # "speaking"
            sim.tap("double-tap")
    events.put(("lost", "you quit"))


def main():
    p = argparse.ArgumentParser(description="Talk to your coding agent through the Vexo band.")
    p.add_argument("number", nargs="?", type=kit.band_number, help="your team's band number, from the bag")
    p.add_argument("--sim", action="store_true", help="pretend band: type what you would say")
    p.add_argument("--usb", action="store_true", help="use the USB cable instead of Bluetooth")
    p.add_argument("--deepgram", action="store_true",
                   help="with --sim: real Deepgram on the kit's sample recording instead of typing")
    p.add_argument("--agent", choices=["claude", "echo"], default="claude")
    p.add_argument("--workdir", default=os.getcwd(), help="the folder the coding agent works in")
    p.add_argument("--permission-mode", default="acceptEdits",
                   help="Claude Code permission mode (default acceptEdits: edits yes, shell commands need --allowed-tools)")
    p.add_argument("--allowed-tools", default="", help='passed to Claude Code, e.g. "Bash(npm test:*)"')
    p.add_argument("--quiet", action="store_true", help="print replies, do not speak them")
    p.add_argument("--seconds", type=float, help="stop after this many seconds")
    p.add_argument("--json-events", action="store_true", help="machine-readable output for the control panel")
    a = p.parse_args()
    global JSON_EVENTS
    JSON_EVENTS = a.json_events
    if a.number is None:
        p.error("add your team's band number (written on the band's bag), also with --sim")

    typed = []
    if a.sim and not a.deepgram:
        band = Band.connect(a.number, transport=SimTransport(a.number, auto_tap=False))
        make_ears = lambda: TypedEars(typed)                                         # noqa: E731
    else:
        if not secret("DEEPGRAM_API_KEY"):
            raise SystemExit("Speech needs DEEPGRAM_API_KEY (environment or .env). "
                             "Without one, try --sim and type instead.")
        if a.sim:
            from vexo_open import audio
            packets = audio.ogg_packets(kit.SAMPLE_SPEECH)
            band = Band.connect(a.number, transport=SimTransport(a.number, auto_tap=False,
                                                                       audio_packets=packets))
        else:
            band = Band.connect(a.number, transport="serial" if a.usb else "ble", auto_reconnect=True)
        make_ears = speech.create
        print("Note: while the light is solid blue, the mic's sound goes to Deepgram. Tell people nearby.")

    workdir = str(Path(a.workdir).expanduser().resolve())
    extra = ["--allowedTools", a.allowed_tools] if a.allowed_tools else []
    agent = EchoAgent() if a.agent == "echo" else ClaudeCodeAgent(workdir, a.permission_mode, extra)
    voice = Voice(quiet=a.quiet)
    log("setup", "agent=%s  workdir=%s  voice=%s" % (a.agent, workdir, voice.label))
    emit("started", band=band.name, sim=a.sim, agent=a.agent, voice=voice.label)

    app = WristAgent(band, agent, voice, make_ears)
    if a.sim:
        threading.Thread(target=type_to_band, args=(band, typed, app.inbox), daemon=True).start()
    try:
        app.run(a.seconds)
    except KeyboardInterrupt:
        pass
    finally:
        voice.stop()
        band.disconnect()
        emit("stopped")


if __name__ == "__main__":
    main()
