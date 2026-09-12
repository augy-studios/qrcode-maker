"""Telegram Rich Messages over raw TL requests.

Telethon's send_message and edit_message do not expose the rich_message field
that arrived with layer 227, so the requests are built here by hand. Every
helper takes the same contract, a dict with the content and a plain fallback:

    rich = {"markdown": "<Rich Markdown>", "fallback": "<plain text>"}
    rich = {"html": "<Rich HTML>", "fallback": "<plain text>"}

The fallback goes in the request's required message field. It is what an old
client shows, and what gets sent if Telegram rejects the rich payload for any
reason: a rich failure never surfaces as an error, it is logged and the plain
text goes out instead.

No parse_mode anywhere in here. The fallback is plain, the rich half is parsed
by Telegram from the markdown or html field, and mixing the two is exactly the
bug this module exists to avoid.
"""

import logging
import re

from telethon import types
from telethon.errors import MessageNotModifiedError
from telethon.tl import functions

log = logging.getLogger(__name__)


def _rich_input(rich):
    if rich.get("html") is not None:
        return types.InputRichMessageHTML(html=rich["html"])
    return types.InputRichMessageMarkdown(markdown=rich["markdown"])


# Editing without reply_markup keeps the old keyboard; an empty inline
# keyboard is what actually removes it.
_NO_BUTTONS = types.ReplyInlineMarkup(rows=[])


def sent_message_id(result):
    """Id of the message a raw send created (bot sends come back as Updates)."""
    if isinstance(result, (types.Message, types.UpdateShortSentMessage)):
        return result.id
    for update in getattr(result, "updates", []):
        if isinstance(update, types.UpdateMessageID):
            return update.id
        if isinstance(update, (types.UpdateNewMessage, types.UpdateNewChannelMessage)):
            return update.message.id
    return None


async def send_rich_message(client, entity, rich, buttons=None, *,
                            reply_to=None, silent=False, link_preview=False):
    """Send one rich message. Returns Telethon's Message for the sent one."""
    markup = client.build_reply_markup(buttons) if buttons else None
    peer = await client.get_input_entity(entity)
    request = functions.messages.SendMessageRequest(
        peer=peer,
        message=rich["fallback"],
        rich_message=_rich_input(rich),
        reply_markup=markup,
        reply_to=(types.InputReplyToMessage(reply_to_msg_id=reply_to)
                  if reply_to else None),
        silent=silent or None,
        no_webpage=not link_preview,
    )
    try:
        result = await client(request)
    except Exception as err:  # noqa: BLE001 - the plain text must still go out
        log.warning("Rich send failed, falling back to plain text: %s", err)
        return await client.send_message(
            entity, rich["fallback"], buttons=buttons, reply_to=reply_to,
            silent=silent, link_preview=link_preview,
        )
    return client._get_response_message(request, result, peer)


async def edit_rich_message_at(client, peer, msg_id, rich, buttons=None, *,
                               link_preview=False):
    """Edit by chat + message id. No buttons => keyboard removed."""
    markup = client.build_reply_markup(buttons) if buttons else _NO_BUTTONS
    peer = await client.get_input_entity(peer)
    try:
        await client(functions.messages.EditMessageRequest(
            peer=peer, id=msg_id, message=rich["fallback"],
            rich_message=_rich_input(rich), reply_markup=markup,
            no_webpage=not link_preview,
        ))
    except MessageNotModifiedError:
        return
    except Exception as err:  # noqa: BLE001
        log.warning("Rich edit failed, falling back to plain text: %s", err)
        await client.edit_message(peer, msg_id, text=rich["fallback"],
                                  buttons=buttons, link_preview=link_preview)


async def edit_rich_message(client, event, rich, buttons=None):
    """Edit the message a CallbackQuery came from, regular chat or inline-mode."""
    markup = client.build_reply_markup(buttons) if buttons else _NO_BUTTONS
    is_inline = isinstance(event.query, types.UpdateInlineBotCallbackQuery)
    try:
        if is_inline:
            await client(functions.messages.EditInlineBotMessageRequest(
                id=event.query.msg_id, message=rich["fallback"],
                rich_message=_rich_input(rich), reply_markup=markup))
        else:
            await client(functions.messages.EditMessageRequest(
                peer=event.query.peer, id=event.query.msg_id,
                message=rich["fallback"], rich_message=_rich_input(rich),
                reply_markup=markup))
    except MessageNotModifiedError:
        return
    except Exception as err:  # noqa: BLE001
        log.warning("Rich edit failed, falling back to plain text: %s", err)
        if is_inline:
            await client.edit_message(event.query.msg_id, text=rich["fallback"],
                                      buttons=buttons)
        else:
            await client.edit_message(event.query.peer, event.query.msg_id,
                                      text=rich["fallback"], buttons=buttons)


def inline_article(result_id: str, title: str, description: str, rich,
                   client, buttons=None):
    """An inline-mode result carrying a rich message.

    Telethon's builder.article cannot carry one, so this is the raw result.
    Hand it to event.answer like any other.
    """
    return types.InputBotInlineResult(
        id=result_id,
        type="article",
        title=title,
        description=description,
        send_message=types.InputBotInlineMessageRichMessage(
            rich_message=_rich_input(rich),
            reply_markup=client.build_reply_markup(buttons) if buttons else None,
        ),
    )


# --------------------------------------------------------------- escaping --

_MD_SPECIAL = re.compile(r"([\\*_~`|\[\]#>=])")


def escape_md(text) -> str:
    """Escape user/data text for Telegram's Rich Markdown dialect."""
    return _MD_SPECIAL.sub(r"\\\1", str(text))


def escape_cell(text) -> str:
    """Escape for a GFM table cell; also flattens newlines so the row stays intact."""
    return escape_md(str(text).replace("\n", " "))


def table(headers: list[str], rows: list[list]) -> str:
    """A pipe table with a blank leading header cell, for row-labelled data."""
    lines = ["| " + " | ".join(["", *headers]) + " |",
             "| " + " | ".join(["---"] * (len(headers) + 1)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(escape_cell(v) for v in row) + " |")
    return "\n".join(lines)


# ------------------------------------------------- legacy HTML on the way in --
#
# Most of what the bot says was written for Telegram's HTML parse mode: <b>,
# <i>, <code>, <pre> and newlines. Rich HTML knows every one of those tags but
# treats newlines the way a browser does, so they have to become paragraphs
# and line breaks before the text is a rich message. A bold line on its own,
# with a blank line after it, is a heading in all but name, so it becomes one.

_TAG = re.compile(r"<[^>]+>")
_ENTITY = re.compile(r"&(lt|gt|amp|quot|#\d+|#x[0-9a-fA-F]+);")
_WHOLE_BOLD = re.compile(r"^<b>(.*)</b>$", re.S)
_PRE = re.compile(r"(<pre>.*?</pre>)", re.S)


def plain_text(html_text: str) -> str:
    """The fallback: tags stripped, entities resolved, layout kept."""
    import html as html_lib
    return html_lib.unescape(_TAG.sub("", html_text))


def html_to_rich(html_text: str) -> str:
    """Rewrite parse-mode HTML as Rich HTML with the same layout."""
    out = []
    for piece in _PRE.split(html_text):
        if piece.startswith("<pre>"):
            out.append(piece)
            continue
        paragraphs = re.split(r"\n\s*\n", piece.strip("\n"))
        for index, paragraph in enumerate(paragraphs):
            if not paragraph.strip():
                continue
            whole = _WHOLE_BOLD.match(paragraph.strip())
            if whole and "\n" not in paragraph.strip() and len(paragraphs) > 1:
                # The first heading is the title; any later one is a section.
                tag = "h3" if index == 0 else "h4"
                out.append(f"<{tag}>{whole.group(1)}</{tag}>")
                continue
            out.append("<p>" + paragraph.strip("\n").replace("\n", "<br/>") + "</p>")
    return "".join(out)


def from_html(html_text: str) -> dict:
    """The rich contract for text written in the old HTML parse mode."""
    return {"html": html_to_rich(html_text), "fallback": plain_text(html_text)}
