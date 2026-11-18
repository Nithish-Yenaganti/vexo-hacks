# Wrist Agent

**Tap your wrist, say what you want, and your computer does it.**

Built at **VexoHacks**, the AI wearables hackathon by Vexo at Y Combinator.

---

## The story

### It started with a different band

The first idea wasn't about computers at all. It was about nerves: a band that notices when your body tenses up and sends slow, calming pulses through your wrist until you settle again.

Then we got our hands on the **Vexo Band**: a microphone, a button, a motion sensor and quiet haptics, with no screen. It has no heart-rate sensor, so the calm band had to wait. But the band raised a better question:

> *If something is always on your wrist and always listening, why are we still typing to our AI?*

### The keyboard is the bottleneck

Every day we sit in front of Claude Code, Codex and ChatGPT, and every instruction has to go through a keyboard. You stop what you're doing, switch windows, type a paragraph, wait. Meanwhile the most natural interface we have, our voice, does nothing.

Vexo's brief said it plainly: build new ways to interact with AI, *"not just another app on a screen."*

### So we gave the agent a wrist

**Wrist Agent** connects the Vexo Band to the agents already on your laptop:

1. **Tap** the band. Its light turns blue: it's listening.
2. **Say it**: *"Add a dark mode toggle to the settings page."*
3. **Tap again.** Deepgram turns your voice into text, and your coding agent (Claude Code or Codex) gets to work in your project folder.
4. **Hear the answer.** The reply is spoken back with OpenAI or ElevenLabs voices, and the band's light turns green when it's done.
5. If the agent asks *"Should I go ahead?"*, **double-tap** for yes.

Then we went further. Choose **Computer use** and the agent doesn't just write code, it **operates your Mac**. It takes a screenshot, decides, clicks, types and repeats. *"Open Safari and search for Vexo"* happens on screen while you watch. A tap on the band stops it immediately.

### Then we asked: what if you don't have the band?

Not everyone has a Vexo Band. Nearly everyone has **AirPods**.

So we added a second way in. Choose **AirPods** and Wrist Agent becomes a live conversation. OpenAI's Realtime model listens, answers out loud in about a second, and lets you interrupt it like a person. Ask for something on screen and it hands the job to computer use while you keep talking.

**Both are optional.** Pick the one you have:

| Talk through | You need | How it feels |
|---|---|---|
| **Vexo Band** | The band (or the built-in pretend band), a Deepgram key | Tap, speak, tap. Works with Claude Code, Codex or computer use. |
| **AirPods** | Any headphones with a mic, an OpenAI key | Just talk. A live voice chat that can use your Mac. |

Switch any time: menu bar dot → **Input**, or **Talk through** in the control panel.

### Built to be trusted

An agent that can click around your computer needs limits, so we built them in:

- **Stop is always one move away:** tap the band, say "stop", or press Stop. Moving the mouse into a screen corner also aborts.
- **It refuses the risky stuff:** it won't type passwords or card numbers, buy things, or send messages. It stops and tells you instead.
- **At most 25 steps** per request.
- **Mute button:** in AirPods mode, ⌃⌥M (or the floating pill) cuts the mic instantly.
- **Keys stay local:** they live in `.env`, which git ignores. The control panel only answers on `127.0.0.1` and needs a per-run token.

---

## Try it

```bash
git clone https://github.com/Nithish-Yenaganti/vexo-hacks.git
```

```bash
cd vexo-hacks && cp .env.example .env
```

Add your keys to `.env`:

```
DEEPGRAM_API_KEY=     # Vexo Band input: speech to text
OPENAI_API_KEY=       # AirPods input, computer use, and the OpenAI voice
ELEVENLABS_API_KEY=   # optional: ElevenLabs voice
```

Then start it:

```bash
./start.sh
```

The first run downloads the [Vexo Open kit](https://github.com/VexoAI-Org/vexo-open-kit) and the Python libraries. Wrist Agent then appears as a **dot in the menu bar** with a **floating pill** at the top of the screen.

1. Menu → **Input** → **Vexo Band** or **AirPods**.
2. For the band: set your **Band number** (it's on the bag), then pick the **Agent** and the **Folder** it works in.
3. Press **Start**.

No hardware yet? Choose **Band → Pretend band** and **Run self-test**. It runs the whole loop with no keys.

From any terminal, the `wrist` command does the same: `wrist`, `wrist here`, `wrist status`, `wrist stop`. Run `wrist help` for the full list.

| Pill colour | Meaning |
|---|---|
| white | ready |
| blue | listening |
| amber | working |
| green | speaking |
| red | a problem (the pill says what) |

**macOS permissions:** computer use needs **Screen Recording** and **Accessibility**, and AirPods mode needs the **Microphone**. macOS asks once, for the *Wrist Agent* app.

More detail is in [wrist-agent/README.md](wrist-agent/README.md).

---

## How it works

```
            ┌──────────── Vexo Band ─────────────┐     ┌────────── AirPods ──────────┐
            │ tap · voice · double-tap · light   │     │ just talk, interrupt anytime │
            └─────────────────┬──────────────────┘     └──────────────┬───────────────┘
                              │ Bluetooth / USB                       │ mic audio
                     Deepgram (speech → text)              OpenAI Realtime (voice ↔ voice)
                              │                                       │
              ┌───────────────┼────────────────┐                      │
        Claude Code       OpenAI Codex     Computer use  ◄────────────┘
       (edits your project)               (screenshot → click → type, on your Mac)
                              │
              OpenAI / ElevenLabs / macOS voice → spoken reply · band light → green
```

| Part | File |
|---|---|
| Band loop: band → Deepgram → agent → voice | `wrist-agent/wrist_agent.py` |
| AirPods live voice chat | `wrist-agent/voice_chat.py` |
| Computer use (controls the Mac) | `wrist-agent/computer.py` |
| Menu-bar dot and floating pill | `wrist-agent/app.py` |
| Settings, checks, tests and the browser control panel | `wrist-agent/server.py`, `wrist-agent/ui/index.html` |
| One-command start and the `wrist` CLI | `start.sh`, `bin/wrist` |

**Built with:** Vexo Band and the Vexo Open kit, Deepgram, OpenAI (Realtime, computer use, voices, Codex), ElevenLabs, and Claude Code.

---

## What's next

The ideas we didn't have time for are in [ideas.md](ideas.md), and our notes on the hardware are in [vexo-band.md](vexo-band.md):

- **Point and command:** use the band's motion sensor to point at something on screen and say *"fix this."*
- **Handshake:** agree on something out loud, and the band turns it into an invoice or a booking once you approve it with a tap.
- **Calm mode:** the original dream. Spot stress in your voice and movement, and pace your breathing with slow buzzes on your wrist.

*The keyboard had a good run.*
