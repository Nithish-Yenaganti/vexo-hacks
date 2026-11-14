"""AirPods voice chat that controls your Mac.

Talk naturally through your AirPods (or any headset). OpenAI's Realtime model listens,
answers out loud within a second, and you can interrupt it any time. When you ask for
something on the screen ("open ChatGPT and start a new chat"), it hands the task to
computer use (computer.py), which clicks and types while you watch, and it tells you when
it is done. Say "stop" to stop the computer.

    .venv/bin/python wrist-agent/voice_chat.py                 AirPods if connected, else the default mic
    .venv/bin/python wrist-agent/voice_chat.py --device "MacBook"
    .venv/bin/python wrist-agent/voice_chat.py --say-file x.pcm   test with a recording, no mic

Needs OPENAI_API_KEY (environment or .env). Use headphones: with the laptop's speakers the
model hears itself. Your voice goes to OpenAI while this runs.
"""
import argparse
import base64
import json
import queue
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import computer  # noqa: E402
import wrist_agent  # noqa: E402  (secret(), emit(), log(), JSON_EVENTS)
from wrist_agent import emit, log, secret  # noqa: E402

RATE = 24000                    # the Realtime API's PCM: 24 kHz, mono, 16-bit
BLOCK = 480                     # 20 ms
MODEL = "gpt-realtime-2.1"
VOICE = "marin"

INSTRUCTIONS = (
    "You are Wrist Agent, a voice assistant living on the user's Mac. The user talks to you "
    "through AirPods. Speak briefly and naturally, one or two sentences, like a helpful "
    "colleague; never read out code, lists or long text. "
    "For anything that needs the screen (opening apps, clicking, typing, browsing, writing "
    "in an app) call use_computer with a clear, complete task, then say a few words like "
    "'On it'. You will get a system message when the computer task finishes: tell the user "
    "the result in one sentence. While a task runs you can keep talking. If the user says "
    "stop, cancel or wait during a task, call stop_computer. Never ask the computer to "
    "type passwords or card numbers, buy anything, or send messages without the user "
    "clearly asking for that exact message to be sent."
)
TOOLS = [
    {"type": "function", "name": "use_computer",
     "description": "Do a task on the user's Mac by looking at the screen and clicking and typing. "
                    "Runs in the background; you get a system message with the result.",
     "parameters": {"type": "object", "properties": {"task": {"type": "string",
                    "description": "The complete task, in plain words, including app names."}},
                    "required": ["task"]}},
    {"type": "function", "name": "stop_computer", "description": "Stop the computer task that is running now.",
     "parameters": {"type": "object", "properties": {}}},
]


class Player:
    """Plays the model's voice; clear() drops what is left when the user interrupts."""

    def __init__(self):
        self.buf = bytearray()
        self.lock = threading.Lock()

    def add(self, pcm):
        with self.lock:
            self.buf += pcm

    def clear(self):
        with self.lock:
            self.buf.clear()

    def busy(self):
        with self.lock:
            return len(self.buf) > 0

    def callback(self, out, frames, t, status):
        need = len(out)
        with self.lock:
            chunk = bytes(self.buf[:need])
            del self.buf[:need]
        out[:len(chunk)] = chunk
        if len(chunk) < need:
            out[len(chunk):] = b"\x00" * (need - len(chunk))


def pick_device(sd, wanted):
    """(input index, output index, name): a device whose name contains `wanted`, else AirPods, else default."""
    devices = sd.query_devices()
    for name in ([wanted] if wanted else []) + ["AirPods", "Headphones", "Headset"]:
        ins = [i for i, d in enumerate(devices) if name.lower() in d["name"].lower() and d["max_input_channels"] > 0]
        outs = [i for i, d in enumerate(devices) if name.lower() in d["name"].lower() and d["max_output_channels"] > 0]
        if ins and outs:
            return ins[0], outs[0], devices[ins[0]]["name"]
    if wanted:
        raise SystemExit('No audio device with "%s" in its name. Devices: %s' %
                         (wanted, ", ".join(d["name"] for d in devices)))
    i, o = sd.default.device
    return i, o, "%s / %s (no AirPods found: use headphones, or it hears itself)" % (
        devices[i]["name"], devices[o]["name"])


class VoiceChat:
    def __init__(self, ws, model, workdir):
        self.ws = ws
        self.send_lock = threading.Lock()
        self.player = Player()
        self.computer = None
        self.computer_thread = None
        self.workdir = workdir
        self.user_text = ""
        self.speaking = False
        self.user_talking = False
        self.state = None
        self.state_lock = threading.Lock()
        self.muted = False              # muted: no sound from the mic is sent at all
        self.responding = False         # the model is producing a reply right now
        self.want_reply = False         # ask for a reply as soon as that one is done

    def set_state(self, state):
        with self.state_lock:
            if state != self.state:
                self.state = state
                emit("state", state=state)

    def computer_busy(self):
        return bool(self.computer_thread and self.computer_thread.is_alive())

    def send(self, event):
        with self.send_lock:
            self.ws.send(json.dumps(event))

    def configure(self, voice):
        self.send({"type": "session.update", "session": {
            "type": "realtime", "instructions": INSTRUCTIONS + "\nThe user's current project folder is %s." % self.workdir,
            "output_modalities": ["audio"],
            "audio": {
                "input": {"format": {"type": "audio/pcm", "rate": RATE},
                          "transcription": {"model": "gpt-realtime-whisper"},
                          "turn_detection": {"type": "semantic_vad", "interrupt_response": True}},
                "output": {"format": {"type": "audio/pcm", "rate": RATE}, "voice": voice}},
            "tools": TOOLS, "tool_choice": "auto"}})

    def set_muted(self, on):
        self.muted = on
        if on:
            self.user_talking = False
            self.send({"type": "input_audio_buffer.clear"})     # drop anything half-heard
        emit("muted", on=on)
        log("band", "Microphone muted: nothing you say is sent." if on else "Microphone on. Just talk.")

    def reply(self):
        """Ask the model to speak; only one reply at a time, so queue it if one is running."""
        with self.send_lock:
            if self.responding:
                self.want_reply = True
                return
            self.responding = True
            self.ws.send(json.dumps({"type": "response.create"}))

    def mic(self, pcm):
        self.send({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm).decode()})

    # ---- computer tasks -----------------------------------------------------------------
    def start_computer(self, task):
        if self.computer_thread and self.computer_thread.is_alive():
            return "Another computer task is still running. Stop it first or wait."
        self.computer = computer.ComputerAgent(
            secret("OPENAI_API_KEY"), model=secret("OPENAI_COMPUTER_MODEL"), tool=secret("OPENAI_COMPUTER_TOOL"),
            on_step=lambda t: log("act", t),
            context="The user's current project folder is %s (when they say 'my project', they mean this one)."
                    % self.workdir)
        self.set_state("working")
        log("act", "Task: " + task)

        def run():
            try:
                result = self.computer.ask(task)
            except Exception as e:
                result = "The computer task failed: %s" % e
            log("act", "Finished: " + result)
            self.send({"type": "conversation.item.create", "item": {
                "type": "message", "role": "system",
                "content": [{"type": "input_text", "text": "Computer task finished. Result: " + result}]}})
            self.reply()
        self.computer_thread = threading.Thread(target=run, daemon=True)
        self.computer_thread.start()
        return "Started. Tell the user you're on it; you'll get the result in a system message."

    def stop_computer(self):
        if self.computer and self.computer_thread and self.computer_thread.is_alive():
            self.computer.cancel()
            log("band", "stopping the computer task...")
            return "Stopping after the current step."
        return "No computer task is running."

    # ---- events from the model ----------------------------------------------------------
    def handle(self, e):
        kind = e.get("type", "")
        if kind == "input_audio_buffer.speech_started":
            self.player.clear()                          # you talked over it: stop its voice now
            self.user_text = ""
            self.user_talking = True
            if not self.computer_busy():
                self.set_state("listening")
        elif kind == "input_audio_buffer.speech_stopped":
            self.user_talking = False
        elif kind == "conversation.item.input_audio_transcription.delta":
            self.user_text += e.get("delta", "")
            emit("heard", text=self.user_text.strip(), final=False)
        elif kind == "conversation.item.input_audio_transcription.completed":
            text = (e.get("transcript") or self.user_text).strip()
            if text:
                emit("heard", text=text, final=True)
                log("you", text)
        elif kind == "response.output_audio.delta":
            self.player.add(base64.b64decode(e["delta"]))
            self.speaking = True
            if not self.computer_busy():
                self.set_state("speaking")
        elif kind == "response.output_audio_transcript.done":
            if e.get("transcript"):
                log("agent", e["transcript"])
        elif kind == "response.function_call_arguments.done":
            try:
                args = json.loads(e.get("arguments") or "{}")
            except ValueError:
                args = {}
            if e.get("name") == "use_computer":
                out = self.start_computer(args.get("task", ""))
            elif e.get("name") == "stop_computer":
                out = self.stop_computer()
            else:
                out = "Unknown tool."
            self.send({"type": "conversation.item.create", "item": {
                "type": "function_call_output", "call_id": e.get("call_id"), "output": out}})
            self.reply()
        elif kind == "response.created":
            self.responding = True
        elif kind == "response.done":
            self.speaking = False
            with self.send_lock:
                self.responding = False
                queued, self.want_reply = self.want_reply, False
            if queued:
                self.reply()
        elif kind == "error":
            msg = (e.get("error") or {}).get("message", "unknown error")
            if "no active response" not in msg.lower():
                log("agent", "problem: " + msg)

    def idle_watch(self):
        """Back to 'chat' (listening, idle) once its voice has finished playing."""
        while True:
            time.sleep(0.2)
            if self.computer_busy():
                self.set_state("working")
            elif not (self.speaking or self.player.busy() or self.user_talking):
                self.set_state("muted" if self.muted else "chat")


def main():
    p = argparse.ArgumentParser(description="AirPods voice chat that controls your Mac.")
    p.add_argument("--device", default="", help='audio device name to use (default: AirPods if connected)')
    p.add_argument("--model", default="", help="Realtime model (default %s, or OPENAI_REALTIME_MODEL)" % MODEL)
    p.add_argument("--voice", default="", help="voice (default %s, or OPENAI_REALTIME_VOICE)" % VOICE)
    p.add_argument("--workdir", default=str(Path.home()), help="what 'my project' means")
    p.add_argument("--say-file", default="", help="test: send this 24 kHz 16-bit mono PCM file instead of the mic")
    p.add_argument("--seconds", type=float, help="stop after this many seconds")
    p.add_argument("--json-events", action="store_true")
    for ignored in ("--quiet",):                      # accepted so the panel can start it like the band program
        p.add_argument(ignored, action="store_true")
    a, _ = p.parse_known_args()
    wrist_agent.JSON_EVENTS = a.json_events

    key = secret("OPENAI_API_KEY")
    if not key:
        raise SystemExit("Voice chat needs OPENAI_API_KEY in .env.")
    model = a.model or secret("OPENAI_REALTIME_MODEL") or MODEL
    voice = a.voice or secret("OPENAI_REALTIME_VOICE") or VOICE
    import sounddevice as sd
    from websockets.sync.client import connect

    if a.say_file:
        device_label = "test recording " + Path(a.say_file).name
    else:
        dev_in, dev_out, device_label = pick_device(sd, a.device)
    log("setup", "voice chat: %s, voice %s, audio: %s" % (model, voice, device_label))
    print("Note: while this runs, your voice goes to OpenAI, and computer tasks send screenshots too.", flush=True)

    with connect("wss://api.openai.com/v1/realtime?model=" + model,
                 additional_headers={"Authorization": "Bearer " + key},
                 ssl=computer._ssl(), open_timeout=20, max_size=None) as ws:
        chat = VoiceChat(ws, model, a.workdir)
        chat.configure(voice)
        emit("started", band=device_label, sim=False, agent="voice chat", voice=voice)
        chat.set_state("chat")
        log("band", "Listening. Just talk.")
        stop = threading.Event()

        def reader():
            try:
                for raw in ws:
                    chat.handle(json.loads(raw))
            except Exception as e:
                if not stop.is_set():
                    log("agent", "problem: connection closed (%s)" % type(e).__name__)
            stop.set()
        threading.Thread(target=reader, daemon=True).start()
        threading.Thread(target=chat.idle_watch, daemon=True).start()
        def commands():                              # from the menu / panel: /mute, /unmute, /quit
            for line in sys.stdin:
                cmd = line.strip()
                if cmd in ("/quit", "/q"):
                    stop.set()
                elif cmd in ("/mute", "/unmute", "/toggle-mute"):
                    chat.set_muted(cmd == "/mute" or (cmd == "/toggle-mute" and not chat.muted))
        threading.Thread(target=commands, daemon=True).start()

        mic_q = queue.Queue(maxsize=200)
        if a.say_file:
            pcm = Path(a.say_file).read_bytes() + b"\x00" * (RATE * 2 * 2)    # then 2 s of silence
            def play():
                for i in range(0, len(pcm), BLOCK * 2):
                    if not chat.muted:
                        chat.mic(pcm[i:i + BLOCK * 2])
                    time.sleep(BLOCK / RATE)
            threading.Thread(target=play, daemon=True).start()
            out = None
        else:
            def on_mic(data, frames, t, status):
                try:
                    mic_q.put_nowait(bytes(data))
                except queue.Full:
                    pass
            inp = sd.RawInputStream(samplerate=RATE, blocksize=BLOCK, channels=1, dtype="int16",
                                    device=dev_in, callback=on_mic)
            out = sd.RawOutputStream(samplerate=RATE, blocksize=BLOCK, channels=1, dtype="int16",
                                     device=dev_out, callback=chat.player.callback)
            inp.start()
            out.start()
        end = time.time() + a.seconds if a.seconds else None
        try:
            while not stop.is_set() and (end is None or time.time() < end):
                try:
                    pcm = mic_q.get(timeout=0.2)
                except queue.Empty:
                    continue
                if not chat.muted:
                    chat.mic(pcm)
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
            if chat.computer:
                chat.computer.cancel()
            if out is not None:
                inp.stop()
                out.stop()
            emit("stopped")


if __name__ == "__main__":
    main()
