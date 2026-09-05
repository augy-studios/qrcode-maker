"""Rich message helpers and the shared text.

Everything the bot says goes out through send_rich or one of its siblings, so
formatting, button registration and error handling stay in one place. Messages
are HTML, previews are off unless a link is the point of the message, and any
value that came from a user is escaped on the way in.
"""

import html
import logging

from telethon import Button
from telethon.errors import (
    MessageIdInvalidError,
    MessageNotModifiedError,
    UserIsBlockedError,
)

import db
from config import DONATION_URL, WEBAPP_URL

log = logging.getLogger(__name__)


def esc(value) -> str:
    """Escape a value for the HTML parse mode."""
    return html.escape(str(value), quote=False)


def code(value) -> str:
    return f"<code>{esc(value)}</code>"


def _collect_button_ids(buttons) -> list[str]:
    """Pull our own button ids out of a keyboard so we can bind them later."""
    found = []
    if not buttons:
        return found
    rows = buttons if isinstance(buttons, (list, tuple)) else [buttons]
    for row in rows:
        cells = row if isinstance(row, (list, tuple)) else [row]
        for cell in cells:
            data = getattr(cell, "data", None)
            if isinstance(data, bytes) and data.startswith(b"b:"):
                found.append(data[2:].decode())
    return found


async def send_rich(client, entity, text=None, *, buttons=None, file=None,
                    reply_to=None, link_preview=False, silent=False,
                    force_document=False):
    """Send one formatted message, with optional media and inline buttons.

    Returns the sent message, or None when the user has blocked the bot.
    """
    try:
        if file is not None:
            message = await client.send_file(
                entity,
                file,
                caption=text,
                parse_mode="html",
                buttons=buttons,
                reply_to=reply_to,
                silent=silent,
                force_document=force_document,
            )
        else:
            message = await client.send_message(
                entity,
                text,
                parse_mode="html",
                buttons=buttons,
                reply_to=reply_to,
                link_preview=link_preview,
                silent=silent,
            )
    except UserIsBlockedError:
        log.info("Cannot reach %s, the bot is blocked.", entity)
        return None

    ids = _collect_button_ids(buttons)
    if ids:
        await db.bind_button_message(ids, message.chat_id, message.id)
    return message


async def edit_rich(message, text=None, *, buttons=None, link_preview=False,
                    file=None):
    """Rewrite a message in place, retiring the buttons it used to carry."""
    try:
        await db.retire_message_buttons(message.chat_id, message.id)
    except Exception:  # noqa: BLE001 - never let bookkeeping break a reply
        log.exception("Could not retire buttons for message %s", message.id)

    try:
        if file is not None:
            edited = await message.edit(
                text, parse_mode="html", buttons=buttons, file=file
            )
        else:
            edited = await message.edit(
                text, parse_mode="html", buttons=buttons,
                link_preview=link_preview,
            )
    except MessageNotModifiedError:
        return message
    except MessageIdInvalidError:
        log.info("Message %s can no longer be edited.", message.id)
        return message

    ids = _collect_button_ids(buttons)
    if ids:
        await db.bind_button_message(ids, message.chat_id, message.id)
    return edited


async def reply_rich(event, text=None, **kwargs):
    """Reply in the chat the event came from."""
    return await send_rich(event.client, event.chat_id, text, **kwargs)


async def inline_button(text: str, kind: str, payload: dict | None = None,
                        owner_id: int | None = None, ttl: int | None = None):
    """Create a persistent inline button backed by a row in SQLite."""
    data = await db.create_button(kind, payload, owner_id, ttl)
    return Button.inline(text, data)


def url_button(text: str, url: str):
    return Button.url(text, url)


def portal_button(text: str = "Open the portal"):
    return Button.url(text, WEBAPP_URL)


def donate_button(text: str = "Support the project"):
    return Button.url(text, DONATION_URL) if DONATION_URL else None


def row(*cells):
    """Build a keyboard row, dropping anything that came back as None."""
    return [cell for cell in cells if cell is not None]


def keyboard(*rows):
    """Build a keyboard, dropping rows that ended up empty."""
    return [r for r in rows if r]


# ------------------------------------------------------------------- texts --

START = (
    "<b>QR Maker</b>\n"
    "\n"
    "Turn a link, a note, a WiFi network, a contact or a calendar event into a "
    "scannable code, without leaving this chat. Every code is drawn at the "
    "highest error correction level and carries a small mark at its centre. It "
    "says uwu to begin with, the same as the portal, and {watermark} makes it "
    "say whatever you like.\n"
    "\n"
    "<b>Make a code</b>\n"
    "Send any text or link on its own, or use one of these.\n"
    "{qr} followed by text or a link\n"
    "{wifi} builds a WiFi code step by step\n"
    "{contact} builds a contact card\n"
    "{event} builds a calendar event\n"
    "\n"
    "<b>Read a code</b>\n"
    "Send a photo of a QR code and it comes back as plain text. "
    "{decode} explains the details.\n"
    "\n"
    "<b>Keeping codes</b>\n"
    "Press Save under any code and it is kept. With an account connected it "
    "goes straight there; without one it waits in this chat and moves across "
    "the moment you connect, skipping anything already on the account.\n"
    "{saved} lists whichever of the two you have\n"
    "\n"
    "<b>Your account</b>\n"
    "{link} connects this chat to your portal account\n"
    "{unlink} disconnects it again\n"
    "{code} issues a code to type into the portal\n"
    "{twofa} turns sign in approval on or off\n"
    "\n"
    "<b>Everything else</b>\n"
    "{settings} changes size, colour and error correction\n"
    "{watermark} changes the mark in the middle\n"
    "{cancel} abandons whatever is half finished\n"
    "\n"
    "Run {start} at any time to see this list again."
)

COMMAND_LIST = (
    "start", "qr", "wifi", "contact", "event", "decode", "link", "unlink",
    "code", "saved", "twofa", "settings", "watermark", "cancel",
)


def start_text() -> str:
    return START.format(**{name: f"/{name}" for name in COMMAND_LIST})


# What Telegram shows in the command menu. Kept here so bot.py can push it and
# SETUP.md can quote it, with no chance of the two drifting apart. Telegram caps
# a description at 256 characters and requires lower case command names.
COMMAND_DESCRIPTIONS = (
    ("start", "What this is, and the full command list"),
    ("qr", "Turn a link or some text into a code"),
    ("wifi", "Build a WiFi code step by step"),
    ("contact", "Build a contact card step by step"),
    ("event", "Build a calendar event step by step"),
    ("decode", "Read a QR code out of an image"),
    ("link", "Connect this chat to your portal account"),
    ("code", "Get a six digit code for the portal"),
    ("unlink", "Disconnect this chat from your account"),
    ("saved", "Browse the codes you have kept"),
    ("twofa", "Turn sign in approval on or off"),
    ("settings", "Size, colour and error correction"),
    ("watermark", "Change the mark in the middle of your codes"),
    ("cancel", "Abandon whatever is half finished"),
)


NOT_CONFIGURED = (
    "Account features are switched off on this instance, because it is running "
    "without portal credentials. Generating and reading codes still works."
)

NO_LINK = (
    "This chat is not connected to a portal account yet. Run /link to connect "
    "it, and your saved codes become reachable from here."
)

RATE_LIMITED = (
    "That is a lot of codes in a short window. Give it a minute and try again."
)
