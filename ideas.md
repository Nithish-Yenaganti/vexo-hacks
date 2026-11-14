# VexoHacks: win plan

Goal: **win**, meaning first place, sponsor prizes, and the YC final interview.

---

## 1. How this hackathon is likely judged

- **Vexo is the host.** They want to see their band do something new that they didn't think of: "not just another app on a screen." The band has to be the **main input**, not a gadget we bolt on.
- **YC partners are in the room**, and the prize includes a final interview. The project should look like the **first version of a startup**, not a toy.
- **Sponsor prizes are usually separate.** Each sponsor rewards the project that uses *their* product best. Every sponsor we use should get one clear, visible moment in the demo.
- **A live demo beats slides.** Something real should happen on stage: a real call, a real payment, real code shipped.

**Trap to avoid:** squeezing in all 11 sponsors. Judges can tell when a stack is forced. Pick a main idea that **naturally** needs 6–8 of them, and make each one obviously necessary.

---

## 2. What each sponsor gives us

| Sponsor | What we'd use | Best "moment" |
|---|---|---|
| **Vexo** | Always-on mic, conversation memory, button, quiet haptics, links to Claude/Codex | Wrist as the input; **button press = approve**; haptic buzz = done |
| **Deepgram** | Fast streaming speech-to-text, **diarization (who said what)**, Voice Agent API | Labelling the speakers in a real conversation as it happens |
| **OpenAI** | GPT reasoning, Realtime API, vision, Agents SDK, Codex | Planning, structured extraction, coding |
| **Google DeepMind** | Gemini (multimodal, long context), Gemini Live (streaming camera + audio) | Seeing the screen or the room; reasoning over a whole day of memory |
| **ElevenLabs** | Natural text-to-speech, voice cloning, **conversational agents that make phone calls** | The agent **phones a real business live on stage** |
| **Minimax** | Speech, Hailuo video, music, cheap long-context LLM | Making a recap video or audio of the day |
| **Stripe** | Payment Links, Invoices, Agent Toolkit, Issuing (virtual cards), test mode | Agent **sends an invoice or pays** after a verbal agreement |
| **Brex** | Company cards, spend limits, expenses and receipts API | Agent spends **within a budget**, and the receipt files itself |
| **Mastra** | TypeScript agent framework: workflows, memory, tools, **suspend/resume for human approval** | The backbone: wait for the wrist approval, then carry on |
| **Superserve** | Isolated cloud sandboxes for agents (fast microVMs), MCP server | Agent runs or builds code safely in a sandbox |
| **Marvlabs** | ❓ **Unclear.** Possibly *Marr Labs* (YC, human-like voice agents). **Ask at the event.** | Probably phone or voice agents |

---

## 3. Ideas, ranked

### 🥇 Idea A: "Handshake": say it, shake on it, done
**Pitch:** *You agree on something out loud, and by the time you've shaken hands it's paid, booked and filed.* An agentic wallet on your wrist.

**Flow:**
1. You're talking to someone (a freelancer, a vendor, a friend). Vexo and Deepgram transcribe it and work out **who said what**.
2. A Mastra agent (running on GPT or Gemini) spots a **commitment**: "I'll pay you $300 for the logo by Friday", "let's book dinner for 6 at 7pm", "can you send me the deck?"
3. The band **buzzes**, and your earbuds or phone say (ElevenLabs): *"Invoice Sam $300, due Friday?"*
4. You **press the band's button** to approve. Mastra's suspend/resume waits for that press.
5. The agent acts:
   - **Stripe:** creates and sends a Payment Link or Invoice to the other person.
   - **Brex:** pays with a card that has a **spend limit** ("team dinner budget: $400"), and the receipt and expense memo fill in automatically.
   - **ElevenLabs / Marvlabs voice agent:** **phones the restaurant** live to book the table.
6. Haptic buzz: done. A dashboard shows the paper trail.

**Why it wins:** it's a real-world interaction with no screen, it makes the band the trusted approval device, it covers the money theme of both Stripe and Brex, and the startup story is clear ("Vexo does the next step, and Handshake is the money layer"). The live phone call on stage is a big moment.

**Sponsors:** Vexo, Deepgram, OpenAI or Gemini, Mastra, Stripe, Brex, ElevenLabs, plus Marvlabs if it's voice agents. **7–8 of them, all needed.**

**Risk:** it's close to Vexo's own pitch. We stand apart with **money, trust and spend limits**, which Vexo doesn't have.

---

### 🥈 Idea B: "Point & Ship": point at your screen, say it, and it's built
(This is idea 2 from vexo-band.md, upgraded.)

**Flow:** point your finger at the screen (webcam hand tracking, or Gemini Live watching the camera) and say *"make this a checkout page"* or *"fix this error"*.
- Gemini works out *what* you're pointing at (a screenshot crop plus vision).
- Deepgram or Vexo captures the command, and Mastra routes it.
- Codex or OpenAI writes the code, and **Superserve** runs and tests it in a sandbox.
- *"Add payments here"* makes the agent create a **Stripe** product and Payment Link and add it to the page.
- ElevenLabs reads out the result, and the band buzzes when it's deployed.

**Why it's good:** the developer judges love it, it's visual, and it uses Superserve, Codex, Gemini and Stripe heavily.
**Why it's #2:** it's still "an app on a screen", which the brief warns against, and pointing accuracy is a demo risk.

**Sponsors:** Vexo, Gemini, OpenAI/Codex, Deepgram, Mastra, Superserve, Stripe, ElevenLabs.

---

### 🥉 Idea C: "Steady": a voice-based calm coach (idea 1, reworked)
The band hears **stress in your voice** (speaking fast, pitch rising, lots of filler words) through Deepgram and an LLM. It starts **slow haptic breathing pulses** on your wrist, and if you want, an ElevenLabs calm voice in your earbuds. After a hard conversation, Minimax makes a short "how you did" audio recap.

**Why:** it has heart and is close to your original vision. **Why it's #3:** it uses fewer sponsors, and it needs programmable haptics, which isn't confirmed.

---

### Quick-fire extras (can become features of A)
- **"Who's that?"**: at a networking event, the band whispers the name of the person walking up and what you last discussed (Vexo memory + Gemini).
- **Day reel**: Minimax Hailuo turns your day's conversations into a 30-second recap video. A good closing shot for the demo.
- **Expense-by-voice**: "That lunch was with a client" files a Brex expense with the receipt.

---

## 4. Recommendation

**Build Idea A (Handshake).** Use the **live phone call** and **press-to-pay** as the two big demo moments. If time allows, add "Who's that?" as the opening hook.

Keep Idea B's pointing as a **stretch feature**: "Point at the invoice on screen and say *resend it*."

---

## 5. Architecture (Idea A)

```
Vexo Band (mic, button, haptics)
   │ BLE → phone app → Vexo memory / agent hooks   (fallback: phone/laptop mic)
   ▼
Deepgram streaming STT + diarization  ──►  transcript with speakers
   ▼
Mastra workflow
   ├─ detectCommitment (GPT / Gemini, structured output: {type, amount, who, when})
   ├─ confirm → ElevenLabs TTS prompt + band haptic → SUSPEND until button press
   └─ execute (tools):
        ├─ stripe.createInvoice / paymentLink      (test mode)
        ├─ brex.cardCharge + expense memo           (sandbox, spend limits)
        └─ elevenlabs.outboundCall (book table)     (voice agent + phone number)
   ▼
Dashboard (Next.js): live transcript, pending approvals, receipts trail
```

**Fallbacks (decide during the first hour):**
- If we can't get the Vexo button or haptics in real time → approve with a phone tap and vibrate the phone. Still show the band as the mic.
- If the live call is risky → call a teammate's phone acting as the restaurant.
- If the Brex sandbox is slow → Stripe Issuing virtual card with spending controls.

---

## 6. Timeline for the day

| Time | What |
|---|---|
| **Before the event** | Make accounts and get API keys for every sponsor (Stripe test mode, Brex sandbox, Deepgram, ElevenLabs + phone number, OpenAI, Gemini, Superserve). Read the Mastra quickstart. **Check the rules** on pre-written code. |
| **Hour 0–1** | Ask the Vexo team the 7 questions in vexo-band.md. Lock the scope and the fallbacks. Split roles. |
| **Hour 1–4** | Audio → Deepgram → commitment detection working end to end in the terminal. |
| **Hour 4–6** | Mastra approval loop (suspend/resume) + Stripe invoice + ElevenLabs confirmation voice. |
| **Hour 6–8** | Brex spend + outbound phone call. Dashboard. |
| **Hour 8–9** | **Freeze features.** Rehearse the demo 5+ times. Record a backup video. |
| **Last hour** | Polish the pitch: problem, live demo, why now, what's next. |

**Roles (team of 3–4):** (1) audio + Vexo integration, (2) Mastra agent + tools, (3) Stripe/Brex/voice calls, (4) dashboard + demo + pitch.

---

## 7. Demo script (2 minutes)

1. **Hook (15s):** "Every day you agree to things out loud and then forget to do them. What if shaking hands *was* the paperwork?"
2. **Live (75s):** a teammate plays a freelancer. They agree on $300 for a logo. The band buzzes, an ElevenLabs voice asks, *press*, and a Stripe invoice shows up on the freelancer's phone. Then: "let's celebrate, dinner for 4 at 7." *Press.* The phone call to the restaurant plays on the speakers, and the Brex card is charged within the team budget.
3. **Show the trail (15s):** dashboard with the transcript, approvals and receipts.
4. **Close (15s):** "Vexo remembers. Handshake makes it happen. Next: shared wallets for teams."

---

## 8. Open questions to settle at the event
- What does Vexo give us in real time: audio, transcripts, the button, haptics?
- What is **Marvlabs**, and do they have their own prize?
- Do sponsors have separate prize tracks, and what is each one's criteria?
- Is there a Brex sandbox or API access for hackers?
- How long is the demo, and who are the judges?

---

## Sources
- Superserve: <https://superserve-legacy.vercel.app/blog/introducing-superserve/>, <https://mcpservers.org/servers/superserve-sandbox-mcp-server>
- Marvlabs (unclear): <https://www.arr.club/signal/marv-labs-hit-3-1m-in-contracted-arr-in-32-days>, <https://www.ycombinator.com/launches/Kbe-marr-labs-ai-voice-agents-that-are-indistinguishable-from-humans>
- Vexo and event: see vexo-band.md
