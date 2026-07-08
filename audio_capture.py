"""PulseAudio virtual sink setup and audio recording."""
import subprocess
import os
import signal
import time


class AudioCapture:
    """Captures audio from a PulseAudio virtual sink via ffmpeg."""

    def __init__(self, sink_name: str = "meet_capture"):
        self.sink_name = sink_name
        self.monitor_source = f"{sink_name}.monitor"
        self.process = None
        self.output_path = None

    def setup_sink(self):
        """Create virtual PulseAudio sink if not exists."""
        # Start PulseAudio if not running
        subprocess.run(
            ["pulseaudio", "--check"],
            capture_output=True,
        )
        if subprocess.run(["pulseaudio", "--check"], capture_output=True).returncode != 0:
            subprocess.Popen(
                ["pulseaudio", "--start", "--exit-idle-time=-1"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(1)

        # Check if sink already exists
        result = subprocess.run(
            ["pactl", "list", "short", "sinks"],
            capture_output=True, text=True,
        )
        if self.sink_name in result.stdout:
            subprocess.run(["pactl", "set-default-sink", self.sink_name], check=True)
            print(f"[audio] Sink '{self.sink_name}' already exists (set as default)")
            return

        # Create null sink (virtual audio device)
        subprocess.run([
            "pactl", "load-module", "module-null-sink",
            f"sink_name={self.sink_name}",
            f"sink_properties=device.description=MeetCapture",
        ], check=True)
        # Set as default so browser audio routes here
        subprocess.run(["pactl", "set-default-sink", self.sink_name], check=True)
        print(f"[audio] Created virtual sink '{self.sink_name}' (set as default)")

    def get_sink_id(self) -> str:
        """Get the sink index for setting as default."""
        result = subprocess.run(
            ["pactl", "list", "short", "sinks"],
            capture_output=True, text=True,
        )
        for line in result.stdout.strip().split("\n"):
            if self.sink_name in line:
                return line.split("\t")[0]
        return "0"

    def start_recording(self, output_path: str):
        """Start recording from the virtual sink monitor."""
        self.output_path = output_path
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Record from the monitor source of our virtual sink
        # Volume boost: Meet WebRTC audio is very quiet (~-80dB), amplify 30x
        self.process = subprocess.Popen([
            "ffmpeg", "-y",
            "-f", "pulse",
            "-i", self.monitor_source,
            "-af", "volume=20dB",  # boost quiet WebRTC audio
            "-ac", "1",           # mono
            "-ar", "16000",       # 16kHz for Whisper
            "-acodec", "pcm_s16le",
            output_path,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[audio] Recording started → {output_path}")

    def stop_recording(self) -> str:
        """Stop recording, return path to recorded file."""
        if self.process:
            self.process.send_signal(signal.SIGINT)
            self.process.wait(timeout=10)
            self.process = None
            print(f"[audio] Recording stopped → {self.output_path}")
        return self.output_path

    def cleanup(self):
        """Remove virtual sink."""
        subprocess.run(
            ["pactl", "unload-module", "module-null-sink"],
            capture_output=True,
        )
        print("[audio] Cleaned up virtual sink")
