#!/usr/bin/env python3
"""Meeting Notes Agent — Google Meet recording & structuring agent.

Joins a Google Meet call, captures the audio via a virtual PulseAudio sink,
transcribes it with Groq Whisper, and turns the transcript into structured
meeting notes.

Usage:
    python3 main.py <meet_url> [--language ru]

Example:
    python3 main.py "https://meet.google.com/abc-defg-hij"
"""
import asyncio
import argparse
import os
import sys
from datetime import datetime

from config import RECORDINGS_DIR, PULSE_SINK_NAME
from audio_capture import AudioCapture
from meet_bot import launch_chrome, connect_browser, google_login, join_meeting, wait_for_meeting_end
from transcribe import transcribe_audio, save_transcript
from structurize import structurize_transcript


async def run(meet_url: str, language: str = None):
    meeting_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    audio_path = os.path.join(RECORDINGS_DIR, f"{meeting_id}.wav")

    print(f"=== Meeting Notes Agent ===")
    print(f"Meeting: {meet_url}")
    print(f"Recording: {audio_path}")
    print(f"Meeting ID: {meeting_id}")
    print()

    # 1. Setup audio capture
    audio = AudioCapture(PULSE_SINK_NAME)
    audio.setup_sink()

    # 2. Launch Chrome process
    os.environ["PULSE_SINK"] = PULSE_SINK_NAME
    chrome_proc = launch_chrome()

    # 3. Connect via CDP
    pw, browser = await connect_browser()
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    try:
        # 4. Login to Google
        await google_login(page)

        # 5. Start recording BEFORE joining
        audio.start_recording(audio_path)

        # 6. Join meeting
        await join_meeting(page, meet_url)

        # 7. Wait for meeting to end
        result = await wait_for_meeting_end(page)
        print(f"[main] Meeting ended: {result}")

    except KeyboardInterrupt:
        print("\n[main] Stopped by user (Ctrl+C)")
    except Exception as e:
        print(f"[main] Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 8. Stop recording
        audio.stop_recording()
        try:
            await browser.close()
        except Exception:
            pass
        await pw.stop()
        chrome_proc.terminate()

    # 9. Check if we got audio
    if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 10000:
        print("[main] WARNING: Audio too small, but continuing with transcription attempt")

    if os.path.exists(audio_path):
        file_mb = os.path.getsize(audio_path) / 1024 / 1024
        print(f"\n[main] Recorded {file_mb:.1f} MB of audio")

        # 10. Transcribe
        print("\n[main] Transcribing...")
        transcript = transcribe_audio(audio_path, language=language)
        transcript_path = save_transcript(transcript, meeting_id)
        print(f"[main] Transcript: {len(transcript.get('text', ''))} chars")

        # 11. Structurize
        print("\n[main] Creating notes...")
        date_str = datetime.now().strftime("%d.%m.%Y")
        output_path = structurize_transcript(transcript, meeting_id, date=date_str)

        print(f"\n{'='*50}")
        print(f"DONE!")
        print(f"  Audio:      {audio_path}")
        print(f"  Transcript: {transcript_path}")
        print(f"  Notes:      {output_path}")
        print(f"{'='*50}")
        return output_path
    else:
        print("[main] ERROR: No audio file created")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Meeting Notes Agent: Google Meet recorder & structurizer")
    parser.add_argument("meet_url", help="Google Meet URL (e.g., https://meet.google.com/abc-defg-hij)")
    parser.add_argument("--language", "-l", default=None, help="Audio language hint (e.g., ru, en)")
    args = parser.parse_args()

    os.environ["PULSE_SINK"] = PULSE_SINK_NAME

    asyncio.run(run(args.meet_url, language=args.language))


if __name__ == "__main__":
    main()
