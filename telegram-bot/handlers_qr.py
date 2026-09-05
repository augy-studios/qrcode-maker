"""Making codes and reading them back.

Three ways in. A command with the content on the same line, a guided builder
for the shapes that have several fields, or plain text sent on its own in a
private chat. All three land in deliver_code, so a code looks the same however
it was asked for.
"""

import asyncio
import io
import logging

from telethon import events

import db
import dispatch
import qrgen
import ui
from config import (
    MAX_PAYLOAD_CHARS,
    RATE_LIMIT_MAX,
    RATE_LIMIT_WINDOW,
)

log = logging.getLogger(__name__)

try:
    from PIL import Image
    from pyzbar import pyzbar

    DECODING_AVAILABLE = True
except Exception:  # noqa: BLE001 - libzbar is a system package and may be absent
    DECODING_AVAILABLE = False
    log.warning(
        "Reading codes is unavailable. Install the zbar shared library "
        "(apt install libzbar0t64) and the pyzbar package."
    )


# ------------------------------------------------------------ the builders --
#
# A builder is a list of steps. Each step names a field, asks for it, and
# optionally offers fixed choices or the option to skip. Progress lives in
# SQLite, so an unfinished code is still waiting after a restart.

BUILDERS = {
    "wifi": {
        "label": "WiFi code",
        "done": "Scanning this joins the network without anyone reading out "
                "the password.",
        "steps": [
            {
                "key": "ssid",
                "prompt": "<b>WiFi code, step 1 of 4</b>\n\nWhat is the network "
                          "name? Type it exactly as it appears, capitals and all.",
            },
            {
                "key": "security",
                "prompt": "<b>Step 2 of 4</b>\n\nWhich security does it use? "
                          "WPA covers WPA and WPA2, and is the right answer "
                          "for almost every network.",
                "choices": [
                    ("WPA", "WPA"), ("WPA3", "WPA3"),
                    ("WEP", "WEP"), ("Open", "nopass"),
                ],
            },
            {
                "key": "password",
                "prompt": "<b>Step 3 of 4</b>\n\nWhat is the password?",
                "optional": True,
                "skip_if": lambda data: data.get("security") == "nopass",
                "sensitive": True,
            },
            {
                "key": "hidden",
                "prompt": "<b>Step 4 of 4</b>\n\nIs the network hidden, meaning "
                          "it does not broadcast its name?",
                "choices": [("No", "false"), ("Yes", "true")],
            },
        ],
    },
    "contact": {
        "label": "contact card",
        "done": "Scanning this offers to save the contact straight to a phone.",
        "steps": [
            {"key": "first", "prompt": "<b>Contact card, step 1 of 6</b>\n\n"
                                       "What is the first name?"},
            {"key": "last", "prompt": "<b>Step 2 of 6</b>\n\nAnd the surname?",
             "optional": True},
            {"key": "phone", "prompt": "<b>Step 3 of 6</b>\n\nPhone number, "
                                       "with the country code if it matters.",
             "optional": True},
            {"key": "email", "prompt": "<b>Step 4 of 6</b>\n\nEmail address.",
             "optional": True},
            {"key": "org", "prompt": "<b>Step 5 of 6</b>\n\nCompany or "
                                     "organisation.", "optional": True},
            {"key": "url", "prompt": "<b>Step 6 of 6</b>\n\nWebsite.",
             "optional": True},
        ],
    },
    "event": {
        "label": "calendar event",
        "done": "Scanning this offers to drop the event into a calendar.",
        "steps": [
            {"key": "title", "prompt": "<b>Calendar event, step 1 of 5</b>\n\n"
                                       "What is the event called?"},
            {
                "key": "start",
                "prompt": "<b>Step 2 of 5</b>\n\nWhen does it start? Use "
                          "<code>YYYY-MM-DD HH:MM</code>, for example "
                          "<code>2026-12-24 19:30</code>.",
                "optional": True,
            },
            {
                "key": "end",
                "prompt": "<b>Step 3 of 5</b>\n\nAnd when does it end? Same "
                          "format again.",
                "optional": True,
            },
            {"key": "location", "prompt": "<b>Step 4 of 5</b>\n\nWhere is it?",
             "optional": True},
            {"key": "description", "prompt": "<b>Step 5 of 5</b>\n\nAnything "
                                             "else worth noting?", "optional": True},
        ],
    },
}


for _name, _spec in BUILDERS.items():
    dispatch.name_flow(_name, _spec["label"])


def _build_payload(flow: str, data: dict) -> str:
    if flow == "wifi":
        return qrgen.build_wifi(
            ssid=data.get("ssid", ""),
            password=data.get("password", ""),
            security=data.get("security", "WPA"),
            hidden=data.get("hidden") == "true",
        )
    if flow == "contact":
        return qrgen.build_vcard(
            first=data.get("first", ""), last=data.get("last", ""),
            phone=data.get("phone", ""), email=data.get("email", ""),
            org=data.get("org", ""), url=data.get("url", ""),
        )
    if flow == "event":
        return qrgen.build_event(
            title=data.get("title", ""), start=data.get("start", ""),
            end=data.get("end", ""), location=data.get("location", ""),
            description=data.get("description", ""),
        )
    raise ValueError(f"Unknown builder {flow!r}")


def _step_index(flow: str, key: str) -> int:
    for index, step in enumerate(BUILDERS[flow]["steps"]):
        if step["key"] == key:
            return index
    return 0


# ------------------------------------------------------------- registration --


def register(client) -> None:

    @client.on(events.NewMessage(
        pattern=dispatch.command("qr", "gen", "generate"), func=dispatch.private
    ))
    async def on_qr(event):
        content = dispatch.argument(event)
        if not content:
            await ui.reply_rich(
                event,
                "Put the content on the same line, like "
                "<code>/qr https://qr.uwuapps.org</code>. In a private chat you "
                "can also just send the text on its own.\n"
                "\n"
                "For the shapes with several fields use /wifi, /contact or /event.",
            )
            raise events.StopPropagation
        await deliver_code(event.client, event.chat_id, event.sender_id, content)
        raise events.StopPropagation

    @client.on(events.NewMessage(
        pattern=dispatch.command("wifi"), func=dispatch.private
    ))
    async def on_wifi(event):
        await _begin_builder(event, "wifi")
        raise events.StopPropagation

    @client.on(events.NewMessage(
        pattern=dispatch.command("contact", "vcard"), func=dispatch.private
    ))
    async def on_contact(event):
        await _begin_builder(event, "contact")
        raise events.StopPropagation

    @client.on(events.NewMessage(
        pattern=dispatch.command("event", "calendar"), func=dispatch.private
    ))
    async def on_event(event):
        await _begin_builder(event, "event")
        raise events.StopPropagation

    @client.on(events.NewMessage(
        pattern=dispatch.command("decode", "read", "scan"), func=dispatch.private
    ))
    async def on_decode(event):
        if event.is_reply:
            replied = await event.get_reply_message()
            if replied and replied.media:
                await _decode_message(event.client, event.chat_id, replied)
                raise events.StopPropagation
        await ui.reply_rich(
            event,
            "<b>Reading a code</b>\n"
            "\n"
            "Send me a photo or an image file with a QR code in it and I will "
            "read it back as text. You can also reply to an image with this "
            "command.\n"
            "\n"
            "Sharp and square works best. A screenshot beats a photo taken at "
            "an angle."
            + ("" if DECODING_AVAILABLE else
               "\n\nReading is switched off on this instance, because the zbar "
               "library is not installed."),
        )
        raise events.StopPropagation

    # A guided builder in progress swallows plain text before anything else.
    @client.on(events.NewMessage(
        func=lambda e: dispatch.private(e) and bool(e.raw_text)
    ))
    async def on_flow_text(event):
        if event.raw_text.startswith(("/", "!")):
            return
        flow = await db.get_flow(event.sender_id)
        if not flow:
            return
        await _advance(event.client, event.chat_id, event.sender_id,
                       flow, event.raw_text.strip())
        raise events.StopPropagation

    # Anything else typed into a private chat becomes a code.
    @client.on(events.NewMessage(
        func=lambda e: dispatch.private(e) and bool(e.raw_text)
    ))
    async def on_plain_text(event):
        if event.raw_text.startswith(("/", "!")):
            return
        await deliver_code(event.client, event.chat_id, event.sender_id,
                           event.raw_text.strip())
        raise events.StopPropagation

    @client.on(events.NewMessage(
        func=lambda e: dispatch.private(e) and (bool(e.photo) or _is_image_doc(e))
    ))
    async def on_image(event):
        await _decode_message(event.client, event.chat_id, event.message)
        raise events.StopPropagation

    @client.on(events.InlineQuery)
    async def on_inline(event):
        await _answer_inline(event)


def _is_image_doc(event) -> bool:
    document = getattr(event, "document", None)
    if document is None:
        return False
    mime = getattr(document, "mime_type", "") or ""
    return mime.startswith("image/")


# ------------------------------------------------------------- delivering ---


async def deliver_code(client, chat_id: int, sender_id: int, content: str,
                       *, kind: str | None = None, note: str = "") -> None:
    """Render one payload and send it with the buttons that go with it."""
    if not await db.allow(sender_id, "generate", RATE_LIMIT_MAX, RATE_LIMIT_WINDOW):
        await ui.send_rich(client, chat_id, ui.RATE_LIMITED)
        return

    if len(content) > MAX_PAYLOAD_CHARS:
        await ui.send_rich(
            client, chat_id,
            f"That is {len(content)} characters, and a QR code stops being "
            f"readable long before {MAX_PAYLOAD_CHARS}. Shorten it, or put it "
            "behind a link and encode the link instead.",
        )
        return

    kind = kind or qrgen.detect_kind(content)
    if kind == "url":
        content = qrgen.build_url(content)

    prefs = await db.get_prefs(sender_id)
    try:
        png = await _render(content, prefs)
    except Exception:  # noqa: BLE001 - report the failure rather than dying
        log.exception("Could not render a code.")
        await ui.send_rich(
            client, chat_id,
            "That content would not fit into a readable code. Try something "
            "shorter, or lower the error correction with /settings.",
        )
        return

    history_id = await db.add_history(sender_id, kind, content)

    # Save is offered whether or not there is an account behind it. Without one
    # the code waits in this chat's own list and moves across on the first
    # /link, so there is never a moment where saving is the wrong thing to do.
    buttons_row = [
        await ui.inline_button("Show the data", "show_data",
                               {"h": history_id}, owner_id=sender_id),
        await ui.inline_button("Save", "save_code",
                               {"h": history_id}, owner_id=sender_id),
    ]

    caption = (
        f"<b>{ui.esc(qrgen.KIND_LABELS.get(kind, 'Code'))}</b>\n"
        f"{ui.esc(qrgen.describe(content))}\n"
        f"<i>{prefs['size']} px, error correction {ui.esc(prefs['ec'])}</i>"
    )
    if note:
        caption += f"\n\n{note}"

    await ui.send_rich(
        client, chat_id, caption,
        file=qrgen.to_upload(png, f"qr-{kind}.png"),
        buttons=ui.keyboard(buttons_row),
    )


async def _render(content: str, prefs: dict) -> bytes:
    return await asyncio.to_thread(qrgen.render_with_prefs, content, prefs)


# ---------------------------------------------------------------- builders --


async def _begin_builder(event, flow: str) -> None:
    if not event.is_private:
        await ui.reply_rich(
            event,
            "The step by step builders only run in a private chat, so nobody "
            "else sees the answers. Message me directly and start it there.",
        )
        return

    await db.set_flow(event.sender_id, flow, BUILDERS[flow]["steps"][0]["key"],
                      {}, event.chat_id)
    await _ask(event.client, event.chat_id, event.sender_id, flow, 0, {})


async def _ask(client, chat_id: int, sender_id: int, flow: str, index: int,
               data: dict) -> None:
    step = BUILDERS[flow]["steps"][index]
    rows = []

    if step.get("choices"):
        rows.append([
            await ui.inline_button(
                label, "flow_choice",
                {"flow": flow, "key": step["key"], "value": value},
                owner_id=sender_id,
            )
            for label, value in step["choices"]
        ])
    if step.get("optional"):
        rows.append(ui.row(
            await ui.inline_button(
                "Skip", "flow_skip", {"flow": flow, "key": step["key"]},
                owner_id=sender_id,
            )
        ))
    rows.append(ui.row(
        await ui.inline_button("Cancel", "flow_cancel", owner_id=sender_id)
    ))

    prompt = step["prompt"]
    if step.get("sensitive"):
        prompt += ("\n\nIt is only used to build the code. Nothing is stored "
                   "once the code is sent.")

    await ui.send_rich(client, chat_id, prompt, buttons=ui.keyboard(*rows))


async def _advance(client, chat_id: int, sender_id: int, flow_row: dict,
                   value: str) -> None:
    flow = flow_row["flow"]
    if flow not in BUILDERS:
        # Not a builder, so it belongs to whichever module registered it. Only
        # a flow left behind by an older version reaches the clear below.
        handler = dispatch.flow_handler(flow)
        if handler is None:
            await db.clear_flow(sender_id)
            return
        await handler(client, chat_id, sender_id, flow_row, value)
        return

    data = dict(flow_row["data"])
    index = _step_index(flow, flow_row["step"])
    data[BUILDERS[flow]["steps"][index]["key"]] = value
    await _continue_from(client, chat_id, sender_id, flow, index + 1, data)


async def _continue_from(client, chat_id: int, sender_id: int, flow: str,
                         index: int, data: dict) -> None:
    steps = BUILDERS[flow]["steps"]

    while index < len(steps):
        skip_if = steps[index].get("skip_if")
        if skip_if and skip_if(data):
            data[steps[index]["key"]] = ""
            index += 1
            continue
        break

    if index >= len(steps):
        await db.clear_flow(sender_id)
        try:
            payload = _build_payload(flow, data)
        except ValueError:
            await ui.send_rich(client, chat_id, "That builder is not available.")
            return
        if not payload:
            await ui.send_rich(
                client, chat_id,
                "There was not enough there to build a code. Start again when "
                "you have the details to hand.",
            )
            return
        kind = {"wifi": "wifi", "contact": "contact", "event": "calendar"}[flow]
        await deliver_code(client, chat_id, sender_id, payload, kind=kind,
                           note=BUILDERS[flow]["done"])
        return

    await db.set_flow(sender_id, flow, steps[index]["key"], data, chat_id)
    await _ask(client, chat_id, sender_id, flow, index, data)


# ---------------------------------------------------------------- decoding --


async def _decode_message(client, chat_id: int, message) -> None:
    if not DECODING_AVAILABLE:
        await ui.send_rich(
            client, chat_id,
            "Reading codes is switched off on this instance, because the zbar "
            "library is not installed. Generating still works.",
        )
        return

    blob = await message.download_media(file=bytes)
    if not blob:
        await ui.send_rich(client, chat_id, "That image would not download.")
        return

    results = await asyncio.to_thread(_decode_bytes, blob)
    if not results:
        await ui.send_rich(
            client, chat_id,
            "No code found in that image. A flat, square, well lit shot reads "
            "best, and a screenshot beats a photo taken at an angle.",
        )
        return

    for payload in results[:5]:
        kind = qrgen.detect_kind(payload)
        shown = payload if len(payload) <= 1200 else payload[:1200] + "\n..."
        buttons = ui.keyboard(ui.row(
            await ui.inline_button(
                "Rebuild it as a code", "rebuild",
                {"h": await db.add_history(message.sender_id or 0, kind, payload)},
                owner_id=message.sender_id,
            )
        ))
        await ui.send_rich(
            client, chat_id,
            f"<b>{ui.esc(qrgen.KIND_LABELS.get(kind, 'Code'))}</b>\n"
            f"<pre>{ui.esc(shown)}</pre>",
            buttons=buttons,
        )

    if len(results) > 5:
        await ui.send_rich(
            client, chat_id,
            f"That image held {len(results)} codes. The first five are above.",
        )


def _decode_bytes(blob: bytes) -> list[str]:
    """Read every code in an image, retrying once at double size."""
    try:
        image = Image.open(io.BytesIO(blob))
    except Exception:  # noqa: BLE001
        return []

    image = image.convert("L")
    found = pyzbar.decode(image)
    if not found and max(image.size) < 2000:
        doubled = image.resize((image.width * 2, image.height * 2), Image.LANCZOS)
        found = pyzbar.decode(doubled)

    payloads = []
    for item in found:
        try:
            payloads.append(item.data.decode("utf-8"))
        except UnicodeDecodeError:
            payloads.append(item.data.decode("latin-1", errors="replace"))
    return payloads


# ------------------------------------------------------------------ inline --


async def _answer_inline(event) -> None:
    query = (event.text or "").strip()
    builder = event.builder

    if not query:
        await event.answer(
            [],
            switch_pm="Type something to turn it into a code",
            switch_pm_param="inline",
        )
        return

    if len(query) > MAX_PAYLOAD_CHARS:
        await event.answer([])
        return

    prefs = await db.get_prefs(event.sender_id)
    kind = qrgen.detect_kind(query)
    content = qrgen.build_url(query) if kind == "url" else query

    try:
        png = await _render(content, prefs)
    except Exception:  # noqa: BLE001
        await event.answer([])
        return

    caption = f"<b>{ui.esc(qrgen.KIND_LABELS.get(kind, 'Code'))}</b>\n{ui.esc(content[:200])}"
    try:
        result = await builder.photo(
            file=qrgen.to_upload(png, "qr.png"),
            text=caption,
            parse_mode="html",
        )
        await event.answer([result], cache_time=1)
    except Exception:  # noqa: BLE001 - photo results can fail, text still works
        log.debug("Inline photo result failed, answering with text.", exc_info=True)
        await event.answer([
            await builder.article(
                title="Send this as a code",
                description=content[:80],
                text=caption,
                parse_mode="html",
            )
        ], cache_time=1)


# --------------------------------------------------------------- callbacks --


@dispatch.on("flow_choice")
async def _cb_flow_choice(event, button):
    payload = button["payload"]
    flow_row = await db.get_flow(event.sender_id)
    if not flow_row or flow_row["flow"] != payload["flow"]:
        await event.answer("That builder is no longer running.", alert=True)
        return

    await event.answer()
    data = dict(flow_row["data"])
    data[payload["key"]] = payload["value"]
    index = _step_index(payload["flow"], payload["key"])
    await _continue_from(event.client, event.chat_id, event.sender_id,
                         payload["flow"], index + 1, data)


@dispatch.on("flow_skip")
async def _cb_flow_skip(event, button):
    payload = button["payload"]
    flow_row = await db.get_flow(event.sender_id)
    if not flow_row or flow_row["flow"] != payload["flow"]:
        await event.answer("That builder is no longer running.", alert=True)
        return

    await event.answer("Skipped.")
    data = dict(flow_row["data"])
    data[payload["key"]] = ""
    index = _step_index(payload["flow"], payload["key"])
    await _continue_from(event.client, event.chat_id, event.sender_id,
                         payload["flow"], index + 1, data)


@dispatch.on("flow_cancel")
async def _cb_flow_cancel(event, button):
    await db.clear_flow(event.sender_id)
    await event.answer("Cancelled.")
    await ui.edit_rich(
        await event.get_message(),
        "Builder cancelled. Nothing was kept.",
    )


@dispatch.on("show_data")
async def _cb_show_data(event, button):
    row = await db.get_history(button["payload"]["h"])
    if not row:
        await event.answer("That content is no longer in the local history.",
                           alert=True)
        return
    await event.answer()
    payload = row["payload"]
    shown = payload if len(payload) <= 3000 else payload[:3000] + "\n..."
    await ui.send_rich(
        event.client, event.chat_id,
        f"<b>What that code contains</b>\n<pre>{ui.esc(shown)}</pre>",
    )


@dispatch.on("rebuild")
async def _cb_rebuild(event, button):
    row = await db.get_history(button["payload"]["h"])
    if not row:
        await event.answer("That content is no longer in the local history.",
                           alert=True)
        return
    await event.answer("Rebuilding.")
    await deliver_code(event.client, event.chat_id, event.sender_id,
                       row["payload"], kind=row["kind"])
