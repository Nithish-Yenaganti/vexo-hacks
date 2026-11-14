"""Wrist Agent: talk to your coding agent through the Vexo band.

    tap         start listening (the band's light goes solid blue: the mic is on)
    tap         again (or double-tap): send what you said; say nothing to cancel
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
    OPENAI_API_KEY      optional: OpenAI voice (preferred when set)
    ELEVENLABS_API_KEY  optional: ElevenLabs voice. With neither, macOS `say` is used.
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
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent / "vexo-open-kit"
sys.path.insert(0, str(KIT / "examples" / "python"))     # speech.py, kit.py (kit.py finds the library)

import kit  # noqa: E402
import speech  # noqa: E402
from vexo_open.sync import Band, VexoError  # noqa: E402
from vexo_open.transports.sim import SimTransport  # noqa: E402

# Words Deepgram should expect (it heard "Codex" as "Cortex"). Add your own in .env:
# DEEPGRAM_KEYTERMS=MyApp,My Project
KEYTERMS = ["Codex", "Claude", "Claude Code", "Cursor", "VS Code", "Xcode", "Vexo", "GitHub", "Terminal",
            "Safari", "Chrome", "Slack", "Notion", "Figma", "Finder", "Spotlight", "localhost", "commit",
            "pull request", "npm", "Python"]
# speech.py builds the Deepgram address with urlencode(query); a list must become one
# keyterm=... per word, so let it repeat keys.
speech.urlencode = lambda query: __import__("urllib.parse").parse.urlencode(query, doseq=True)

DOUBLE_TAP_GRACE = 0.4        # seconds to wait after a tap in case it is the start of a double-tap
SETTLE = 1.5                  # after a gesture starts or sends, ignore taps this long: over Bluetooth
                              # with the mic on, the band's tap and double-tap events arrive late and
                              # in pieces, and a leftover tap used to cancel or stop what you just did
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
        done = subprocess.run(cmd, cwd=self.workdir, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=900)
        try:
            out = json.loads(done.stdout)
        except ValueError:
            raise RuntimeError((done.stderr or done.stdout or "no output").strip()[-300:])
        self.session = out.get("session_id") or self.session
        if out.get("is_error"):
            raise RuntimeError(out.get("result") or "the agent reported an error")
        return (out.get("result") or "").strip() or "Done."


class CodexAgent:
    """OpenAI Codex CLI in headless mode (`codex exec`). One session, resumed every turn.
    It may edit files in the working folder (sandbox workspace-write); "plan" = read-only."""

    def __init__(self, workdir, permission_mode, model=None):
        if not shutil.which("codex"):
            raise SystemExit("Codex (the `codex` command) is not installed. Use --agent echo to test without it.")
        self.workdir = workdir
        self.sandbox = "read-only" if permission_mode == "plan" else "workspace-write"
        self.model = model
        self.session = None

    def ask(self, text):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            last = f.name
        try:
            common = ["--skip-git-repo-check", "--json", "-o", last] + (["-m", self.model] if self.model else [])
            if self.session:
                cmd = ["codex", "exec", "resume", *common, "-c", 'sandbox_mode="%s"' % self.sandbox,
                       self.session, text]
            else:
                cmd = ["codex", "exec", *common, "-s", self.sandbox, SPOKEN_STYLE + "\n\nTask: " + text]
            done = subprocess.run(cmd, cwd=self.workdir, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=900)
            problem = None
            for line in done.stdout.splitlines():
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") == "thread.started":
                    self.session = e.get("thread_id") or self.session
                elif e.get("type") in ("turn.failed", "error"):
                    problem = (e.get("error") or {}).get("message") if isinstance(e.get("error"), dict) \
                        else e.get("message") or "the agent reported an error"
            answer = open(last).read().strip()
            if problem and not answer:
                raise RuntimeError(problem)
            if done.returncode != 0 and not answer:
                raise RuntimeError((done.stderr or "codex failed").strip()[-300:])
            return answer or "Done."
        finally:
            os.unlink(last)


class EchoAgent:
    """No real agent: answers at once. For testing the band loop."""

    def ask(self, text):
        time.sleep(1)
        if "?" in text or "should" in text.lower():
            return "I can do that. Shall I go ahead?"
        return "Pretend agent here. You said: %s" % text


# ---- voice: text -> sound --------------------------------------------------------------

class Voice:
    """Speaks in the background so a tap can interrupt it.

    engine: "auto" (OpenAI if OPENAI_API_KEY is set, else ElevenLabs if its key is set,
    else macOS say), or "openai", "elevenlabs", "say". A cloud voice that fails falls
    back to say, so the reply is always heard."""

    ENGINES = ("auto", "openai", "elevenlabs", "say")

    def __init__(self, quiet=False, engine="auto"):
        self.quiet = quiet
        self.keys = {"openai": secret("OPENAI_API_KEY"), "elevenlabs": secret("ELEVENLABS_API_KEY")}
        if engine == "auto":
            engine = next((e for e in ("openai", "elevenlabs") if self.keys[e]), "say")
        elif engine in self.keys and not self.keys[engine]:
            log("voice", "no key for %s, using say" % engine)
            engine = "say"
        self.engine = engine
        self.openai_model = secret("OPENAI_TTS_MODEL") or "gpt-4o-mini-tts"
        self.openai_voice = secret("OPENAI_TTS_VOICE") or "alloy"
        self.eleven_voice = secret("ELEVENLABS_VOICE_ID") or "21m00Tcm4TXvDq3nzCVL"
        self.proc = None
        self.turn = 0                   # each speak() is a new turn; stop() cancels the current one
        self.lock = threading.Lock()

    @property
    def label(self):
        if self.quiet:
            return "off"
        return {"openai": "OpenAI %s (%s)" % (self.openai_model, self.openai_voice),
                "elevenlabs": "ElevenLabs", "say": "macOS say"}[self.engine]

    def speak(self, text, then=None):
        self.stop()
        with self.lock:
            self.turn += 1
            turn = self.turn

        def run():
            try:
                if not self.quiet:
                    self._play(text, turn)
            finally:
                if then:
                    then()
        threading.Thread(target=run, daemon=True).start()

    def _fetch(self, text):
        """The reply as an mp3 file from the cloud voice, or None."""
        if self.engine == "openai":
            req = urllib.request.Request(
                "https://api.openai.com/v1/audio/speech",
                data=json.dumps({"model": self.openai_model, "voice": self.openai_voice, "input": text,
                                 "response_format": "mp3",
                                 "instructions": "Speak like a calm, friendly coding partner. Brief and clear."}).encode(),
                headers={"Authorization": "Bearer " + self.keys["openai"], "Content-Type": "application/json"})
        elif self.engine == "elevenlabs":
            req = urllib.request.Request(
                "https://api.elevenlabs.io/v1/text-to-speech/%s" % self.eleven_voice,
                data=json.dumps({"text": text, "model_id": "eleven_flash_v2_5"}).encode(),
                headers={"xi-api-key": self.keys["elevenlabs"], "Content-Type": "application/json",
                         "Accept": "audio/mpeg"})
        else:
            return None
        try:
            with urllib.request.urlopen(req, timeout=30) as r, \
                    tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(r.read())
            return f.name
        except urllib.error.HTTPError as e:              # status only: never what was sent
            log("voice", "%s answered %s, using say" % (self.engine, e.code))
        except Exception as e:
            log("voice", "%s failed (%s), using say" % (self.engine, type(e).__name__))
        return None

    def _play(self, text, turn):
        audio = self._fetch(text)
        cmd = ["afplay", audio] if audio else (["say", text] if shutil.which("say") else None)
        try:
            with self.lock:
                if cmd is None or turn != self.turn:     # stopped while the sound was being made
                    return
                self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.proc.wait()
        finally:
            if audio:
                try:
                    os.unlink(audio)
                except OSError:
                    pass

    def stop(self):
        with self.lock:
            self.turn += 1
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
        self.quiet_until = 0.0          # taps before this are leftovers of the last gesture
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
            self.finish_listening()            # tap again = send (a double-tap does the same)
        elif self.state == "speaking":
            self.voice.stop()
            self.start_listening()
        elif self.state == "working":
            if hasattr(self.agent, "cancel"):
                self.agent.cancel()
                log("band", "stopping after this step...")
            else:
                log("band", "still working...")

    def on_double_tap(self):
        if self.state == "listening":
            self.finish_listening()
        elif self.state in ("ready", "speaking") and self.question_pending:
            self.voice.stop()
            log("you", "yes (double-tap)")
            self.send("Yes, go ahead.")

    # steps ----------------------------------------------------------------------------
    def finish_listening(self):
        self.quiet_until = time.time() + SETTLE
        text = self.stop_listening()
        log("you", text or "(nothing heard)")
        if text:
            self.send(text)
        else:
            self.say("I didn't catch that.", "ready")

    def start_listening(self):
        self.quiet_until = time.time() + SETTLE
        self.set_state("listening")
        emit("led", colour="#0040ff", name="mic on")
        ears = self.make_ears()
        self.ears = ears

        def heard(text, final):         # live words: everything final so far + the current guess
            done = list(getattr(ears, "finals", []))
            words = " ".join(done if final else done + [text]).strip()
            if words:
                emit("heard", text=words, final=bool(final))
            if final and text:
                log("...", text)
        ears.start(heard)
        self.band.on("audio", self.ears.feed)
        self.band.configure(audio=True)            # solid blue: mic is on
        log("band", "listening. tap (or double-tap) when you are done")

    def stop_listening(self):
        self.band.configure(audio=False)
        self.band.off("audio", self.ears.feed)
        text = self.ears.stop()
        self.ears = None
        return (text or "").strip()

    def send(self, text):
        self.quiet_until = time.time() + SETTLE      # the rest of this gesture must not stop the agent
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
        self.quiet_until = 0.0          # a new tap here is a new gesture
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
            if kind in ("tap", "double-tap") and time.time() < self.quiet_until:
                log("band", "(ignored a %s: part of the last gesture)" % kind)
                self.tap_at = None
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
            time.sleep(DOUBLE_TAP_GRACE + SETTLE + 0.4)  # "speaking" (taps before SETTLE are ignored)
            sim.tap("double-tap")
    events.put(("lost", "you quit"))


def main():
    p = argparse.ArgumentParser(description="Talk to your coding agent through the Vexo band.")
    p.add_argument("number", nargs="?", type=kit.band_number, help="your team's band number, from the bag")
    p.add_argument("--sim", action="store_true", help="pretend band: type what you would say")
    p.add_argument("--usb", action="store_true", help="use the USB cable instead of Bluetooth")
    p.add_argument("--deepgram", action="store_true",
                   help="with --sim: real Deepgram on the kit's sample recording instead of typing")
    p.add_argument("--agent", choices=["claude", "codex", "computer", "echo"], default="claude")
    p.add_argument("--codex-model", default="", help="model for Codex (empty = Codex's default)")
    p.add_argument("--workdir", default=os.getcwd(), help="the folder the coding agent works in")
    p.add_argument("--permission-mode", default="acceptEdits",
                   help="Claude Code permission mode (default acceptEdits: edits yes, shell commands need --allowed-tools)")
    p.add_argument("--allowed-tools", default="", help='passed to Claude Code, e.g. "Bash(npm test:*)"')
    p.add_argument("--quiet", action="store_true", help="print replies, do not speak them")
    p.add_argument("--voice", choices=Voice.ENGINES, default="auto",
                   help="who speaks the replies: auto (OpenAI, else ElevenLabs, else say), openai, elevenlabs, say")
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
        model = secret("DEEPGRAM_MODEL") or "nova-3"
        options = {"model": model}
        if model.startswith(("nova-3", "flux")):       # these models take words to listen for
            options["keyterm"] = KEYTERMS + [t.strip() for t in (secret("DEEPGRAM_KEYTERMS") or "").split(",") if t.strip()]
        make_ears = lambda: speech.create(**options)                             # noqa: E731
        log("setup", "speech: Deepgram %s, listening for %d key words" % (model, len(options.get("keyterm", []))))
        print("Note: while the light is solid blue, the mic's sound goes to Deepgram. Tell people nearby.")

    workdir = str(Path(a.workdir).expanduser().resolve())
    extra = ["--allowedTools", a.allowed_tools] if a.allowed_tools else []
    if a.agent == "echo":
        agent = EchoAgent()
    elif a.agent == "computer":
        import computer
        agent = computer.ComputerAgent(secret("OPENAI_API_KEY"), model=secret("OPENAI_COMPUTER_MODEL"),
                                       tool=secret("OPENAI_COMPUTER_TOOL"), on_step=lambda t: log("act", t),
                                       context="The user's current project folder is %s (when they say 'my "
                                               "project', they mean this one)." % workdir)
        print("Note: computer use sends screenshots of your screen to OpenAI. Tap the band to stop it.", flush=True)
    elif a.agent == "codex":
        agent = CodexAgent(workdir, a.permission_mode, a.codex_model or None)
    else:
        agent = ClaudeCodeAgent(workdir, a.permission_mode, extra)
    voice = Voice(quiet=a.quiet, engine=a.voice)
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
