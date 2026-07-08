#!/usr/bin/env python3
"""One-time Google login via VNC.

1. Launches Chrome on display :98 with VNC access
2. Opens accounts.google.com
3. You login manually through VNC (noVNC at http://<server>:6098 or VNC :5998)
4. Cookies saved to profile — no need to login again

Usage:
    python3 login.py
"""
import subprocess
import os
import glob
import time
import signal
import sys
import urllib.request

from config import GOOGLE_EMAIL

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.environ.get("PROFILE_DIR", os.path.join(BASE_DIR, "profiles", "meet_bot"))
CHROME_BIN = os.environ.get("CHROME_BIN", "google-chrome")
CDP_PORT = int(os.environ.get("LOGIN_CDP_PORT", "9334"))  # different port from main bot
DISPLAY = os.environ.get("LOGIN_DISPLAY", ":98")  # Xvfb :98 already running
VNC_PORT = int(os.environ.get("VNC_PORT", "5998"))
NOVNC_PORT = int(os.environ.get("NOVNC_PORT", "6098"))

proc = None

def cleanup(signum=None, frame=None):
    if proc and proc.poll() is None:
        proc.terminate()
    sys.exit(0)

signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)

def main():
    global proc

    # Clean singletons
    for f in glob.glob(os.path.join(PROFILE, "Singleton*")):
        os.remove(f)
    os.makedirs(PROFILE, exist_ok=True)

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    # Ensure x11vnc is running on the login display
    vnc_check = subprocess.run(["pgrep", "-f", f"x11vnc.*{VNC_PORT}"], capture_output=True)
    if vnc_check.returncode != 0:
        subprocess.Popen([
            "x11vnc", "-display", DISPLAY, "-rfbport", str(VNC_PORT),
            "-nopw", "-forever", "-shared", "-bg",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        print(f"[login] x11vnc started on port {VNC_PORT}")

    # Ensure noVNC/websockify
    novnc_check = subprocess.run(["pgrep", "-f", f"websockify.*{NOVNC_PORT}"], capture_output=True)
    if novnc_check.returncode != 0:
        subprocess.Popen([
            "websockify", "--web", "/usr/share/novnc",
            str(NOVNC_PORT), f"localhost:{VNC_PORT}",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        print(f"[login] noVNC started on port {NOVNC_PORT}")

    # Launch Chrome
    proc = subprocess.Popen([
        CHROME_BIN,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={PROFILE}",
        "--no-sandbox", "--disable-gpu", "--enable-unsafe-swiftshader",
        "--no-first-run", "--disable-sync",
        "--window-size=1280,720",
        "https://accounts.google.com/",
    ], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    time.sleep(3)
    if proc.poll() is not None:
        print("[login] Chrome failed to start!")
        sys.exit(1)

    server_ip = os.environ.get("SERVER_IP", "<your-server-ip>")
    login_email = GOOGLE_EMAIL or "<your-google-email>"
    print(f"""
╔══════════════════════════════════════════════════╗
║        MEETING NOTES AGENT — Google Login        ║
╠══════════════════════════════════════════════════╣
║                                                  ║
║  Chrome opened on display {DISPLAY}                ║
║                                                  ║
║  Connect via noVNC:                              ║
║  http://{server_ip}:{NOVNC_PORT}/vnc.html        ║
║                                                  ║
║  Or VNC client: {server_ip}:{VNC_PORT}            ║
║                                                  ║
║  Login to: {login_email}                         ║
║  Then press Ctrl+C here to save & exit           ║
║                                                  ║
╚══════════════════════════════════════════════════╝
""")

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\n[login] Saving cookies and closing...")
        proc.terminate()
        print("[login] Done! Cookies saved to profile.")

if __name__ == "__main__":
    main()
