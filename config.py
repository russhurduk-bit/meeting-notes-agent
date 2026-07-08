"""Meeting Notes Agent configuration.

All secrets are read from environment variables (see .env.example).
Paths are derived from this file's location so the project is relocatable.
"""
import os

# Google account for the Meet bot
GOOGLE_EMAIL = os.environ.get("GOOGLE_EMAIL", "")
GOOGLE_PASSWORD = os.environ.get("GOOGLE_PASSWORD", "")
GOOGLE_TOTP_SECRET = os.environ.get("GOOGLE_TOTP_SECRET", "")  # base32 secret, empty if no 2FA

# Groq API (Whisper transcription + LLM structuring)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Paths (relative to this file — keep the project relocatable)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "profiles", "meet_bot")
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
TRANSCRIPTS_DIR = os.path.join(BASE_DIR, "transcripts")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# PulseAudio virtual sink used to capture meeting audio
PULSE_SINK_NAME = os.environ.get("PULSE_SINK_NAME", "meet_capture")

# Bot display name shown in Meet
BOT_NAME = os.environ.get("BOT_NAME", "Meeting Recorder")
