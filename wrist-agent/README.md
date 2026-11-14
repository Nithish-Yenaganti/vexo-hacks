# Wrist Agent

Talk to your coding agent (Claude Code) through the Vexo band: tap, speak, double-tap, and
hear the answer.

## Start (one command)

```bash
./start.sh
```

Or double-click **Start Wrist Agent.command** in Finder. Your browser opens the control
panel at http://127.0.0.1:8765. Everything else happens there.

## In the panel

1. **Connect:** type your band number (from the bag), pick *Pretend band* to start, pick
   the agent and the folder it works in.
2. **Setup checklist:** shows what is ready. **Open .env** creates the key file (it is
   already in `.gitignore`) and opens it. Fill in:
   ```
   DEEPGRAM_API_KEY=...      speech to text, needed for a real band
   ELEVENLABS_API_KEY=...    optional, nicer voice (otherwise the Mac voice)
   ```
   **Install band libraries** installs `bleak` (Bluetooth) and `pyserial` (USB).
3. **Tests:** **Self-test** runs the whole loop on a pretend band with a fake agent (no
   keys). Then **Test Claude Code**, **Test Deepgram** and **Test voice**.
4. Press **Start**. With the pretend band, type what you'd say. With a real band,
   double-tap it first so it can be found, then:

| On the band | What happens |
|---|---|
| tap | start listening (light solid blue: mic on) |
| double-tap | send what you said to the agent |
| tap while listening | cancel |
| tap while it talks | stop talking, listen again |
| double-tap after a question | "yes" |

Light: dim = ready, yellow = working, green = done, red = problem.

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
