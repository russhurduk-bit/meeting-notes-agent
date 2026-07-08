"""Telegram call recorder — joins TG conference calls via Pyrogram + pytgcalls."""
import asyncio
import os
import re
from pyrogram import Client
from pyrogram.raw.types import InputGroupCallSlug
from pyrogram.raw.functions.phone import JoinGroupCall, GetGroupCall
from pytgcalls import PyTgCalls

# Telegram API credentials — obtain from https://my.telegram.org
API_ID = int(os.environ.get("TG_API_ID", "0"))
API_HASH = os.environ.get("TG_API_HASH", "")

BASE_DIR = os.environ.get("WORKDIR", os.path.dirname(os.path.abspath(__file__)))
SESSION_NAME = os.environ.get("TG_SESSION_NAME", "tg_session")
SESSION_PATH = os.path.join(BASE_DIR, SESSION_NAME)

# Extract slug from t.me/call/SLUG
CALL_LINK_PATTERN = re.compile(r't\.me/call/([A-Za-z0-9_-]+)')


class TgCallRecorder:
    def __init__(self):
        self.client = Client(
            SESSION_NAME,
            workdir=BASE_DIR,
            api_id=API_ID,
            api_hash=API_HASH,
        )
        self.pytgcalls = PyTgCalls(self.client)
        self._active_chat = None

    async def start(self):
        await self.client.start()
        await self.pytgcalls.start()
        me = await self.client.get_me()
        print(f"[tg_call] Connected as {me.first_name} (@{me.username})")

    async def join_and_record(self, call_link: str, output_path: str) -> bool:
        """Join conference call by link and record.

        Args:
            call_link: full URL like https://t.me/call/SLUG
            output_path: path for audio recording

        Returns True if joined successfully.
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Extract slug from link
        match = CALL_LINK_PATTERN.search(call_link)
        if not match:
            print(f"[tg_call] Invalid call link: {call_link}")
            return False

        slug = match.group(1)
        print(f"[tg_call] Call slug: {slug}")

        try:
            # Get group call info via slug
            input_call = InputGroupCallSlug(slug=slug)
            call_info = await self.client.invoke(GetGroupCall(call=input_call, limit=1))
            call = call_info.call
            print(f"[tg_call] Call: id={call.id}, title={getattr(call, 'title', 'N/A')}, participants={getattr(call, 'participants_count', '?')}")

            # Get chat_id from the call
            chat_id = getattr(call, 'chat_id', None) or getattr(call, 'channel_id', None)
            if not chat_id:
                # Try to find via participants or call object
                print(f"[tg_call] Call object: {call}")
                # Use the call ID directly with pytgcalls
                chat_id = call.id

            self._active_chat = chat_id

            # Record via pytgcalls
            await self.pytgcalls.record(chat_id, output_path)
            print(f"[tg_call] Recording → {output_path}")
            return True

        except Exception as e:
            print(f"[tg_call] Join failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def is_active(self) -> bool:
        """Check if still in call."""
        if self._active_chat is None:
            return False
        return self._active_chat in self.pytgcalls.calls

    async def leave(self):
        """Leave current call."""
        if self._active_chat is not None:
            try:
                await self.pytgcalls.leave_call(self._active_chat)
                print(f"[tg_call] Left call")
            except Exception as e:
                print(f"[tg_call] Leave error: {e}")
            self._active_chat = None

    async def stop(self):
        try:
            await self.pytgcalls.stop()
        except Exception:
            pass
        await self.client.stop()


def extract_call_link(text: str) -> str:
    """Extract t.me/call/SLUG from text. Returns full match or None."""
    match = CALL_LINK_PATTERN.search(text)
    return match.group(0) if match else None
