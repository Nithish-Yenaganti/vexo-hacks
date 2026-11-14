"""Computer use: a spoken request becomes clicks and typing on this Mac.

Loop: screenshot -> OpenAI computer-use model -> one action (click, type, keys, scroll)
-> do it -> new screenshot -> ... until the model answers in words.

Safety:
  - a tap on the band (or Stop in the panel) cancels between any two steps
  - at most MAX_STEPS actions per request
  - when OpenAI flags a step (pending_safety_checks) it stops and says why
  - moving the mouse into a screen corner aborts (pyautogui's fail-safe)
  - the model is told never to type passwords or payment details

macOS asks for two permissions for the app that runs it (Terminal, iTerm, ...):
Screen Recording (to see) and Accessibility (to click and type).
"""
import base64
import ctypes
import json
import os
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

MAX_STEPS = 25
URL = "https://api.openai.com/v1/responses"

INSTRUCTIONS = (
    "You operate this user's Mac for them. Their request was spoken into a wristband and "
    "transcribed, so guess the intent if a word looks wrong. Act directly; do not ask for "
    "confirmation for ordinary steps. Never type passwords, payment card numbers or other "
    "credentials, never buy anything and never send messages or emails: stop and say the "
    "user must do that step. When finished (or stopped), reply in one or two short spoken "
    "sentences, no markdown."
)

KEYS = {"CMD": "command", "COMMAND": "command", "META": "command", "SUPER": "command",
        "CTRL": "ctrl", "CONTROL": "ctrl", "ALT": "option", "OPTION": "option", "SHIFT": "shift",
        "ENTER": "enter", "RETURN": "enter", "ESC": "esc", "ESCAPE": "esc", "SPACE": "space",
        "TAB": "tab", "BACKSPACE": "backspace", "DELETE": "delete", "DEL": "delete",
        "ARROWUP": "up", "ARROWDOWN": "down", "ARROWLEFT": "left", "ARROWRIGHT": "right",
        "UP": "up", "DOWN": "down", "LEFT": "left", "RIGHT": "right",
        "PAGEUP": "pageup", "PAGEDOWN": "pagedown", "HOME": "home", "END": "end"}


class Cancelled(Exception):
    pass


def permissions():
    """(screen_recording, accessibility) for this process, without asking."""
    try:
        cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        ax = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        ax.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(cg.CGPreflightScreenCaptureAccess()), bool(ax.AXIsProcessTrusted())
    except OSError:
        return False, False


def _ssl():
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except ImportError:
        pass
    return ctx


class ComputerAgent:
    def __init__(self, api_key, model=None, tool=None, on_step=None, max_steps=MAX_STEPS):
        if not api_key:
            raise SystemExit("Computer use needs OPENAI_API_KEY in .env.")
        import pyautogui                                   # needs Accessibility permission to act
        self.gui = pyautogui
        pyautogui.FAILSAFE = True                          # mouse into a corner = abort
        pyautogui.PAUSE = 0.15
        self.key = api_key
        self.model = model or "gpt-5.5"
        self.tool = tool or "computer"                      # "computer_use_preview" for the older model
        self.on_step = on_step or (lambda text: None)
        self.max_steps = max_steps
        self.stop_flag = threading.Event()
        self.width, self.height = pyautogui.size()          # screen in points: screenshots are resized to this

    # ---- the outside world ------------------------------------------------------------
    def cancel(self):
        self.stop_flag.set()

    def screenshot(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            subprocess.run(["screencapture", "-x", "-t", "png", path], check=True, timeout=15)
            subprocess.run(["sips", "-z", str(self.height), str(self.width), path],
                           check=True, capture_output=True, timeout=15)
            with open(path, "rb") as f:
                return "data:image/png;base64," + base64.b64encode(f.read()).decode()
        finally:
            os.unlink(path)

    def post(self, body):
        req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                     headers={"Authorization": "Bearer " + self.key,
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=90, context=_ssl()) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:                                            # OpenAI's own message, never our request
                msg = json.loads(e.read()).get("error", {}).get("message", "")
            except Exception:
                msg = ""
            raise RuntimeError("OpenAI answered %s. %s" % (e.code, msg[:200]))

    # ---- one action -------------------------------------------------------------------
    def act(self, a):
        g, kind = self.gui, a.get("type")
        x, y = a.get("x"), a.get("y")
        if kind == "click":
            button = {"wheel": "middle"}.get(a.get("button", "left"), a.get("button", "left"))
            if button in ("back", "forward"):
                g.hotkey("command", "[" if button == "back" else "]")
            else:
                held = [KEYS.get(k.upper(), k.lower()) for k in (a.get("keys") or [])]   # e.g. cmd+click
                for k in held:
                    g.keyDown(k)
                try:
                    g.click(x, y, button=button)
                finally:
                    for k in reversed(held):
                        g.keyUp(k)
            return "click %s,%s" % (x, y)
        if kind == "double_click":
            g.doubleClick(x, y)
            return "double-click %s,%s" % (x, y)
        if kind == "move":
            g.moveTo(x, y)
            return "move %s,%s" % (x, y)
        if kind == "drag":
            path = a.get("path") or []
            if path:
                g.moveTo(path[0]["x"], path[0]["y"])
                for p in path[1:]:
                    g.dragTo(p["x"], p["y"], duration=0.2)
            return "drag"
        if kind == "scroll":
            if x is not None:
                g.moveTo(x, y)
            sy, sx = a.get("scroll_y") or 0, a.get("scroll_x") or 0
            if sy:
                g.scroll(-max(1, round(abs(sy) / 50)) if sy > 0 else max(1, round(abs(sy) / 50)))
            if sx:
                g.hscroll(max(1, round(abs(sx) / 50)) * (1 if sx > 0 else -1))
            return "scroll %s" % ("down" if sy > 0 else "up" if sy < 0 else "sideways")
        if kind == "type":
            text = a.get("text", "")
            g.write(text, interval=0.01)
            return 'type "%s"' % (text[:40] + ("..." if len(text) > 40 else ""))
        if kind == "keypress":
            keys = [KEYS.get(k.upper(), k.lower()) for k in a.get("keys", [])]
            g.hotkey(*keys) if len(keys) > 1 else g.press(keys[0]) if keys else None
            return "keys " + "+".join(keys)
        if kind == "wait":
            time.sleep(1.5)
            return "wait"
        if kind == "screenshot":
            return "look"
        return "unknown action %s (skipped)" % kind

    # ---- the loop ---------------------------------------------------------------------
    def ask(self, text):
        self.stop_flag.clear()
        tool = {"type": "computer"} if self.tool == "computer" else \
            {"type": self.tool, "display_width": self.width, "display_height": self.height, "environment": "mac"}
        body = {"model": self.model, "tools": [tool], "truncation": "auto", "instructions": INSTRUCTIONS,
                "input": [{"role": "user", "content": [
                    {"type": "input_text", "text": text},
                    {"type": "input_image", "image_url": self.screenshot()}]}]}
        for step in range(self.max_steps + 1):
            if self.stop_flag.is_set():
                return "Stopped. I did %d steps." % step
            resp = self.post(body)
            calls = [o for o in resp.get("output", []) if o.get("type") == "computer_call"]
            if not calls:
                words = [c.get("text", "") for o in resp.get("output", []) if o.get("type") == "message"
                         for c in o.get("content", []) if c.get("type") == "output_text"]
                return " ".join(w for w in words if w).strip() or "Done."
            if step == self.max_steps:
                return "I stopped after %d steps so I don't run away with your computer." % self.max_steps
            call = calls[0]
            checks = call.get("pending_safety_checks") or []
            if checks:
                why = "; ".join(c.get("message") or c.get("code", "") for c in checks)
                return "I stopped because OpenAI flagged this step: %s. Please do it yourself." % why[:200]
            if self.stop_flag.is_set():
                return "Stopped. I did %d steps." % step
            for action in call.get("actions") or [call.get("action") or {}]:   # new models send a batch
                if self.stop_flag.is_set():
                    return "Stopped. I did %d steps." % step
                self.on_step(self.act(action))
            time.sleep(0.6)                                     # let the screen settle
            body = {"model": self.model, "tools": [tool], "truncation": "auto",
                    "previous_response_id": resp["id"],
                    "input": [{"type": "computer_call_output", "call_id": call["call_id"],
                               "output": {"type": "computer_screenshot", "image_url": self.screenshot()}}]}
        return "Done."
