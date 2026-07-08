#!/bin/bash
# Watchdog for the Meeting Notes Agent Chrome + PulseAudio stack
# Run via cron every minute

INSTALL_DIR="${INSTALL_DIR:-/opt/meeting-notes-agent}"
CDP_PORT="${CDP_PORT:-9333}"
LOG="${LOG_FILE:-$INSTALL_DIR/logs/watchdog.log}"
LOCKFILE="/tmp/meeting-notes-chrome-watchdog.lock"
TDESKTOP_BIN="${TDESKTOP_BIN:-/opt/telegram-desktop/Telegram}"
TDESKTOP_DATA="${TDESKTOP_DATA:-$INSTALL_DIR/tdesktop_data}"
PULSE_SERVER="${PULSE_SERVER:-/run/user/0/pulse/native}"

exec 200>"$LOCKFILE"
flock -n 200 || exit 0

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }

NEED_RESTART=0

# Check PulseAudio
if ! pactl info > /dev/null 2>&1; then
    log "PulseAudio dead, restarting..."
    pulseaudio -D --exit-idle-time=-1 2>/dev/null
    sleep 1
    NEED_RESTART=1
fi

# Check PulseAudio sinks exist
if ! pactl list short sinks 2>/dev/null | grep -q meet_capture; then
    log "meet_capture sink missing, recreating..."
    pactl load-module module-null-sink sink_name=meet_capture sink_properties=device.description=MeetCapture 2>/dev/null
    pactl load-module module-null-sink sink_name=fake_mic sink_properties=device.description=FakeMicrophone 2>/dev/null
    pactl load-module module-remap-source source_name=virtual_mic master=fake_mic.monitor source_properties=device.description=VirtualMicrophone 2>/dev/null
    pactl set-default-sink meet_capture
    pactl set-default-source virtual_mic
    NEED_RESTART=1
fi

# Check Chrome CDP
if ! curl -s --connect-timeout 3 http://127.0.0.1:${CDP_PORT}/json/version > /dev/null 2>&1; then
    log "Chrome CDP dead, restarting..."
    NEED_RESTART=1
fi

if [ "$NEED_RESTART" = "1" ]; then
    bash "$INSTALL_DIR/start_chrome.sh" >> "$LOG" 2>&1
    if curl -s --connect-timeout 5 http://127.0.0.1:${CDP_PORT}/json/version > /dev/null 2>&1; then
        log "Chrome restarted OK"
        systemctl restart meeting-notes-agent
        log "Bot restarted"
    else
        log "Chrome restart FAILED"
    fi
fi

# Check Telegram Desktop
if ! pgrep -f "Telegram.*tdesktop_data" > /dev/null 2>&1; then
    log "Telegram Desktop dead, restarting..."
    DISPLAY="${TDESKTOP_DISPLAY:-:98}" QT_QPA_PLATFORM=xcb PULSE_SINK=meet_capture PULSE_SERVER="$PULSE_SERVER" "$TDESKTOP_BIN" -workdir "$TDESKTOP_DATA" &
    log "Telegram Desktop restarted"
fi
