"""Callback routing for persistent buttons.

Every inline button carries the same shape of callback data, ``b:<id>``, where
the id points at a row in the local SQLite buttons table. The row names a kind,
and each kind has a handler registered here.

Keeping the meaning in the database rather than in the callback payload is what
lets a button outlive the process. It also keeps the payload well under the
sixty four byte limit Telegram imposes, no matter how much context the button
needs to carry.
"""

import logging
import re

log = logging.getLogger(__name__)

_HANDLERS: dict[str, callable] = {}


def command(*names: str) -> re.Pattern:
    """Build the pattern for a slash command.

    Telegram appends the bot handle to commands sent in groups. The handle is
    matched and thrown away here, which is the only place in the codebase that
    has to know it exists, and it never appears in anything the bot says.
    """
    alternatives = "|".join(re.escape(name) for name in names)
    return re.compile(
        rf"^[/!]({alternatives})(?:@[A-Za-z0-9_]+)?(?:\s+([\s\S]*))?$",
        re.IGNORECASE,
    )


def private(event) -> bool:
    """Gate for every message handler.

    The bot is a private chat tool. It is not meant to be added to groups, and
    BotFather is told to refuse that, but a bot already sitting in a group when
    the setting changes would still receive from it. This is the belt to that
    braces: nothing outside a one to one chat is ever acted on.
    """
    return bool(getattr(event, "is_private", False))


def argument(event) -> str:
    """The text after a command, or an empty string."""
    match = getattr(event, "pattern_match", None)
    if not match:
        return ""
    try:
        return (match.group(2) or "").strip()
    except IndexError:
        return ""


def on(kind: str):
    """Register the handler for one button kind."""

    def decorator(func):
        if kind in _HANDLERS:
            raise RuntimeError(f"Duplicate button handler for kind {kind!r}")
        _HANDLERS[kind] = func
        return func

    return decorator


def get(kind: str):
    return _HANDLERS.get(kind)


def known_kinds() -> list[str]:
    return sorted(_HANDLERS)
