# Wrist Agent

Talk to your coding agent (Claude Code, Codex) or let it use your Mac, through the Vexo
band: tap, speak, double-tap, and hear the answer.

## Start (one command)

```bash
./start.sh
```

Or double-click **Start Wrist Agent.command** in Finder. Wrist Agent lives in the **menu
bar** (a coloured dot) with a **floating pill** at the top of the screen:

| Dot / pill colour | Meaning |
|---|---|
| grey | stopped |
| white | ready: tap the band to talk |
| blue | listening |
| amber | working |
| green | speaking the answer |
| red | a problem (the pill says what) |

The dot's menu: Start/Stop, Agent, Band, Band number, Folder, Speak replies, Show floating
pill, Run self-test, Open control panel, Open .env, Quit. The pill lets clicks through,
shows on every Space and is hidden from screenshots, so computer use never sees it.

## From any folder: the `wrist` command

`bin/wrist` is linked into `~/.local/bin`, so in any terminal:

```bash
wrist            # start in the background
wrist here       # make this folder the agent's project folder
wrist status     # running? which band, agent, folder
wrist stop       # quit
wrist panel      # open the browser control panel
wrist log        # follow the log (~/Library/Logs/WristAgent.log)
wrist login on   # start at login (wrist login off to undo)
```

Not linked yet? `ln -sf "$PWD/bin/wrist" ~/.local/bin/wrist` in this folder.

## In the browser control panel (menu: Open control panel)

1. **Connect:** type your band number (from the bag), pick *Pretend band* to start, pick
   the agent and the folder it works in.
2. **Setup checklist:** shows what is ready. **Open .env** creates the key file from
   `.env.example` (`.env` is already in `.gitignore`) and opens it. Or by hand:
   `cp .env.example .env`. Fill in:
   ```
   DEEPGRAM_API_KEY=...      speech to text, needed for a real band
   OPENAI_API_KEY=...        OpenAI voice for the replies (preferred)
   ELEVENLABS_API_KEY=...    or the ElevenLabs voice; with neither, the Mac voice
   ```
   Pick the voice under **Voice** in the Connect card. `OPENAI_TTS_VOICE` (default
   `alloy`) and `OPENAI_TTS_MODEL` (default `gpt-4o-mini-tts`) change the OpenAI voice.
   **Install band libraries** installs `bleak` (Bluetooth) and `pyserial` (USB).
3. **Tests:** **Self-test** runs the whole loop on a pretend band with a fake agent (no
   keys). Then **Test Claude Code**, **Test Deepgram** and **Test voice**.
4. Press **Start**. With the pretend band, type what you'd say. With a real band,
   double-tap it first so it can be found, then:

| On the band | What happens |
|---|---|
| tap | start listening (light solid blue: mic on) |
| tap again (or double-tap) | send what you said to the agent; say nothing to cancel |
| tap while it talks | stop talking, listen again |
| double-tap after a question | "yes" |

Light: dim = ready, yellow = working, green = done, red = problem.

## Computer use

Pick **Computer use: control this Mac** as the agent and say things like *"open Safari
and search for Vexo"*. Each step: screenshot → OpenAI (`gpt-5.5`, `computer` tool) →
click or type → repeat, up to 25 steps.

- **Tap the band to stop it** at once. Moving the mouse into a screen corner also aborts.
- It will not type passwords or card numbers, buy, or send messages: it stops and tells you.
- Your terminal app needs **Screen Recording** and **Accessibility** (System Settings >
  Privacy & Security). Quit the terminal after turning them on, then run `./start.sh`.
- Screenshots of your screen go to OpenAI while it works.
- **Test computer control** checks the permissions and takes one screenshot; it clicks nothing.

## Good to know

- Close the Vexo dashboard tab before you press Start: the band takes one Bluetooth
  connection at a time.
- While the light is solid blue, the mic's sound goes to Deepgram. Tell the people near you.
- The agent can edit files in the chosen folder but cannot run shell commands unless you
  allow them under **Also allow** (for example `Bash(npm test:*)`).
- The panel only answers on 127.0.0.1 and needs a per-run token, so other websites cannot
  start your agent.

## Files

| File | What it is |
|---|---|
| `server.py` | The control panel: settings, checks, tests, starts and stops the agent |
| `ui/index.html` | The panel's page |
| `wrist_agent.py` | The band → Deepgram → Claude Code → voice loop (also runs on its own, see `--help`) |
| `config.json` | Your saved settings (not in git) |
