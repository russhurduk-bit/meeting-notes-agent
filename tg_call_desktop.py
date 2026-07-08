"""TG Conference Call via Telegram Desktop automation.

Opens call link in tdesktop, finds and clicks 'Join Group Call' button,
records audio via PulseAudio.
"""
import subprocess
import os
import time
import re
import numpy as np
from PIL import Image

DISPLAY = os.environ.get("TDESKTOP_DISPLAY", ":98")
TDESKTOP = os.environ.get("TDESKTOP_BIN", "/opt/telegram-desktop/Telegram")
BASE_DIR = os.environ.get("WORKDIR", os.path.dirname(os.path.abspath(__file__)))
WORKDIR = os.environ.get("TDESKTOP_DATA", os.path.join(BASE_DIR, "tdesktop_data"))
PULSE_SINK = os.environ.get("PULSE_SINK", "meet_capture")
PULSE_SERVER = os.environ.get("PULSE_SERVER", "/run/user/0/pulse/native")
TG_SESSION_NAME = os.environ.get("TG_SESSION_NAME", "tg_session")
API_ID = int(os.environ.get("TG_API_ID", "0"))
API_HASH = os.environ.get("TG_API_HASH", "")
SLUG_STATE_FILE = os.environ.get("SLUG_STATE_FILE", "/tmp/meeting_notes_current_slug")
BUTTON_COLOR = (64, 167, 227)  # RGB of "Join Group Call" button
COLOR_TOLERANCE = 30


def open_call_link(slug: str):
    """Open conference call dialog in tdesktop."""
    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    env["QT_QPA_PLATFORM"] = "xcb"
    env["PULSE_SINK"] = PULSE_SINK
    env["PULSE_SERVER"] = PULSE_SERVER

    # Send tg:// link to running tdesktop
    subprocess.Popen(
        [TDESKTOP, "-workdir", WORKDIR, "--", f"tg://call?slug={slug}"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    print(f"[tg_call] Opened call dialog for slug={slug}")


def find_join_button() -> tuple:
    """Take screenshot and find 'Join Group Call' button coordinates.
    Returns (x, y) center of button, or None if not found.
    """
    screenshot_path = "/tmp/td_autojoin.png"
    subprocess.run(
        ["import", "-window", "root", screenshot_path],
        env={"DISPLAY": DISPLAY}, capture_output=True,
    )

    img = Image.open(screenshot_path)
    px = np.array(img)

    # Find blue button pixels matching BUTTON_COLOR
    r, g, b = BUTTON_COLOR
    tol = COLOR_TOLERANCE
    mask = (
        (px[:, :, 0] >= r - tol) & (px[:, :, 0] <= r + tol) &
        (px[:, :, 1] >= g - tol) & (px[:, :, 1] <= g + tol) &
        (px[:, :, 2] >= b - tol) & (px[:, :, 2] <= b + tol)
    )

    ys, xs = np.where(mask)
    if len(xs) < 100:
        return None

    # Find the button region (horizontal bar of blue pixels)
    from collections import Counter
    y_counts = Counter(ys)
    dense_ys = [y for y, count in y_counts.items() if count > 80]

    if not dense_ys:
        return None

    btn_y_min = min(dense_ys)
    btn_y_max = max(dense_ys)
    btn_xs = xs[(ys >= btn_y_min) & (ys <= btn_y_max)]

    cx = int((btn_xs.min() + btn_xs.max()) / 2)
    cy = int((btn_y_min + btn_y_max) / 2)

    print(f"[tg_call] Button found at ({cx}, {cy}), size {btn_xs.max()-btn_xs.min()}x{btn_y_max-btn_y_min}")
    return (cx, cy)


def click_join_button() -> bool:
    """Find and click the Join Group Call button. Returns True if clicked."""
    for attempt in range(10):
        coords = find_join_button()
        if coords:
            x, y = coords
            os.environ["DISPLAY"] = DISPLAY
            import pyautogui
            pyautogui.click(x, y)
            print(f"[tg_call] Clicked Join at ({x}, {y})")
            return True
        print(f"[tg_call] Button not found, attempt {attempt + 1}/10")
        time.sleep(2)
    return False


def join_conference_call(slug: str) -> bool:
    """Full flow: open link → find button → click → joined."""
    # Save slug for is_in_call() checks
    with open(SLUG_STATE_FILE, "w") as f:
        f.write(slug)

    open_call_link(slug)
    time.sleep(8)  # wait for dialog to appear
    return click_join_button()


def is_in_call() -> bool:
    """Check if other participants are in the call via Pyrogram API.
    Returns False if alone or not in call.
    """
    try:
        import asyncio
        from pyrogram import Client
        from pyrogram.raw.types import InputGroupCallSlug
        from pyrogram.raw.functions.phone import GetGroupCall

        # Read current slug from state file
        if not os.path.exists(SLUG_STATE_FILE):
            return False

        with open(SLUG_STATE_FILE) as f:
            slug = f.read().strip()

        if not slug:
            return False

        async def check():
            app = Client(TG_SESSION_NAME, workdir=BASE_DIR,
                         api_id=API_ID, api_hash=API_HASH)
            await app.start()
            result = await app.invoke(GetGroupCall(
                call=InputGroupCallSlug(slug=slug), limit=10
            ))
            await app.stop()
            return result.call.participants_count

        count = asyncio.run(check())
        print(f"[tg_call] Participants: {count}")
        return count > 1  # >1 means someone else is there
    except Exception as e:
        print(f"[tg_call] is_in_call check failed: {e}")
        # Fallback: check if tdesktop process exists
        r = subprocess.run(["pgrep", "-f", "Telegram.*tdesktop_data"], capture_output=True)
        return r.returncode == 0


def leave_call():
    """Leave call by killing and restarting tdesktop."""
    subprocess.run(["pkill", "-f", "Telegram.*tdesktop_data"], capture_output=True)
    import time
    time.sleep(2)
    # Restart tdesktop (watchdog will also do this, but let's be explicit)
    env = {
        "DISPLAY": DISPLAY,
        "QT_QPA_PLATFORM": "xcb",
        "PULSE_SINK": PULSE_SINK,
        "PULSE_SERVER": PULSE_SERVER,
        "HOME": os.environ.get("HOME", os.path.expanduser("~")),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
    }
    subprocess.Popen(
        [TDESKTOP, "-workdir", WORKDIR],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    print("[tg_call] Left call (killed + restarted tdesktop)")


def extract_slug(url: str) -> str:
    """Extract slug from t.me/call/SLUG URL."""
    match = re.search(r't\.me/call/([A-Za-z0-9_-]+)', url)
    return match.group(1) if match else None
