#!/bin/bash
# Start Chrome for the Meeting Notes Agent CDP endpoint
INSTALL_DIR="${INSTALL_DIR:-/opt/meeting-notes-agent}"
PROFILE="${PROFILE_DIR:-$INSTALL_DIR/profiles/meet_bot}"
CDP_PORT="${CDP_PORT:-9333}"
CHROME="${CHROME_BIN:-google-chrome}"

# Kill only our chrome
pkill -9 -f "remote-debugging-port=${CDP_PORT}" 2>/dev/null
sleep 2
rm -f "$PROFILE"/Singleton*

export DISPLAY="${MEET_DISPLAY:-:99}"
export PULSE_SINK="${PULSE_SINK:-meet_capture}"

# === PulseAudio setup ===
pulseaudio --check 2>/dev/null || pulseaudio -D --exit-idle-time=-1 2>/dev/null
sleep 0.5

# Audio output sink (captures Meet audio)
pactl list short sinks | grep -q meet_capture || \
    pactl load-module module-null-sink sink_name=meet_capture sink_properties=device.description=MeetCapture
pactl set-default-sink meet_capture

# Virtual microphone (so Meet sees an input device)
pactl list short sinks | grep -q fake_mic || \
    pactl load-module module-null-sink sink_name=fake_mic sink_properties=device.description=FakeMicrophone
pactl list short sources | grep -q virtual_mic || \
    pactl load-module module-remap-source source_name=virtual_mic master=fake_mic.monitor source_properties=device.description=VirtualMicrophone
pactl set-default-source virtual_mic

echo "PulseAudio: sink=meet_capture, source=virtual_mic"

# Launch Chrome
$CHROME \
    --remote-debugging-port=${CDP_PORT} \
    --remote-allow-origins=* \
    --user-data-dir=${PROFILE} \
    --no-sandbox --disable-gpu --enable-unsafe-swiftshader \
    --disable-breakpad \
    --use-fake-ui-for-media-stream \
    --autoplay-policy=no-user-gesture-required \
    --no-first-run --disable-sync --disable-translate \
    --window-size=1280,720 --lang=en-US \
    about:blank &

# Wait for CDP
for i in $(seq 1 30); do
    sleep 0.5
    if curl -s http://127.0.0.1:${CDP_PORT}/json/version > /dev/null 2>&1; then
        echo "Chrome CDP ready on :${CDP_PORT}"
        exit 0
    fi
done

echo "Chrome failed to start"
exit 1
