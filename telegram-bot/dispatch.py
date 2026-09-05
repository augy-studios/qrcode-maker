"""Callback routing for persistent buttons, and the register of text flows.

Every inline button carries the same shape of callback data, ``b:<id>``, where
the id points at a row in the local SQLite buttons table. The row names a kind,
and each kind has a handler registered here.

Keeping the meaning in the database rather than in the callback payload is what
lets a button outlive the process. It also keeps the payload well under the
sixty four byte limit Telegram imposes, no matter how much context the button
needs to carry.

The second register does the same job for the other thing that waits on a user:
a flow expecting the next plain message in the chat. handlers_qr owns the
multi step builders and reads the next message for all of them, so anything
else that needs one message typed at it says so here rather than growing
another listener that would race the first.
"""

import logging
import re

log = logging.getLogger(__name__)

_HANDLERS: dict[str, callable] = {}
_TEXT_FLOWS: dict[str, callable] = {}
_FLOW_LABELS: dict[str, str] = {}


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


# ------------------------------------------------------------- text flows --


def name_flow(name: str, label: str) -> None:
    """Give a flow the words /cancel uses when it throws one away."""
    _FLOW_LABELS[name] = label


def text_flow(name: str, label: str):
    """Register the handler for a flow that is waiting on one typed message.

    The handler is called as ``(client, chat_id, sender_id, flow_row, value)``
    and owns the flow from there, including clearing it.
    """

    def decorator(func):
        if name in _TEXT_FLOWS:
            raise RuntimeError(f"Duplicate text flow handler for {name!r}")
        _TEXT_FLOWS[name] = func
        name_flow(name, label)
        return func

    return decorator


def flow_handler(name: str):
    return _TEXT_FLOWS.get(name)


def flow_label(name: str) -> str:
    return _FLOW_LABELS.get(name, "thing you had in progress")
