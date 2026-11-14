"""Wrist Agent as a Mac app: a menu-bar icon and a floating status pill.

    .venv/bin/python wrist-agent/app.py        (./start.sh and `wrist` do this for you)

- Menu-bar dot: its colour is the band's state. Its menu starts and stops the agent and
  picks the agent, band, folder and voice.
- Floating pill at the top of the screen: what is happening right now and the last thing
  said. Clicks go through it, it shows on every Space, and it is hidden from screenshots
  so computer use never sees or clicks it.
- The browser control panel still runs at http://127.0.0.1:8765 ("Open control panel").
"""
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

import objc
from AppKit import (
    NSAlert, NSApp, NSApplication, NSApplicationActivationPolicyAccessory, NSAttributedString,
    NSBackingStoreBuffered, NSColor, NSFont, NSFontAttributeName, NSForegroundColorAttributeName,
    NSLineBreakByTruncatingTail, NSMakeRect, NSMenu, NSMenuItem, NSOffState, NSOnState, NSOpenPanel,
    NSPanel, NSScreen, NSStatusBar, NSStatusWindowLevel, NSTextField, NSVariableStatusItemLength,
    NSVisualEffectView, NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary, NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary, NSWindowSharingNone, NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSObject, NSTimer
from PyObjCTools import AppHelper

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402  (sets the working folder to the project, where .env is)

COLOURS = {  # state -> (r, g, b)
    "stopped": (0.55, 0.55, 0.55), "starting": (0.55, 0.55, 0.55), "ready": (0.92, 0.92, 0.92),
    "listening": (0.20, 0.45, 1.00), "working": (1.00, 0.67, 0.00), "speaking": (0.15, 0.80, 0.35),
    "error": (1.00, 0.25, 0.20),
}
LABELS = {"stopped": "Stopped", "starting": "Connecting to the band…", "ready": "Ready · tap the band to talk",
          "listening": "Listening… tap when you're done", "working": "Working…", "speaking": "Speaking",
          "error": "Problem"}
AGENTS = [("claude", "Claude Code"), ("codex", "OpenAI Codex"), ("computer", "Computer use (this Mac)"),
          ("echo", "Echo (test)")]
MODES = [("pretend", "Pretend band (type in panel)"), ("pretend-deepgram", "Pretend band + Deepgram"),
         ("bluetooth", "Real band · Bluetooth"), ("usb", "Real band · USB cable")]
PILL_W, PILL_H = 520, 62


def colour(state, alpha=1.0):
    r, g, b = COLOURS.get(state, COLOURS["stopped"])
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, alpha)


def label(text, size, bold=False, secondary=False):
    f = NSTextField.labelWithString_(text)
    f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    f.setTextColor_(NSColor.secondaryLabelColor() if secondary else NSColor.labelColor())
    f.setLineBreakMode_(NSLineBreakByTruncatingTail)
    return f


class Controller(NSObject):
    def init(self):
        self = objc.super(Controller, self).init()
        if self is None:
            return None
        self.since = 0
        self.shown_state = None
        self.detail = ""
        self.detail_at = 0.0
        self.error_until = 0.0
        self.pill_on = True
        self.build_status_item()
        self.build_pill()
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.25, self, "tick:", None, True)
        if server.load_config()["agent"] == "computer":   # make macOS list this app and ask, once
            import computer
            if not all(computer.permissions()):
                computer.request_permissions()
        return self

    # ---- menu bar -----------------------------------------------------------------------
    @objc.python_method
    def build_status_item(self):
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self.menu = NSMenu.alloc().init()
        self.menu.setAutoenablesItems_(False)     # we decide what is enabled
        self.menu.setDelegate_(self)
        self.item.setMenu_(self.menu)
        self.paint_dot("stopped")

    @objc.python_method
    def paint_dot(self, state):
        title = NSAttributedString.alloc().initWithString_attributes_(
            "●", {NSForegroundColorAttributeName: colour(state), NSFontAttributeName: NSFont.systemFontOfSize_(15)})
        self.item.button().setAttributedTitle_(title)
        self.item.button().setToolTip_("Wrist Agent: " + LABELS.get(state, state))

    @objc.python_method
    def add(self, menu, title, action=None, obj=None, on=None, enabled=True):
        mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
        if action:
            mi.setTarget_(self)
        if obj is not None:
            mi.setRepresentedObject_(obj)
        if on is not None:
            mi.setState_(NSOnState if on else NSOffState)
        mi.setEnabled_(enabled and action is not None)
        menu.addItem_(mi)
        return mi

    @objc.python_method
    def submenu(self, title):
        parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
        sub = NSMenu.alloc().init()
        sub.setAutoenablesItems_(False)
        parent.setSubmenu_(sub)
        self.menu.addItem_(parent)
        return sub

    def menuNeedsUpdate_(self, menu):           # rebuilt each time it opens, so it is always current
        menu.removeAllItems()
        cfg = server.load_config()
        running = self.running()
        state = server.hub.state if running else "stopped"
        agent = dict(AGENTS).get(cfg["agent"], cfg["agent"])
        band = "band %s" % cfg["band"] if cfg["band"] else "no band number"
        self.add(menu, "%s  ·  %s  ·  %s" % (LABELS.get(state, state).split(" ·")[0], agent, band))
        if self.detail:
            self.add(menu, "“%s”" % self.detail[:70])
        menu.addItem_(NSMenuItem.separatorItem())
        self.add(menu, "Stop" if running else "Start", "toggleRun:")
        menu.addItem_(NSMenuItem.separatorItem())
        sub = self.submenu("Agent")
        for key, name in AGENTS:
            self.add(sub, name, "pickAgent:", key, on=cfg["agent"] == key)
        sub = self.submenu("Band")
        for key, name in MODES:
            self.add(sub, name, "pickMode:", key, on=cfg["mode"] == key)
        self.add(menu, "Band number: %s…" % (cfg["band"] or "not set"), "setBand:")
        self.add(menu, "Folder: %s…" % self.short(cfg["workdir"]), "pickFolder:")
        self.add(menu, "Speak replies", "toggleVoice:", on=cfg["voice"])
        self.add(menu, "Show floating pill", "togglePill:", on=self.pill_on)
        menu.addItem_(NSMenuItem.separatorItem())
        self.add(menu, "Run self-test", "selfTest:", enabled=not server.hub.test_running)
        import computer
        screen, access = computer.permissions()
        if not (screen and access):
            self.add(menu, "Allow computer control…  (needed for Computer use)", "allowComputer:")
        else:
            self.add(menu, "Computer control: allowed ✓")
        self.add(menu, "Open control panel", "openPanel:")
        self.add(menu, "Open .env", "openEnv:")
        menu.addItem_(NSMenuItem.separatorItem())
        self.add(menu, "Quit Wrist Agent", "quit:")
        if running:                              # settings apply on the next Start
            for i in range(menu.numberOfItems()):
                t = menu.itemAtIndex_(i).title()
                if t in ("Agent", "Band") or t.startswith(("Band number", "Folder")):
                    menu.itemAtIndex_(i).setEnabled_(False)

    @staticmethod
    @objc.python_method
    def short(path):
        home = str(Path.home())
        return ("~" + path[len(home):]) if path.startswith(home) else path

    @objc.python_method
    def running(self):
        return bool(server.hub.proc and server.hub.proc.poll() is None)

    @objc.python_method
    def save(self, **changes):
        try:
            server.save_config(changes)
        except ValueError as e:
            self.flash(str(e))

    @objc.python_method
    def flash(self, text):
        self.detail, self.detail_at, self.error_until = text, time.time(), time.time() + 6

    # ---- menu actions -------------------------------------------------------------------
    def toggleRun_(self, sender):
        def go():
            try:
                server.stop() if self.running() else server.start()
            except ValueError as e:
                self.flash(str(e))
        threading.Thread(target=go, daemon=True).start()   # stopping can take a few seconds

    def pickAgent_(self, sender):
        self.save(agent=sender.representedObject())

    def pickMode_(self, sender):
        self.save(mode=sender.representedObject())

    def toggleVoice_(self, sender):
        self.save(voice=not server.load_config()["voice"])

    def togglePill_(self, sender):
        self.pill_on = not self.pill_on

    def setBand_(self, sender):
        NSApp.activateIgnoringOtherApps_(True)
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Band number")
        alert.setInformativeText_("The number written on your band's bag.")
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 120, 24))
        field.setStringValue_(str(server.load_config()["band"] or ""))
        alert.setAccessoryView_(field)
        alert.addButtonWithTitle_("Save")
        alert.addButtonWithTitle_("Cancel")
        alert.window().setInitialFirstResponder_(field)
        if alert.runModal() == 1000:            # first button
            text = field.stringValue().strip()
            if text.isdigit():
                self.save(band=int(text))
            else:
                self.flash("Band numbers are digits only, 1 to 999.")

    def pickFolder_(self, sender):
        NSApp.activateIgnoringOtherApps_(True)
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseDirectories_(True)
        panel.setCanChooseFiles_(False)
        panel.setAllowsMultipleSelection_(False)
        panel.setPrompt_("Use this folder")
        panel.setMessage_("The folder your coding agent works in")
        if panel.runModal() == 1:
            self.save(workdir=panel.URL().path())

    def allowComputer_(self, sender):
        import computer
        screen, access = computer.request_permissions()
        for key, ok in (("screen", screen), ("access", access)):
            if not ok:
                os.system("open '%s'" % computer.SETTINGS[key])
        self.flash("Turn on “Wrist Agent” in Screen Recording and Accessibility, then Quit and start again."
                   if not (screen and access) else "Computer control is allowed.")

    def selfTest_(self, sender):
        try:
            server.run_test("selftest")
            self.flash("Self-test running…")
        except ValueError as e:
            self.flash(str(e))

    def openPanel_(self, sender):
        webbrowser.open("http://127.0.0.1:%d/" % server.PORT)

    def openEnv_(self, sender):
        try:
            self.flash(server.open_env())
        except ValueError as e:
            self.flash(str(e))

    def quit_(self, sender):
        threading.Thread(target=lambda: (server.stop(), AppHelper.callAfter(NSApp.terminate_, None)),
                         daemon=True).start()

    # ---- floating pill ------------------------------------------------------------------
    # Grows with its text: a title (state), the main text (your words live while you talk,
    # then the agent's full answer), and the agent's latest steps while it works.
    @objc.python_method
    def build_pill(self):
        p = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, PILL_W, PILL_H), NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered, False)
        p.setLevel_(NSStatusWindowLevel)
        p.setOpaque_(False)
        p.setBackgroundColor_(NSColor.clearColor())
        p.setHasShadow_(True)
        p.setIgnoresMouseEvents_(True)            # clicks go to the app underneath
        p.setHidesOnDeactivate_(False)
        p.setSharingType_(NSWindowSharingNone)    # not in screenshots: computer use never sees it
        p.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary
                                 | NSWindowCollectionBehaviorFullScreenAuxiliary | NSWindowCollectionBehaviorIgnoresCycle)
        bg = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, PILL_W, PILL_H))
        bg.setMaterial_(13)                       # HUD window
        bg.setBlendingMode_(0)                    # behind window
        bg.setState_(1)                           # always active
        bg.setWantsLayer_(True)
        bg.layer().setCornerRadius_(18)
        bg.layer().setMasksToBounds_(True)
        p.setContentView_(bg)
        self.pill_bg = bg
        self.pill_dot = label("●", 20)
        self.pill_title = label("", 14, bold=True)
        self.pill_text = label("", 14)
        self.pill_steps = label("", 12, secondary=True)
        for v in (self.pill_text, self.pill_steps):
            v.setLineBreakMode_(0)                # wrap by word
            v.setUsesSingleLineMode_(False)
            v.cell().setWraps_(True)
            v.setMaximumNumberOfLines_(0)
        for v in (self.pill_dot, self.pill_title, self.pill_text, self.pill_steps):
            bg.addSubview_(v)
        p.setAlphaValue_(0.0)
        p.orderFrontRegardless()
        self.pill = p
        self.pill_last = None
        self.heard, self.request, self.reply, self.steps = "", "", "", []
        self.changed_at = 0.0

    @objc.python_method
    def layout_pill(self, title, text, steps):
        if (title, text, steps) == self.pill_last:
            return
        self.pill_last = (title, text, steps)
        pad, inner = 18, PILL_W - 62
        self.pill_title.setStringValue_(title)
        self.pill_text.setStringValue_(text)
        self.pill_steps.setStringValue_(steps)
        fit = lambda v: (v.cell().cellSizeForBounds_(NSMakeRect(0, 0, inner, 10000)).height if v.stringValue() else 0)
        h_text, h_steps = min(fit(self.pill_text), 200), min(fit(self.pill_steps), 120)
        height = pad + 20 + (6 + h_text if h_text else 0) + (6 + h_steps if h_steps else 0) + pad
        y = height - pad - 20                      # lay out top to bottom
        self.pill_dot.setFrame_(NSMakeRect(16, y - 3, 26, 26))
        self.pill_title.setFrame_(NSMakeRect(44, y, inner, 20))
        if h_text:
            y -= 6 + h_text
            self.pill_text.setFrame_(NSMakeRect(44, y, inner, h_text))
        if h_steps:
            y -= 6 + h_steps
            self.pill_steps.setFrame_(NSMakeRect(44, y, inner, h_steps))
        self.pill_text.setHidden_(not h_text)
        self.pill_steps.setHidden_(not h_steps)
        vf = NSScreen.mainScreen().visibleFrame()
        self.pill.setFrame_display_(NSMakeRect(vf.origin.x + (vf.size.width - PILL_W) / 2,
                                               vf.origin.y + vf.size.height - height - 10, PILL_W, height), True)
        self.pill_bg.setFrame_(NSMakeRect(0, 0, PILL_W, height))

    def tick_(self, timer):
        for e in server.hub.since(self.since):
            self.since = e["i"] + 1
            kind, who, text = e.get("type"), e.get("who"), e.get("text", "")
            if kind == "state" and e.get("state") == "listening":
                self.heard, self.reply, self.steps = "", "", []
            elif kind == "heard":
                self.heard = text
            elif kind == "log" and who == "you":
                self.request, self.heard, self.steps = text, "", []
            elif kind == "log" and who == "act":
                self.steps = (self.steps + [text])[-4:]
            elif kind == "log" and who == "agent":
                self.reply = text
                if text.startswith("problem:"):
                    self.error_until = time.time() + 8
            elif kind == "test":
                self.flash(("✓ " if e.get("ok") else "✗ ") + e.get("name", "") + ": " + e.get("detail", ""))
                if e.get("ok"):
                    self.error_until = 0
            elif kind == "line" and ("Problem" in text or "Could not" in text):
                self.flash(text)
            else:
                continue
            self.changed_at = time.time()
            if kind == "log" and who in ("you", "agent"):
                self.detail, self.detail_at = ("You: " if who == "you" else "") + text, time.time()
        running = self.running()
        state = server.hub.state if running else "stopped"
        shown = "error" if time.time() < self.error_until else state
        if shown != self.shown_state:
            self.shown_state = shown
            self.paint_dot(shown)
            self.pill_dot.setTextColor_(colour(shown))
        steps = ""
        if state == "listening":
            text = self.heard or "Say what you want…"
        elif state == "working":
            text = "You: " + self.request if self.request else ""
            steps = "\n".join("• " + s for s in self.steps)
        elif self.reply and state in ("speaking", "ready"):
            text = self.reply
        else:
            text = self.detail if time.time() - self.detail_at < 10 else ""
        if shown == "error" and self.detail:
            text = self.detail
        self.layout_pill(LABELS.get(shown, shown), text, steps)
        busy = state in ("starting", "listening", "working", "speaking")
        recent = time.time() - max(self.changed_at, self.detail_at) < 12
        visible = self.pill_on and (busy or recent or shown == "error")
        target = 1.0 if visible else 0.0
        if abs(self.pill.alphaValue() - target) > 0.01:
            self.pill.animator().setAlphaValue_(target)


def main():
    try:
        httpd = server.ThreadingHTTPServer(("127.0.0.1", server.PORT), server.Handler)
    except OSError:
        print("Wrist Agent is already running (port %d is taken). Look for the dot in the menu bar." % server.PORT)
        sys.exit(1)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print("Wrist Agent is in the menu bar. Control panel: http://127.0.0.1:%d/" % server.PORT, flush=True)
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)   # no Dock icon, like other menu-bar apps
    global CONTROLLER
    CONTROLLER = Controller.alloc().init()      # a global keeps it alive
    try:
        AppHelper.runEventLoop(installInterrupt=True)
    finally:
        server.stop()
        httpd.shutdown()


if __name__ == "__main__":
    main()
