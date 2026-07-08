"""Google Meet bot — joins meeting, sits silently, captures audio."""
import asyncio
import subprocess
import os
import time
import hmac
import hashlib
import struct
import base64
from playwright.async_api import async_playwright, Page

from config import (
    GOOGLE_EMAIL, GOOGLE_PASSWORD, GOOGLE_TOTP_SECRET,
    PROFILE_DIR, BOT_NAME, BASE_DIR,
)

CDP_PORT = int(os.environ.get("CDP_PORT", "9333"))
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
DISPLAY = os.environ.get("MEET_DISPLAY", ":99")

# Directory for debug screenshots (kept inside the project tree)
DEBUG_DIR = os.environ.get("DEBUG_DIR", os.path.join(BASE_DIR, "logs"))


def generate_totp(secret: str) -> str:
    """Generate TOTP code from base32 secret."""
    key = base64.b32decode(secret.upper() + "=" * ((8 - len(secret) % 8) % 8))
    iv = int(time.time()) // 30
    h = hmac.new(key, struct.pack(">Q", iv), hashlib.sha1).digest()
    o = h[-1] & 0xF
    code = f"{(struct.unpack('>I', h[o:o+4])[0] & 0x7FFFFFFF) % 1000000:06d}"
    return code


def launch_chrome():
    """Launch Chrome with remote debugging, return subprocess."""
    import glob
    import urllib.request
    os.makedirs(PROFILE_DIR, exist_ok=True)

    # Kill any existing chrome on our CDP port
    subprocess.run(["pkill", "-9", "-f", f"remote-debugging-port={CDP_PORT}"],
                   capture_output=True)
    time.sleep(2)

    # Clean stale singleton locks
    for f in glob.glob(os.path.join(PROFILE_DIR, "Singleton*")):
        os.remove(f)

    env = {
        "DISPLAY": DISPLAY,
        "PULSE_SINK": os.environ.get("PULSE_SINK", "meet_capture"),
        "HOME": os.environ.get("HOME", os.path.expanduser("~")),
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    }

    chrome_bin = os.environ.get("CHROME_BIN", "google-chrome")
    cmd = [
        "setsid",  # detach from controlling terminal
        chrome_bin,
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-allow-origins=*",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-sandbox",
        "--disable-gpu",
        "--enable-unsafe-swiftshader",
        "--disable-breakpad",
        "--disable-crash-reporter",
        "--disable-features=WebRtcHideLocalIpsWithMdns,CrashReporting",
        "--use-fake-ui-for-media-stream",
        "--autoplay-policy=no-user-gesture-required",
        "--window-size=1280,720",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-translate",
        "about:blank",
    ]
    devnull = open(os.devnull, "r+b")
    proc = subprocess.Popen(
        cmd, env=env,
        stdin=devnull,
        stdout=devnull,
        stderr=devnull,
    )
    print(f"[meet] Chrome launched (pid={proc.pid})")

    # Wait for CDP to be ready
    for i in range(20):
        time.sleep(0.5)
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode()[-500:] if proc.stderr else ""
            raise RuntimeError(f"Chrome died with exit code {proc.poll()}, stderr: {stderr}")
        try:
            urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2)
            print(f"[meet] CDP ready at {CDP_URL}")
            return proc
        except Exception:
            continue

    raise RuntimeError("Chrome CDP did not become ready in 10s")


async def connect_browser() -> tuple:
    """Connect to running Chrome via CDP with retry."""
    for attempt in range(3):
        try:
            pw = await async_playwright().start()
            browser = await pw.chromium.connect_over_cdp(CDP_URL, timeout=30000)
            print(f"[meet] Connected to Chrome via CDP")
            return pw, browser
        except Exception as e:
            print(f"[meet] CDP connect attempt {attempt+1} failed: {e}")
            try:
                await pw.stop()
            except Exception:
                pass
            if attempt < 2:
                await asyncio.sleep(3)
    raise RuntimeError("Failed to connect to Chrome CDP after 3 attempts")


async def google_login(page: Page):
    """Login to Google account if not already logged in."""
    await page.goto("https://accounts.google.com/", timeout=20000)
    await page.wait_for_load_state("load", timeout=15000)

    # Check if already logged in
    if "myaccount.google.com" in page.url or "SignOutOptions" in await page.content():
        print("[meet] Already logged into Google")
        return

    print("[meet] Logging into Google...")

    # Email
    email_input = page.locator('input[type="email"]')
    if await email_input.count() > 0:
        await email_input.fill(GOOGLE_EMAIL)
        await page.locator("#identifierNext button").click()
        await page.wait_for_timeout(2000)

    # Password
    password_input = page.locator('input[type="password"]')
    await password_input.wait_for(state="visible", timeout=10000)
    await password_input.fill(GOOGLE_PASSWORD)
    await page.locator("#passwordNext button").click()
    await page.wait_for_timeout(3000)

    # Check for TOTP 2FA
    totp_input = page.locator('input[type="tel"]#totpPin, input[name="totpPin"]')
    if await totp_input.count() > 0 and GOOGLE_TOTP_SECRET:
        code = generate_totp(GOOGLE_TOTP_SECRET)
        print(f"[meet] Entering TOTP: {code}")
        await totp_input.fill(code)
        await page.locator("#totpNext button").click()
        await page.wait_for_timeout(3000)

    os.makedirs(DEBUG_DIR, exist_ok=True)
    await page.screenshot(path=os.path.join(DEBUG_DIR, "debug_login.png"))
    print(f"[meet] Login done, URL: {page.url}")


async def join_meeting(page: Page, meet_url: str):
    """Navigate to Meet link and join the meeting."""
    print(f"[meet] Joining {meet_url}")
    await page.goto(meet_url, wait_until="load", timeout=30000)
    await page.wait_for_timeout(5000)

    # Dismiss notification popup ("Not now")
    try:
        not_now = page.locator('button:has-text("Not now"), button:has-text("Не сейчас")')
        if await not_now.count() > 0:
            await not_now.first.click()
            print("[meet] Dismissed notification popup")
            await page.wait_for_timeout(1000)
    except Exception:
        pass

    # Dismiss any other dialogs ("Got it", "Dismiss")
    try:
        for dismiss_text in ["Got it", "Dismiss", "Понятно", "Закрыть"]:
            btn = page.locator(f'button:has-text("{dismiss_text}")')
            if await btn.count() > 0:
                await btn.first.click()
                await page.wait_for_timeout(500)
    except Exception:
        pass

    # Turn off microphone (we just listen)
    try:
        mic_btn = page.locator('[data-is-muted="false"][aria-label*="microphone" i]')
        if await mic_btn.count() > 0:
            await mic_btn.first.click()
            print("[meet] Microphone OFF")
            await page.wait_for_timeout(500)
    except Exception:
        pass

    # Click "Ask to join" or "Join now"
    join_clicked = False
    for selector in [
        'button:has-text("Ask to join")',
        'button:has-text("Join now")',
        'button:has-text("Присоединиться")',
        'button:has-text("Попросить")',
    ]:
        btn = page.locator(selector)
        if await btn.count() > 0:
            await btn.first.click()
            join_clicked = True
            print(f"[meet] Clicked: {selector}")
            break

    if not join_clicked:
        print("[meet] WARNING: Could not find join button")

    # Wait for meeting to actually load (host approval + WebRTC setup)
    await page.wait_for_timeout(10000)
    os.makedirs(DEBUG_DIR, exist_ok=True)
    await page.screenshot(path=os.path.join(DEBUG_DIR, "debug_meeting.png"))
    print("[meet] In the meeting")


async def wait_for_meeting_end(page: Page, check_interval: int = 15):
    """Wait until the meeting ends or we get kicked."""
    print("[meet] Monitoring meeting... (Ctrl+C to stop)")
    while True:
        try:
            left_indicator = page.locator('text="You left the meeting"')
            left_ru = page.locator('text="Вы покинули"')
            returned = page.locator('text="Return to home screen"')

            if (await left_indicator.count() > 0 or
                    await left_ru.count() > 0 or
                    await returned.count() > 0):
                print("[meet] Meeting ended")
                return "ended"

            if "meet.google.com" not in page.url:
                print("[meet] Redirected away from Meet")
                return "redirected"

            await asyncio.sleep(check_interval)
        except Exception as e:
            print(f"[meet] Monitor error: {e}")
            return "error"
