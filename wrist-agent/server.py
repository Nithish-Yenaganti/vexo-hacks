"""Wrist Agent control panel: one command starts everything.

    python3 wrist-agent/server.py

Opens http://127.0.0.1:8765 in your browser. From there you set your band number, pick
the agent and folder, check your keys, run the tests and start or stop the agent.
Only this computer can reach it (127.0.0.1), and every request needs a token that only
the page served here knows, so other websites cannot drive it.
"""
import importlib.util
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
KIT = ROOT / "vexo-open-kit"
AGENT = HERE / "wrist_agent.py"
UI = HERE / "ui" / "index.html"
CONFIG = HERE / "config.json"
TOKEN = secrets.token_urlsafe(24)
PORT = int(os.environ.get("WRIST_AGENT_PORT", "8765"))

os.chdir(ROOT)                                   # .env is read from here
DEFAULTS = {"input": "band", "band": None, "mode": "pretend", "agent": "claude", "workdir": str(ROOT),
            "permission_mode": "acceptEdits", "allowed_tools": "", "voice": True, "voice_engine": "auto"}
VOICES = ("auto", "openai", "elevenlabs", "say")
INPUTS = ("band", "airpods")                     # how you talk to it: the Vexo band, or AirPods
MODES = {"pretend", "pretend-deepgram", "bluetooth", "usb"}   # how the band connects (input "band")
VOICE_CHAT = HERE / "voice_chat.py"


# ---- shared state ----------------------------------------------------------------------

class Hub:
    def __init__(self):
        self.lock = threading.Lock()
        self.events = []
        self.next = 0
        self.proc = None
        self.state = "stopped"
        self.led = None
        self.test_running = None
        self.muted = False

    def add(self, item):
        with self.lock:
            item["i"] = self.next
            item["at"] = time.time()
            self.next += 1
            self.events.append(item)
            del self.events[:-3000]
            if item.get("type") == "state":
                self.state = item["state"]
            if item.get("type") == "muted":
                self.muted = bool(item.get("on"))
            if item.get("type") == "led":
                self.led = item.get("colour")

    def since(self, i):
        with self.lock:
            return [e for e in self.events if e["i"] >= i]


hub = Hub()


def load_config():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG.read_text()))
    except (OSError, ValueError):
        pass
    return migrate(cfg)


def migrate(cfg):
    """Older settings kept AirPods as a band mode; now it is its own input."""
    if cfg.get("mode") == "airpods":
        cfg["input"], cfg["mode"] = "airpods", DEFAULTS["mode"]
    return cfg


def airpods(cfg):
    return cfg.get("input") == "airpods"


def save_config(new):
    cfg = load_config()
    for k in DEFAULTS:
        if k in new:
            cfg[k] = new[k]
    migrate(cfg)
    if cfg["input"] not in INPUTS:
        raise ValueError("Unknown input: pick the Vexo band or AirPods.")
    band = cfg.get("band")
    if band in ("", None):
        cfg["band"] = None
    else:
        band = int(band)
        if not 1 <= band <= 999:
            raise ValueError("Band numbers are 1 to 999.")
        cfg["band"] = band
    if cfg["mode"] not in MODES:
        raise ValueError("Unknown mode.")
    if cfg["agent"] not in ("claude", "codex", "computer", "echo"):
        raise ValueError("Unknown agent.")
    cfg["workdir"] = str(Path(cfg["workdir"]).expanduser())
    cfg["voice"] = bool(cfg["voice"])
    if cfg["voice_engine"] not in VOICES:
        raise ValueError("Unknown voice.")
    CONFIG.write_text(json.dumps(cfg, indent=2))
    return cfg


def key_found(name):
    """True if the key is in the environment or ./.env. The key itself never leaves here."""
    if os.environ.get(name, "").strip():
        return True
    try:
        for line in (ROOT / ".env").read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            k, _, v = line.partition("=")
            if k.strip() == name and v.strip().strip("'\""):
                return True
    except OSError:
        pass
    return False


def env_ignored():
    try:
        return subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT).returncode == 0
    except OSError:
        return False


def computer_checks(cfg):
    need = cfg["agent"] == "computer"
    sys.path.insert(0, str(HERE))
    import computer
    screen, access = computer.permissions()
    return [
        {"id": "pyautogui", "label": "Computer control library (pyautogui)",
         "ok": bool(importlib.util.find_spec("pyautogui")), "optional": not need,
         "hint": "Run ./start.sh again: it installs it."},
        {"id": "screen", "label": "Screen Recording permission", "ok": screen, "optional": not need,
         "hint": "System Settings > Privacy & Security > Screen Recording: turn on Wrist Agent, "
                 "then run: wrist stop && wrist"},
        {"id": "access", "label": "Accessibility permission (click and type)", "ok": access, "optional": not need,
         "hint": "System Settings > Privacy & Security > Accessibility: turn on Wrist Agent, "
                 "then run: wrist stop && wrist"},
    ]


def checks():
    cfg = load_config()
    wd = Path(cfg["workdir"]).expanduser()
    return [
        {"id": "kit", "label": "Vexo kit", "ok": (KIT / "python" / "vexo_open").is_dir(),
         "hint": "Clone it: git clone https://github.com/VexoAI-Org/vexo-open-kit.git"},
        {"id": "band", "label": "Band number set", "ok": bool(cfg["band"]),
         "hint": "Type the number written on your band's bag.", "optional": airpods(cfg)},
        {"id": "bleak", "label": "Bluetooth library (bleak)", "ok": bool(importlib.util.find_spec("bleak")),
         "hint": "Needed for a real band. Press Install band libraries.", "optional": True},
        {"id": "serial", "label": "USB library (pyserial)", "ok": bool(importlib.util.find_spec("serial")),
         "hint": "Only for the USB cable.", "optional": True},
        {"id": "claude", "label": "Claude Code installed", "ok": bool(shutil.which("claude")),
         "hint": "Install Claude Code, or pick another agent.", "optional": cfg["agent"] != "claude"},
        {"id": "codex", "label": "Codex installed", "ok": bool(shutil.which("codex")),
         "hint": "Install the Codex CLI, or pick another agent.", "optional": cfg["agent"] != "codex"},
        *computer_checks(cfg),
        {"id": "workdir", "label": "Agent folder exists", "ok": wd.is_dir(), "hint": "Pick an existing folder."},
        {"id": "env", "label": ".env file", "ok": (ROOT / ".env").is_file(),
         "hint": "Press Create .env, then add your keys in it."},
        {"id": "envignored", "label": ".env kept out of git", "ok": env_ignored(),
         "hint": "Add .env to .gitignore before putting keys in it."},
        {"id": "deepgram", "label": "Deepgram key", "ok": key_found("DEEPGRAM_API_KEY"),
         "hint": "DEEPGRAM_API_KEY in .env. Needed for speech from a real band."},
        {"id": "openai", "label": "OpenAI key (voice, AirPods)", "ok": key_found("OPENAI_API_KEY"),
         "hint": "OPENAI_API_KEY in .env: needed for AirPods voice chat and the OpenAI voice.",
         "optional": cfg["voice_engine"] != "openai" and not airpods(cfg)},
        {"id": "eleven", "label": "ElevenLabs key (voice)", "ok": key_found("ELEVENLABS_API_KEY"),
         "hint": "ELEVENLABS_API_KEY in .env. Optional.", "optional": cfg["voice_engine"] != "elevenlabs"},
    ]


# ---- running the agent -----------------------------------------------------------------

def agent_args(cfg, mode=None, agent=None, quiet=None):
    if mode is None and airpods(cfg):           # live voice chat through AirPods, no band
        return [sys.executable, "-u", str(VOICE_CHAT), "--json-events", "--workdir", cfg["workdir"]]
    mode = mode or cfg["mode"]
    args = [sys.executable, "-u", str(AGENT), str(cfg["band"]), "--json-events",
            "--agent", agent or cfg["agent"], "--workdir", cfg["workdir"],
            "--permission-mode", cfg["permission_mode"]]
    if mode in ("pretend", "pretend-deepgram"):
        args.append("--sim")
    if mode == "pretend-deepgram":
        args.append("--deepgram")
    if mode == "usb":
        args.append("--usb")
    if cfg["allowed_tools"]:
        args += ["--allowed-tools", cfg["allowed_tools"]]
    args += ["--voice", cfg["voice_engine"]]
    if quiet if quiet is not None else not cfg["voice"]:
        args.append("--quiet")
    return args


def spawn(args):
    return subprocess.Popen(args, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)


def read_lines(proc, sink):
    for line in proc.stdout:
        line = line.rstrip("\n")
        if line.startswith("@@"):
            try:
                sink(json.loads(line[2:]))
                continue
            except ValueError:
                pass
        if line.strip():
            sink({"type": "line", "text": line})


def start():
    if hub.proc and hub.proc.poll() is None:
        return "Already running."
    cfg = load_config()
    if not cfg["band"] and not airpods(cfg):
        raise ValueError("Set your band number first, or pick AirPods as the input.")
    if airpods(cfg) and not key_found("OPENAI_API_KEY"):
        raise ValueError("AirPods voice chat needs OPENAI_API_KEY in .env.")
    if not Path(cfg["workdir"]).is_dir():
        raise ValueError("The agent folder does not exist.")
    hub.add({"type": "line", "text": "Starting: AirPods voice chat" if airpods(cfg) else
             "Starting: Vexo band (%s) agent=%s" % (cfg["mode"], cfg["agent"])})
    hub.state = "starting"
    proc = spawn(agent_args(cfg))
    hub.proc = proc

    def pump():
        read_lines(proc, hub.add)
        code = proc.wait()
        hub.add({"type": "line", "text": "Agent program ended (exit %s)." % code})
        hub.muted = False
        hub.add({"type": "state", "state": "stopped"})
    threading.Thread(target=pump, daemon=True).start()
    return "Started."


def stop():
    proc = hub.proc
    if not proc or proc.poll() is not None:
        hub.state = "stopped"
        return "Not running."
    try:
        proc.stdin.write("/quit\n")
        proc.stdin.flush()
    except OSError:
        pass
    try:
        proc.wait(2)
    except subprocess.TimeoutExpired:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return "Stopped."


def set_mute(on=None):
    """Mute or unmute AirPods voice chat. on=None toggles."""
    proc = hub.proc
    if not proc or proc.poll() is not None or not airpods(load_config()):
        raise ValueError("Mute works while AirPods voice chat is running.")
    want = (not hub.muted) if on is None else bool(on)
    proc.stdin.write("/mute\n" if want else "/unmute\n")
    proc.stdin.flush()
    return "Muted." if want else "Unmuted."


def send_input(text):
    proc = hub.proc
    if not proc or proc.poll() is not None:
        raise ValueError("Start the agent first.")
    cfg = load_config()
    if airpods(cfg) or cfg["mode"] not in ("pretend", "pretend-deepgram"):
        raise ValueError("Typing only works with the pretend band. With a real band: tap it.")
    text = " ".join(str(text).split())[:2000]
    if not text:
        raise ValueError("Nothing to send.")
    proc.stdin.write(text + "\n")
    proc.stdin.flush()
    return "Sent."


# ---- tests -----------------------------------------------------------------------------

def report(name, ok, detail):
    hub.add({"type": "test", "name": name, "ok": ok, "detail": detail})


def test_selftest(cfg):
    """The whole loop, end to end: pretend band, echo agent, no keys, no sound."""
    proc = spawn(agent_args(cfg, mode="pretend", agent="echo", quiet=True))
    seen = []
    cond = threading.Condition()

    def sink(e):
        with cond:
            seen.append(e)
            cond.notify_all()
    threading.Thread(target=read_lines, args=(proc, sink), daemon=True).start()

    def wait_for(pred, timeout, start=0):
        end = time.time() + timeout
        with cond:
            while time.time() < end:
                for e in seen[start:]:
                    if pred(e):
                        return e
                cond.wait(0.2)
        return None

    def say(line):
        proc.stdin.write(line + "\n")
        proc.stdin.flush()

    steps = []
    try:
        ok = wait_for(lambda e: e.get("type") == "started", 15)
        steps.append(("pretend band connects", bool(ok)))
        if ok:
            start_at = len(seen)
            say("hello from the self test")
            steps.append(("tap starts listening", bool(wait_for(lambda e: e.get("state") == "listening", 5))))
            steps.append(("double-tap sends to agent", bool(wait_for(lambda e: e.get("state") == "working", 5))))
            reply = wait_for(lambda e: e.get("type") == "log" and e.get("who") == "agent"
                             and "hello from the self test" in e.get("text", ""), 10)
            steps.append(("agent reply comes back", bool(reply)))
            after = seen.index(reply) + 1 if reply else start_at   # the ready that follows the reply
            steps.append(("back to ready", bool(wait_for(lambda e: e.get("state") == "ready", 10, after))))
            say("should I deploy now")
            steps.append(("agent asks a yes/no question", bool(wait_for(
                lambda e: e.get("type") == "question" and e.get("pending"), 10))))
            time.sleep(0.5)
            say("/double")
            steps.append(("double-tap answers yes", bool(wait_for(
                lambda e: e.get("type") == "log" and e.get("who") == "you" and "yes" in e.get("text", ""), 5))))
    finally:
        try:
            say("/quit")
            proc.wait(5)
        except Exception:
            proc.kill()
    passed = all(ok for _, ok in steps) and len(steps) == 7
    report("Self-test", passed, "; ".join(("✓ " if ok else "✗ ") + name for name, ok in steps))


def test_agent(cfg):
    if cfg["agent"] == "codex":
        return test_codex(cfg)
    if not shutil.which("claude"):
        return report("Claude Code", False, "The claude command is not installed.")
    try:
        done = subprocess.run(["claude", "-p", "Reply with exactly the word OK and nothing else.",
                               "--output-format", "json"], cwd=cfg["workdir"],
                              capture_output=True, text=True, timeout=120)
        out = json.loads(done.stdout)
        text = (out.get("result") or "").strip()
        ok = not out.get("is_error") and "OK" in text.upper()
        report("Claude Code", ok, "Replied: %s" % text[:120] if ok else
               "Unexpected answer: %s" % (text or done.stderr)[:200])
    except subprocess.TimeoutExpired:
        report("Claude Code", False, "No answer in 2 minutes. Run `claude` once in a terminal to log in.")
    except ValueError:
        report("Claude Code", False, "Could not read the answer. Run `claude` once in a terminal to log in.")


def test_codex(cfg):
    if not shutil.which("codex"):
        return report("Codex", False, "The codex command is not installed.")
    sys.path.insert(0, str(HERE))
    import wrist_agent
    try:
        text = wrist_agent.CodexAgent(cfg["workdir"], "plan").ask("Reply with exactly the word OK. Do not run commands.")
        ok = "OK" in text.upper()
        report("Codex", ok, ("Replied: " if ok else "Unexpected answer: ") + text[:160])
    except subprocess.TimeoutExpired:
        report("Codex", False, "No answer in 15 minutes.")
    except RuntimeError as e:
        report("Codex", False, str(e)[:240] + " (Run `codex login` in a terminal if it is a login problem.)")


def test_deepgram(cfg):
    if not key_found("DEEPGRAM_API_KEY"):
        return report("Deepgram", False, "No DEEPGRAM_API_KEY in .env yet.")
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "import kit, speech\n"
        "from vexo_open import audio\n"
        "from vexo_open.sync import Band\n"
        "from vexo_open.transports.sim import SimTransport\n"
        "p = audio.ogg_packets(kit.SAMPLE_SPEECH)\n"
        "b = Band.connect(%d, transport=SimTransport(%d, auto_tap=False, audio_packets=p))\n"
        "import os\n"
        "m = None\n"
        "try: m = speech.find_key('DEEPGRAM_MODEL')\n"
        "except Exception: pass\n"
        "print('HEARD:' + speech.listen(b, 6, model=m or 'nova-3'))\n"
        "b.disconnect()\n" % (str(KIT / "examples" / "python"), cfg["band"], cfg["band"]))
    try:
        done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return report("Deepgram", False, "No answer in a minute. Check the internet connection.")
    heard = [l[6:] for l in done.stdout.splitlines() if l.startswith("HEARD:")]
    if heard and heard[0].strip():
        report("Deepgram", True, 'Heard the sample: "%s"' % heard[0].strip()[:140])
    else:
        msg = (done.stdout + done.stderr).strip().splitlines()
        report("Deepgram", False, (msg[-1] if msg else "Nothing heard.")[:240])


def test_voice(cfg):
    sys.path.insert(0, str(HERE))
    import wrist_agent
    v = wrist_agent.Voice(engine=cfg["voice_engine"])
    wrist_agent.JSON_EVENTS = False
    finished = threading.Event()
    v.speak("Wrist agent voice check. You should hear me.", then=finished.set)
    finished.wait(30)
    report("Voice", True, "Played with %s. Did you hear it? (A failed cloud voice falls back to the Mac voice: check the log.)" % v.label)


def install_libs(cfg):
    done = subprocess.run([sys.executable, "-m", "pip", "install", "bleak", "pyserial"],
                          capture_output=True, text=True, timeout=300)
    last = (done.stdout + done.stderr).strip().splitlines()
    report("Install band libraries", done.returncode == 0, (last[-1] if last else "")[:240])


def test_computer(cfg):
    sys.path.insert(0, str(HERE))
    import computer
    screen, access = computer.permissions()
    if not importlib.util.find_spec("pyautogui"):
        return report("Computer control", False, "pyautogui is missing: run ./start.sh again.")
    try:
        import pyautogui
        w, h = pyautogui.size()
        agent = computer.ComputerAgent.__new__(computer.ComputerAgent)
        agent.width, agent.height = w, h
        size = len(agent.screenshot())
    except Exception as e:
        if not screen:
            return report("Computer control", False, "Cannot see the screen: turn on Wrist Agent in System Settings > Privacy & Security > "
                          "Screen Recording (menu: Allow computer control…), then run: wrist stop && wrist")
        return report("Computer control", False, "Screenshot failed: %s" % e)
    problems = [p for p, ok in (("Screen Recording", screen), ("Accessibility", access)) if not ok]
    report("Computer control", not problems,
           "Screen %dx%d, screenshot works (%d kB). " % (w, h, size // 1024) +
           ("Missing permission: %s (see the checklist)." % ", ".join(problems) if problems
            else "Permissions OK. Nothing was clicked."))


TESTS = {"selftest": test_selftest, "computer": test_computer, "agent": test_agent, "deepgram": test_deepgram,
         "voice": test_voice, "install": install_libs}


def run_test(name):
    if hub.test_running:
        raise ValueError("Another test is running: %s." % hub.test_running)
    cfg = load_config()
    if name in ("selftest", "deepgram") and not cfg["band"]:
        raise ValueError("Set your band number first.")
    hub.test_running = name

    def go():
        try:
            TESTS[name](cfg)
        except Exception as e:                     # a test never takes the panel down
            report(name, False, "%s: %s" % (type(e).__name__, e))
        finally:
            hub.test_running = None
    threading.Thread(target=go, daemon=True).start()
    return "Running."


def create_env():
    env = ROOT / ".env"
    if env.exists():
        return "There is a .env already."
    if not env_ignored():
        raise ValueError(".env is not in .gitignore. Add it there first.")
    example = ROOT / ".env.example"
    env.write_text(example.read_text() if example.is_file() else
                   "# Wrist Agent keys. Never commit this file.\nDEEPGRAM_API_KEY=\nELEVENLABS_API_KEY=\n")
    os.chmod(env, 0o600)
    subprocess.run(["open", "-e", str(env)]) if sys.platform == "darwin" else None
    return "Created .env. Add your keys after the = signs and save."


def open_env():
    env = ROOT / ".env"
    if not env.exists():
        return create_env()
    if sys.platform == "darwin":
        subprocess.run(["open", "-e", str(env)])
    return "Opened .env."


# ---- http ------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def allowed_host(self):
        return self.headers.get("Host", "") in ("127.0.0.1:%d" % PORT, "localhost:%d" % PORT)

    def reply(self, code, body, kind="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authed(self):
        if not self.allowed_host() or self.headers.get("X-Token") != TOKEN:
            self.reply(403, {"error": "forbidden"})
            return False
        return True

    def do_GET(self):
        if not self.allowed_host():
            return self.reply(403, {"error": "forbidden"})
        path, _, query = self.path.partition("?")
        if path == "/":
            html = UI.read_text().replace("__TOKEN__", TOKEN)
            return self.reply(200, html.encode(), "text/html; charset=utf-8")
        if not self.authed():
            return
        if path == "/api/status":
            running = bool(hub.proc and hub.proc.poll() is None)
            return self.reply(200, {"config": load_config(), "checks": checks(), "running": running,
                                    "muted": hub.muted and running,
                                    "state": hub.state if running else "stopped", "led": hub.led,
                                    "test_running": hub.test_running})
        if path == "/api/events":
            since = int(dict(p.split("=", 1) for p in query.split("&") if "=" in p).get("since", 0))
            return self.reply(200, {"events": hub.since(since)})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        if not self.authed():
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            path = self.path
            if path == "/api/config":
                result = save_config(body)
            elif path == "/api/start":
                result = start()
            elif path == "/api/stop":
                result = stop()
            elif path == "/api/mute":
                result = set_mute(body.get("on"))
            elif path == "/api/input":
                result = send_input(body.get("text", ""))
            elif path.startswith("/api/test/") and path[10:] in TESTS:
                result = run_test(path[10:])
            elif path == "/api/env":
                result = open_env()
            else:
                return self.reply(404, {"error": "not found"})
            self.reply(200, {"ok": True, "result": result})
        except (ValueError, TypeError) as e:
            self.reply(400, {"ok": False, "error": str(e)})


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = "http://127.0.0.1:%d/" % PORT
    print("Wrist Agent control panel: %s  (Ctrl+C to stop)" % url, flush=True)
    if os.environ.get("WRIST_AGENT_NO_BROWSER") != "1":
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop()
        server.server_close()


if __name__ == "__main__":
    main()
