# Meeting Notes Agent

An autonomous bot that **joins a video call, records it, transcribes it, and turns
the transcript into structured meeting minutes** — delivered as Markdown, `.docx`,
and (optionally) a shared Google Doc.

It supports two kinds of calls:

- **Google Meet** — a headless Chrome instance driven over the Chrome DevTools
  Protocol (CDP) joins the meeting and sits silently as a listener.
- **Telegram group calls** — Telegram Desktop is automated on a virtual display
  to join a `t.me/call/...` conference link.

In both cases the call audio is routed through a **virtual PulseAudio null-sink**
and captured with `ffmpeg`, so no physical audio device is required — everything
runs on a headless server.

---

## Pipeline

```
                    ┌──────────────────────────────┐
   Meet URL  ─────▶ │ Chrome (CDP) joins the Meet   │──┐
   or             │ meet_bot.py / chrome_launcher │  │
   TG call link ─▶ │ Telegram Desktop joins call   │──┤
                    │ tg_call_desktop.py           │  │
                    └──────────────────────────────┘  │
                                                       ▼
                         ┌─────────────────────────────────────┐
                         │ PulseAudio null-sink "meet_capture"  │
                         │  browser/app audio ──▶ .monitor      │
                         │  ffmpeg records ──▶ 16kHz mono WAV    │
                         │  audio_capture.py                    │
                         └─────────────────────────────────────┘
                                                       │
                                                       ▼
                         ┌─────────────────────────────────────┐
                         │ Preprocess: denoise + normalize      │
                         │ Groq Whisper large-v3 (chunked >25MB)│
                         │ transcribe.py                        │
                         └─────────────────────────────────────┘
                                                       │
                                                       ▼
                         ┌─────────────────────────────────────┐
                         │ LLM structuring (Groq Llama 3.3 70B) │
                         │ → meeting minutes in Markdown        │
                         │ structurize.py                       │
                         └─────────────────────────────────────┘
                                                       │
                        ┌──────────────┬───────────────┴───────────┐
                        ▼              ▼                           ▼
                  Markdown (.md)   .docx (doc_export)     Google Doc (gdoc_export)
```

### Stages in detail

1. **Join the call**
   - *Google Meet:* `chrome_launcher.py` / `start_chrome.sh` launch Chrome with
     `--remote-debugging-port`, a persistent profile, and fake media devices.
     `meet_bot.py` connects over CDP with Playwright, logs into Google
     (with optional TOTP 2FA), dismisses dialogs, mutes the mic and clicks
     *Join now / Ask to join*.
   - *Telegram:* `tg_call_desktop.py` opens the `tg://call?slug=...` link in
     Telegram Desktop on a virtual X display, screenshots the window, and finds
     the blue **Join Group Call** button by matching its RGB color, then clicks it
     with `pyautogui`. `tg_call.py` is a legacy Pyrogram + pytgcalls
     alternative that is not part of the supported base install.

2. **Capture audio** — `audio_capture.py` creates a PulseAudio `module-null-sink`,
   sets it as the default output so all call audio flows into it, and records the
   sink's `.monitor` source with `ffmpeg` to a 16 kHz mono WAV (with a volume
   boost, since WebRTC audio is quiet).

3. **Transcribe** — `transcribe.py` first denoises (via `noisereduce`, estimating
   noise from the opening silence) and peak-normalizes the audio, then sends it to
   **Groq Whisper `whisper-large-v3`**. Files larger than 25 MB are split into
   10-minute chunks and transcribed sequentially with timestamp offsets preserved.

4. **Structurize** — `structurize.py` sends the timestamped transcript to a Groq
   LLM (`llama-3.3-70b-versatile`, falling back to Llama 4 Scout on rate limits)
   with a prompt that produces clean meeting minutes: summary, participants,
   key discussions, decisions, an action-item table, an optional budget table,
   open questions and next steps.

5. **Export** — the Markdown is rendered to a formatted `.docx` (`doc_export.py`)
   and optionally to a shareable **Google Doc** via a service account
   (`gdoc_export.py`).

---

## File overview

| File | Role |
|------|------|
| `main.py` | CLI entry point — one-shot: join a Meet URL, record, transcribe, structurize |
| `tg_bot.py` | Telegram bot front-end — send a Meet URL or TG call link, get the notes back as a `.docx` |
| `meet_bot.py` | Google Meet automation over Chrome CDP (login, join, monitor) |
| `chrome_launcher.py` / `chrome_launcher.sh` / `start_chrome.sh` | Launch & keep Chrome alive with CDP + PulseAudio setup |
| `login.py` | One-time interactive Google login via VNC/noVNC to seed the browser profile |
| `audio_capture.py` | PulseAudio null-sink creation + `ffmpeg` recording |
| `transcribe.py` | Denoise/normalize + Groq Whisper transcription (with chunking) |
| `structurize.py` | LLM structuring of the transcript into meeting minutes |
| `doc_export.py` | Markdown → `.docx` export |
| `gdoc_export.py` | Markdown → Google Doc export (service account) |
| `tg_call.py` | Legacy Pyrogram + pytgcalls variant; excluded from the base install because its available native dependencies do not resolve on Python 3.12 |
| `tg_call_desktop.py` | Telegram Desktop GUI automation for joining TG calls |
| `watchdog.sh` | Cron watchdog — restarts PulseAudio / Chrome / Telegram Desktop if they die |
| `chrome-meeting-notes.service` | systemd unit that keeps the Meet Chrome instance running |
| `config.py` | Central config, all secrets from environment variables |

---

## Headless-server setup

The agent is designed to run on a headless Linux VPS. It needs:

### System dependencies

```bash
# Debian/Ubuntu
sudo apt install -y \
    ffmpeg \
    pulseaudio pulseaudio-utils \
    xvfb x11vnc novnc websockify \
    imagemagick \
    google-chrome-stable   # or chromium

# Optional: Telegram Desktop (for TG call support)
# install to /opt/telegram-desktop/Telegram (or set TDESKTOP_BIN)
```

### Virtual displays (Xvfb)

The Meet Chrome runs on one display and the login/Telegram-Desktop instance on
another:

```bash
Xvfb :99 -screen 0 1280x720x24 &   # Meet Chrome  (MEET_DISPLAY)
Xvfb :98 -screen 0 1280x720x24 &   # login / TG   (LOGIN_DISPLAY / TDESKTOP_DISPLAY)
```

### PulseAudio sinks

`start_chrome.sh` (and the watchdog) create the required virtual audio devices:

- `meet_capture` — null-sink that the browser/app plays into and that `ffmpeg`
  records from (via `meet_capture.monitor`).
- `fake_mic` + `virtual_mic` — a null-sink remapped as a source so the call app
  sees a working microphone input.

### Keeping it alive

- **systemd** — install `chrome-meeting-notes.service` to keep the Meet Chrome
  instance (with CDP) running:

  ```bash
  sudo cp chrome-meeting-notes.service /etc/systemd/system/meeting-notes-agent.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now meeting-notes-agent
  ```

- **watchdog** — run `watchdog.sh` from cron every minute to auto-heal PulseAudio,
  Chrome CDP and Telegram Desktop:

  ```cron
  * * * * * INSTALL_DIR=/opt/meeting-notes-agent /opt/meeting-notes-agent/watchdog.sh
  ```

---

## Configuration

All secrets and paths are read from environment variables. Copy
[`.env.example`](.env.example) to `.env` and fill it in. Key variables:

| Variable | Purpose |
|----------|---------|
| `GROQ_API_KEY` | Groq API key (Whisper + Llama) |
| `GOOGLE_EMAIL`, `GOOGLE_PASSWORD`, `GOOGLE_TOTP_SECRET` | Meet bot Google account |
| `BOT_TOKEN` | Telegram bot token (from @BotFather) |
| `TG_API_ID`, `TG_API_HASH` | Telegram API credentials (my.telegram.org) |
| `GOOGLE_SA_KEY` | Path to Google service-account JSON (Google Doc export) |
| `SERVER_IP` | Public IP for the `login.py` VNC instructions |
| `CHROME_BIN` | Path to the Chrome/Chromium binary |
| `INSTALL_DIR` | Base install path (shell scripts + systemd) |

See `.env.example` for the full list and defaults.

---

## Quick start

```bash
# 1. Install
git clone <this-repo> meeting-notes-agent
cd meeting-notes-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# 2. Configure
cp .env.example .env
$EDITOR .env
set -a && source .env && set +a   # export the variables

# 3. One-time Google login (seeds the browser profile via VNC)
python3 login.py
#   → open http://$SERVER_IP:6098/vnc.html, sign in, Ctrl+C to save

# 4a. One-shot CLI run against a Meet link
python3 main.py "https://meet.google.com/abc-defg-hij" --language ru

# 4b. Or run the Telegram bot and just send it links
python3 tg_bot.py
#   → send a https://meet.google.com/... or https://t.me/call/... link
#     the bot joins, records, and replies with a .docx of the minutes
```

Outputs are written to `recordings/` (audio), `transcripts/` (JSON) and
`output/` (`.md` + `.docx`).

---

## Notes

- The structuring prompt and Whisper hint are in Russian by default (the tool was
  built for Russian-language calls) but Whisper is multilingual — pass
  `--language en` or edit the prompts in `structurize.py` / `transcribe.py`.
- The Telegram Desktop join uses **screenshot color matching** to locate the join
  button, which is resilient to UI text/localization changes but depends on the
  button's accent color (`BUTTON_COLOR` in `tg_call_desktop.py`).
- Everything is designed to be **stateless per call** — audio and intermediate
  files can be cleaned up after each run.
