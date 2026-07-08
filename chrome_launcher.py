#!/usr/bin/env python3
"""Chrome launcher for the Meeting Notes Agent. Keeps Chrome alive with CDP on port 9333.
Run as: python3 chrome_launcher.py
Chrome stays alive until this script is killed.
"""
import subprocess
import os
import glob
import time
import signal
import sys
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.environ.get("PROFILE_DIR", os.path.join(BASE_DIR, "profiles", "meet_bot"))
CHROME_BIN = os.environ.get("CHROME_BIN", "google-chrome")
CDP_PORT = int(os.environ.get("CDP_PORT", "9333"))
DISPLAY = os.environ.get("MEET_DISPLAY", ":99")

proc = None

def cleanup(signum=None, frame=None):
    global proc
    if proc and proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=5)
    sys.exit(0)

signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)

def launch():
    global proc
    # Clean singletons
    for f in glob.glob(os.path.join(PROFILE, "Singleton*")):
        os.remove(f)

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    env["PULSE_SINK"] = os.environ.get("PULSE_SINK", "meet_capture")

    proc = subprocess.Popen([
        CHROME_BIN,
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-allow-origins=*",
        f"--user-data-dir={PROFILE}",
        "--no-sandbox",
        "--no-first-run",
        "--no-default-browser-check",
        "--use-gl=angle",
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
        "--enable-webgl",
        "--ignore-gpu-blocklist",
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        "--auto-accept-camera-and-microphone-capture",
        "--disable-features=WebRtcHideLocalIpsWithMdns",
        "--disable-sync",
        "--disable-translate",
        "--window-size=1280,720",
        "--lang=en-US",
        "about:blank",
    ], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc

def wait_cdp(timeout=15):
    for i in range(timeout * 2):
        time.sleep(0.5)
        rc = proc.poll()
        if rc is not None:
            stderr = proc.stderr.read().decode()[-500:] if proc.stderr else ""
            print(f"[launcher] Chrome died: exit={rc}, stderr: {stderr}")
            return False
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2)
            return True
        except Exception:
            continue
    return False

if __name__ == "__main__":
    print(f"[launcher] Starting Chrome on CDP port {CDP_PORT}...")
    launch()
    if wait_cdp():
        print(f"[launcher] Chrome ready (pid={proc.pid}, CDP=http://127.0.0.1:{CDP_PORT})")
    else:
        print("[launcher] Chrome failed to start")
        sys.exit(1)

    # Keep alive
    try:
        proc.wait()
    except KeyboardInterrupt:
        cleanup()
