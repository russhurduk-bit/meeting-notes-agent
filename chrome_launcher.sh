#!/bin/bash
# Chrome launcher for the Meeting Notes Agent
# Keeps Chrome alive with CDP on port 9333

INSTALL_DIR="${INSTALL_DIR:-/opt/meeting-notes-agent}"
PROFILE="${PROFILE_DIR:-$INSTALL_DIR/profiles/meet_bot}"
CDP_PORT="${CDP_PORT:-9333}"
CHROME="${CHROME_BIN:-google-chrome}"

# Clean singletons
rm -f "$PROFILE"/Singleton*

export DISPLAY="${MEET_DISPLAY:-:99}"
export PULSE_SINK="${PULSE_SINK:-meet_capture}"

exec "$CHROME" \
    --remote-debugging-port=$CDP_PORT \
    --remote-allow-origins=* \
    --user-data-dir="$PROFILE" \
    --no-sandbox \
    --no-first-run \
    --no-default-browser-check \
    --disable-gpu \
    --enable-unsafe-swiftshader \
    --use-fake-ui-for-media-stream \
    --use-fake-device-for-media-stream \
    --auto-accept-camera-and-microphone-capture \
    --disable-features=WebRtcHideLocalIpsWithMdns \
    --disable-sync \
    --disable-translate \
    --window-size=1280,720 \
    --lang=en-US \
    about:blank
