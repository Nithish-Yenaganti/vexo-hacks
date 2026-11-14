# Vexo Band — hackathon notes

Research notes for **VexoHacks** (an AI wearables hackathon by Vexo at Y Combinator, San Francisco), plus our project ideas.

_Researched 2026-11-14. Sources are at the bottom. Anything marked **unconfirmed** needs to be checked with the Vexo team at the event._

---

## 1. The event

- **What:** VexoHacks, a one-day AI wearables hackathon by Vexo, held at Y Combinator in San Francisco.
- **Brief:** "Build new ways for people to interact with AI through **wearables, voice and real-world experiences**, not just another app on a screen."
- **Who:** developers, designers and hardware builders, prototyping AI experiences that fit into everyday life.
- **Hardware:** Vexo bracelets ("and more hardware!") are available to participants who want to build with **Vexo voice technology**.
- **Sponsors:** Google DeepMind, OpenAI, Vexo, ElevenLabs, Minimax, Stripe, Brex, Mastra and others.
- **Prizes:** over $15,000, plus a YC final interview.
- **Not published on the page:** exact date and time, judging criteria, tracks, and what SDK or API participants get.

## 2. The company

- **Vexo**: YC **Fall 2026**, founded 2026, 3 people, San Francisco. Primary YC partner: David Lieb.
- **Tagline:** "An AI bracelet that remembers your day and acts before you ask."
- **Founders:**
  - Haris Malik (CEO): built the OS for Tesla energy products and Optimus, and the humanoid robot at K-Scale Labs (W24).
  - Farqaleet Kiani (CTO): built hardware and firmware for Tesla energy products and Optimus; also worked at AMD, GM, Geotab and Molex.
  - Vikram Narra (CPO): Amazon and Shopify.
- They designed the PCB, enclosure, firmware, app and agents themselves.

## 3. The device: Vexo Band

### What it is
An **always-listening, screenless AI wristband**. It records the conversations you have, turns them into memory, and takes actions in your apps and AI agents. You approve anything sensitive before it happens.

### Specs (from vexoai.com)

| Item | Detail |
|---|---|
| Price | $199 (Graphite, Pearl, Moss; Blush sold out) |
| Ships | January 30, 2027 |
| Module | Anodized aluminum, 49.3 × 26.4 × 10.2 mm, on a nylon strap |
| Durability | IP54 (splash and sweat resistant) |
| Battery | Up to 4 days of 24/7 listening; magnetic charger |
| Input | **Microphone** (always listening while on) and a **physical button** (press to pause or resume listening) |
| Output | **"Quiet haptics"** (a vibration motor) |
| Screen | None |
| Connectivity | **Bluetooth to the phone app**; uses the phone's Wi-Fi or cellular. The phone is required. |
| Warranty | 1-year limited |

### Sensors: what is confirmed and what isn't

| Sensor | Status |
|---|---|
| Microphone | ✅ Confirmed. It is the core of the product. |
| Button | ✅ Confirmed |
| Haptic / vibration motor | ✅ Confirmed ("quiet haptics"). Whether developers can control it is **unconfirmed**. |
| Heart rate / PPG / HRV | ⚠️ **Unconfirmed.** Third-party coverage (Dealroom, RuntimeWire) says "health sensors", but Vexo's own site, YC page and privacy policy don't mention any. |
| IMU (accelerometer / gyroscope) | ❓ Not mentioned anywhere. Most wrist devices have one for wake and taps, but there's no evidence it is exposed. |
| Camera | ❌ None mentioned. The product is voice-only. |
| Location | Comes from the **phone**, with permission, not from the band. |

### How the data flows (from the privacy policy)
1. **Band**: the mic captures audio and streams it over Bluetooth to the paired phone. The band keeps no history; it stores only its own settings.
2. **Phone app**: receives the wearable data and streams the audio to **AssemblyAI** for transcription.
3. **Vexo cloud**: holds the encrypted transcripts, memories, notes and reminders. **No audio is stored.**
4. **Agents and apps**: a memory layer that **Claude, ChatGPT, Codex, Cursor, Muse, Grok** and others can use with permission, plus actions in **2,000+ apps** (Gmail, Google Calendar, Slack, Notion, DoorDash…).

### Voice and privacy features
- "Hey Vexo, forget the past hour" deletes that transcript.
- "Vexo, stop listening", the button, or the app stops capture.
- Approval gating: you choose what runs automatically. Sending messages, changing your calendar and placing orders wait for your OK.

### Developer access
**No public SDK, API or developer docs exist** on vexoai.com or elsewhere that we could find. The event says participants build with **"Vexo voice technology,"** so whatever access we get will most likely be voice, transcripts and memory, and maybe agent hooks (an MCP-style connection to Claude or Codex is likely, given that they advertise Claude, Codex and Cursor). Raw sensor streams are probably not part of it.

### Questions for the Vexo team at the event
1. What do hackers actually get: an SDK, a REST API, an MCP server, webhooks, raw BLE?
2. Can we **trigger custom haptic patterns** (intensity, timing)?
3. Does the band have an **IMU**, and can we stream it (for gestures, taps, wrist orientation)?
4. Does it have **any biosignal sensor** (PPG, heart rate, HRV, skin temperature, EDA)?
5. Can we get transcripts **in real time** (streaming), or only after processing?
6. Can a button press be used as a custom trigger?
7. What is the "more hardware" on offer?

---

## 4. Our ideas

### Idea 1 (original): haptic calm band (parked)
A wearable that senses the stress and anxiety your body produces when you're nervous (from heart rate and HRV), works out your rhythm automatically, and plays calming vibration pulses through the wrist at a matching or slowing frequency to bring you back down. **Why it's parked:** it needs a heart-rate or HRV sensor and fine-grained haptic control, and the Vexo Band publicly offers neither (no confirmed biosensor, and the haptics may not be programmable). We'll revisit it only if the Vexo team confirms both.

> A voice-only fallback version is possible: detect stress from **speech** (pace, pitch, filler words) and run a guided breathing loop using the band's haptics, if we're allowed to trigger them.

### Idea 2 (current): point and command your coding agent
Wear the band, **point at something on your laptop screen** with your finger, and **say what to do** ("fix this", "explain that error", "make this button blue"). Your AI or coding agent then acts on exactly what you pointed at. This fits the brief: voice plus a real-world gesture instead of typing.

**The catch:** the band has **no camera** and **no confirmed IMU stream**, so it can't work out where you're pointing by itself. The way to build it:

| Piece | How |
|---|---|
| **Where you're pointing** | The laptop **webcam** with hand tracking (e.g. MediaPipe Hands) maps your fingertip to screen coordinates. A short calibration helps (point at the 4 corners). |
| **What you're pointing at** | A screenshot around that point, plus the accessibility tree or DOM (or a vision model) to identify the element, file, line or error. |
| **What to do** | **Vexo voice** captures the command. If we can't get a real-time stream, fall back to a laptop mic or ElevenLabs/OpenAI speech-to-text. |
| **Doing it** | Send {command + screenshot crop + element context} to Claude Code, Codex or Cursor (e.g. an MCP tool such as `act_on_pointed_target`). |
| **Feedback** | A band **haptic buzz** when the target locks or the task finishes, if haptics are exposed; otherwise an on-screen highlight or sound. |
| **Optional** | If the band has an IMU, use a wrist flick or tap as the "confirm / execute" trigger instead of a voice word. |

**Demo:** point at a red error in the terminal and say "fix this". The agent patches the code, the band buzzes, and the test passes.

**Open questions:** how much real-time Vexo access we get (this decides whether Vexo is the voice input or only the memory layer), how accurate webcam pointing is at laptop distance, and whether we use the macOS accessibility API or screenshots plus vision.

---

## Sources
- Event page: <https://events.ycombinator.com/vexohacks>
- Vexo on YC: <https://www.ycombinator.com/companies/vexo>
- Vexo website and FAQ: <https://www.vexoai.com/>
- Vexo privacy policy: <https://www.vexoai.com/privacy>
- Third-party coverage (mentions "health sensors", unverified): <https://runtimewire.com/article/vexo-ai-bracelet-conversation-memory>, <https://app.dealroom.co/companies/vexo_2>
