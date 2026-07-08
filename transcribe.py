"""Transcription via Groq Whisper API with audio preprocessing."""
import os
import json
import subprocess
import tempfile
import numpy as np
import soundfile as sf
from groq import Groq
from config import GROQ_API_KEY, TRANSCRIPTS_DIR


def preprocess_audio(audio_path: str) -> str:
    """Preprocess audio: normalize volume + reduce noise. Returns path to cleaned file."""
    import noisereduce as nr

    # Read audio
    data, sr = sf.read(audio_path)

    # Convert to mono if needed
    if len(data.shape) > 1:
        data = data.mean(axis=1)

    # Noise reduction — estimate noise from first 0.5s (usually silence before speech)
    noise_sample = data[:int(sr * 0.5)]
    if len(noise_sample) > 0 and np.abs(noise_sample).max() > 0:
        data = nr.reduce_noise(y=data, sr=sr, y_noise=noise_sample, prop_decrease=0.8)

    # Normalize volume to -3dB peak
    peak = np.abs(data).max()
    if peak > 0:
        target_peak = 10 ** (-3 / 20)  # -3dB
        data = data * (target_peak / peak)

    # Clip to prevent distortion
    data = np.clip(data, -1.0, 1.0)

    # Save to temp file
    clean_path = audio_path.replace(".wav", "_clean.wav")
    sf.write(clean_path, data, sr, subtype="PCM_16")
    print(f"[transcribe] Preprocessed: peak normalized, noise reduced → {clean_path}")
    return clean_path


def transcribe_audio(audio_path: str, language: str = None) -> dict:
    """Transcribe audio file using Groq whisper-large-v3.

    Pipeline: preprocess (normalize + denoise) → Whisper with ru prompt → segments
    """
    client = Groq(api_key=GROQ_API_KEY)

    file_size = os.path.getsize(audio_path)
    print(f"[transcribe] File: {audio_path} ({file_size / 1024 / 1024:.1f} MB)")

    # Preprocess audio
    try:
        clean_path = preprocess_audio(audio_path)
    except Exception as e:
        print(f"[transcribe] Preprocessing failed ({e}), using raw audio")
        clean_path = audio_path

    clean_size = os.path.getsize(clean_path)
    if clean_size > 25 * 1024 * 1024:
        print("[transcribe] File > 25MB, splitting into chunks...")
        return _transcribe_chunked(clean_path, client, language)

    # Default to Russian
    if not language:
        language = "ru"

    with open(clean_path, "rb") as f:
        result = client.audio.transcriptions.create(
            file=(os.path.basename(clean_path), f),
            model="whisper-large-v3",
            response_format="verbose_json",
            temperature=0.0,
            language=language,
            prompt="Деловая встреча. Обсуждение проекта, задач, бюджета, сроков и ответственных.",
        )

    transcript = {
        "text": result.text,
        "segments": [],
        "language": getattr(result, "language", language),
    }

    if hasattr(result, "segments") and result.segments:
        for seg in result.segments:
            transcript["segments"].append({
                "start": seg.start if hasattr(seg, "start") else seg.get("start", 0),
                "end": seg.end if hasattr(seg, "end") else seg.get("end", 0),
                "text": seg.text if hasattr(seg, "text") else seg.get("text", ""),
            })

    # Cleanup preprocessed file
    if clean_path != audio_path:
        try:
            os.remove(clean_path)
        except Exception:
            pass

    return transcript


def _transcribe_chunked(audio_path: str, client: Groq, language: str = None) -> dict:
    """Split large audio into 10-min chunks and transcribe each."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
        capture_output=True, text=True,
    )
    total_duration = float(result.stdout.strip())
    chunk_duration = 600  # 10 minutes

    if not language:
        language = "ru"

    with tempfile.TemporaryDirectory() as tmpdir:
        all_text = []
        all_segments = []
        offset = 0

        while offset < total_duration:
            chunk_path = os.path.join(tmpdir, f"chunk_{offset}.wav")
            subprocess.run([
                "ffmpeg", "-y", "-i", audio_path,
                "-ss", str(offset), "-t", str(chunk_duration),
                "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
                chunk_path,
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            if not os.path.exists(chunk_path) or os.path.getsize(chunk_path) < 1000:
                offset += chunk_duration
                continue

            print(f"[transcribe] Chunk at {offset}s...")
            with open(chunk_path, "rb") as f:
                res = client.audio.transcriptions.create(
                    file=(os.path.basename(chunk_path), f),
                    model="whisper-large-v3",
                    response_format="verbose_json",
                    temperature=0.0,
                    language=language,
                    prompt="Деловая встреча. Обсуждение проекта, задач, бюджета, сроков.",
                )

            all_text.append(res.text)
            if hasattr(res, "segments") and res.segments:
                for seg in res.segments:
                    s = seg if isinstance(seg, dict) else seg.__dict__ if hasattr(seg, "__dict__") else {"start": 0, "end": 0, "text": str(seg)}
                    all_segments.append({
                        "start": s.get("start", 0) + offset,
                        "end": s.get("end", 0) + offset,
                        "text": s.get("text", ""),
                    })

            offset += chunk_duration

    return {
        "text": " ".join(all_text),
        "segments": all_segments,
        "language": language,
    }


def save_transcript(transcript: dict, meeting_id: str) -> str:
    """Save transcript to JSON file."""
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
    path = os.path.join(TRANSCRIPTS_DIR, f"{meeting_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False, indent=2)
    print(f"[transcribe] Saved transcript → {path}")
    return path
