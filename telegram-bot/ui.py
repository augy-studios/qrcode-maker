"""Rich message helpers and the shared text.

Everything the bot says goes out through send_rich or one of its siblings, so
formatting, button registration and error handling stay in one place. Text goes
out as a Telegram Rich Message (reply.py): a view that builds its own Rich
Markdown passes it as ``rich=``, and text written in the HTML parse mode is
converted on the way through, so nothing is left on parse_mode. Only captions
under media still use it, because media messages have no rich form.

Previews are off unless a link is the point of the message, and any value that
came from a user is escaped on the way in.
"""

import base64
import html
import json
import logging

from telethon import Button, types
from telethon.errors import (
    MessageIdInvalidError,
    MessageNotModifiedError,
    UserIsBlockedError,
)

_CAPTIONED_MEDIA = (types.MessageMediaPhoto, types.MessageMediaDocument)

import db
import reply
from config import DONATION_URL, WEBAPP_URL
from reply import escape_md

log = logging.getLogger(__name__)


def esc(value) -> str:
    """Escape a value for the HTML parse mode."""
    return html.escape(str(value), quote=False)


def code(value) -> str:
    return f"<code>{esc(value)}</code>"


def rich(markdown: str, fallback: str | None = None) -> dict:
    """The reply.py contract. Without a fallback, one is read off the markdown."""
    return {"markdown": markdown, "fallback": fallback or md_plain(markdown)}


def md_plain(markdown: str) -> str:
    """A plain rendering of Rich Markdown for old clients and rejections."""
    import re
    text = markdown
    text = re.sub(r"!\[[^\]]*\]\(([^)\s]+)[^)]*\)", r"\1", text)   # images
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)             # headings
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)                # bold
    text = re.sub(r"(?<![\w\\])[*_](.+?)[*_](?!\w)", r"\1", text)  # italic
    text = re.sub(r"^\|\s*-{3,}.*$\n?", "", text, flags=re.M)      # table rules
    text = re.sub(r"\\([\\*_~`|\[\]#>=])", r"\1", text)            # escapes
    return text.strip()


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


def _as_rich(text, rich_content):
    """Whichever of the two the caller gave, as the reply.py contract."""
    return rich_content if rich_content is not None else reply.from_html(text or "")


async def send_rich(client, entity, text=None, *, rich=None, buttons=None,
                    file=None, reply_to=None, link_preview=False, silent=False,
                    force_document=False):
    """Send one message, with optional media and inline buttons.

    ``text`` is HTML in the old parse mode, ``rich`` is the reply.py contract.
    Either becomes a Rich Message on the way out; with a file, the text is the
    caption. Returns the sent message, or None when the user has blocked the
    bot.
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
            message = await reply.send_rich_message(
                client, entity, _as_rich(text, rich), buttons,
                reply_to=reply_to, silent=silent, link_preview=link_preview,
            )
    except UserIsBlockedError:
        log.info("Cannot reach %s, the bot is blocked.", entity)
        return None

    ids = _collect_button_ids(buttons)
    if ids and message is not None:
        await db.bind_button_message(ids, message.chat_id, message.id)
    return message


async def edit_rich(message, text=None, *, rich=None, buttons=None,
                    link_preview=False, file=None):
    """Rewrite a message in place, retiring the buttons it used to carry.

    No buttons means the keyboard goes; the rich edit sends an empty one for
    exactly that reason.
    """
    try:
        await db.retire_message_buttons(message.chat_id, message.id)
    except Exception:  # noqa: BLE001 - never let bookkeeping break a reply
        log.exception("Could not retire buttons for message %s", message.id)

    try:
        if file is not None or isinstance(
            getattr(message, "media", None), _CAPTIONED_MEDIA
        ):
            # A photo or file has a caption, not a rich body. A link preview
            # is media too as far as Telethon is concerned, but its message is
            # ordinary text and edits like one.
            await message.edit(text, parse_mode="html", buttons=buttons, file=file)
        else:
            await reply.edit_rich_message_at(
                message.client, message.chat_id, message.id,
                _as_rich(text, rich), buttons, link_preview=link_preview,
            )
    except MessageNotModifiedError:
        return message
    except MessageIdInvalidError:
        log.info("Message %s can no longer be edited.", message.id)
        return message

    ids = _collect_button_ids(buttons)
    if ids:
        await db.bind_button_message(ids, message.chat_id, message.id)
    return message


async def edit_rich_at(client, chat_id, message_id, text=None, *, rich=None,
                       buttons=None):
    """Edit a message the bot only has the id of, retiring its old buttons."""
    try:
        await db.retire_message_buttons(chat_id, message_id)
    except Exception:  # noqa: BLE001
        log.exception("Could not retire buttons for message %s", message_id)
    await reply.edit_rich_message_at(
        client, chat_id, message_id, _as_rich(text, rich), buttons
    )
    ids = _collect_button_ids(buttons)
    if ids:
        await db.bind_button_message(ids, chat_id, message_id)


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


def portal_open_url(kind: str, data: str) -> str:
    """A link that opens the portal with this code already filled in.

    The payload rides in the fragment, so it never reaches the server and
    needs no session: the page reads it, picks the matching tab and fills the
    fields, and from there the code can be edited, re-saved or downloaded like
    one made on the spot. base64url keeps every byte of the payload intact
    through Telegram and the browser, and a QR can hold at most a few KB, so
    the link never grows beyond what either will carry.
    """
    packed = json.dumps({"t": kind or "", "d": data}, ensure_ascii=False)
    token = base64.urlsafe_b64encode(packed.encode()).decode().rstrip("=")
    return f"{WEBAPP_URL}/#qr={token}"


def open_button(text: str, kind: str, data: str, fallback_url: str | None = None):
    """Open a saved code in the portal's editor, or the bare image without data."""
    if data:
        return Button.url(text, portal_open_url(kind, data))
    return Button.url(text, fallback_url) if fallback_url else None


def donate_button(text: str = "Support the project"):
    return Button.url(text, DONATION_URL) if DONATION_URL else None


def row(*cells):
    """Build a keyboard row, dropping anything that came back as None."""
    return [cell for cell in cells if cell is not None]


def keyboard(*rows):
    """Build a keyboard, dropping rows that ended up empty."""
    return [r for r in rows if r]


# ------------------------------------------------------------------- texts --

# Rich Markdown. The command names are filled in by start_text, and a slash
# command is one of the things Telegram picks out of plain text by itself, so
# they need no markup of their own.
START = (
    "# QR Maker\n"
    "\n"
    "Turn a link, a note, a WiFi network, a contact or a calendar event into a "
    "scannable code, without leaving this chat. Every code is drawn at the "
    "highest error correction level and carries a small mark at its centre. It "
    "says uwu to begin with, the same as the portal, and {watermark} makes it "
    "say whatever you like.\n"
    "\n"
    "## Make a code\n"
    "Send any text or link on its own, or use one of these.\n"
    "\n"
    "- {qr} followed by text or a link\n"
    "- {wifi} builds a WiFi code step by step\n"
    "- {contact} builds a contact card\n"
    "- {event} builds a calendar event\n"
    "\n"
    "## Read a code\n"
    "Send a photo of a QR code and it comes back as plain text. "
    "{decode} explains the details.\n"
    "\n"
    "## Keeping codes\n"
    "Press Save under any code and it is kept. With an account connected it "
    "goes straight there; without one it waits in this chat and moves across "
    "the moment you connect, skipping anything already on the account.\n"
    "\n"
    "- {saved} lists whichever of the two you have\n"
    "\n"
    "## Your account\n"
    "- {link} connects this chat to your portal account\n"
    "- {unlink} disconnects it again\n"
    "- {code} issues a code to type into the portal\n"
    "- {twofa} turns sign in approval on or off\n"
    "\n"
    "## Everything else\n"
    "- {settings} changes size, colour and error correction\n"
    "- {watermark} changes the mark in the middle\n"
    "- {cancel} abandons whatever is half finished\n"
    "\n"
    "Run {start} at any time to see this list again."
)

COMMAND_LIST = (
    "start", "qr", "wifi", "contact", "event", "decode", "link", "unlink",
    "code", "saved", "twofa", "settings", "watermark", "cancel",
)


def start_text() -> dict:
    """The welcome, as the reply.py contract."""
    markdown = START.format(**{name: f"/{name}" for name in COMMAND_LIST})
    return rich(markdown)


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
