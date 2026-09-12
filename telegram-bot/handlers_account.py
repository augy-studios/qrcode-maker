"""The codes saved on a portal account, the ones waiting for one, and the
rendering preferences.

Saving works whether or not there is an account behind it. With a link the code
goes straight to the portal; without one it stays in the local favourites table
and /saved lists that instead. The two become one list the moment a link is
made: merge_favourites walks what the chat is holding, skips anything the
account already has, uploads the rest, and empties the local table. Nothing is
ever in both places afterwards, and nothing is lost by connecting late.

The settings command is local to the chat throughout, and works whether or not
the portal is reachable.
"""

import asyncio
import logging
import time

import db
import dispatch
import linking
import qrgen
import reply
import supa
import ui
from reply import escape_md
from config import (
    COLOUR_PRESETS,
    EC_STEPS,
    FAVOURITES_MAX,
    MARGIN_STEPS,
    SAVED_PAGE_SIZE,
    SIZE_STEPS,
    TABLE_CODES,
    WATERMARK_TEXT,
    WATERMARK_TEXT_MAX,
    WATERMARK_TEXT_ROOMY,
)
from telethon import events

log = logging.getLogger(__name__)


def register(client) -> None:

    @client.on(events.NewMessage(
        pattern=dispatch.command("saved", "myqrs", "list"), func=dispatch.private
    ))
    async def on_saved(event):
        link = None
        if supa.enabled():
            link = await linking.link_for_telegram(event.sender_id)
        if not link:
            # No account to read from, so show what this chat is holding on its
            # own. It is the same list, just waiting for somewhere to go.
            await _show_favourites(event.client, event.chat_id, event.sender_id)
            raise events.StopPropagation
        await _show_page(event.client, event.chat_id, event.sender_id,
                         link["user_id"], 0)
        raise events.StopPropagation

    @client.on(events.NewMessage(
        pattern=dispatch.command("settings", "prefs"), func=dispatch.private
    ))
    async def on_settings(event):
        await _show_settings(event.client, event.chat_id, event.sender_id)
        raise events.StopPropagation

    @client.on(events.NewMessage(
        pattern=dispatch.command("watermark", "mark"), func=dispatch.private
    ))
    async def on_watermark(event):
        typed = dispatch.argument(event)
        if typed:
            await _apply_watermark_text(
                event.client, event.chat_id, event.sender_id, typed
            )
            raise events.StopPropagation
        await _ask_watermark_text(event.client, event.chat_id, event.sender_id)
        raise events.StopPropagation


# ------------------------------------------------------------ saved codes ---
#
# One rich message, two ways of drawing it. The text mode is the numbered list;
# the image mode is the same list with each code's picture under its number,
# which Rich Markdown allows as a media block of its own. Send these as images
# therefore edits the message in place rather than sending anything, and the
# mode rides in every button's payload so paging and deleting keep it.


SAVED_COLUMNS = "id,type,data_preview,qr_data,image_url,created_at"


def _point_markdown(number: int, row: dict, with_image: bool) -> str:
    """One numbered entry, with its picture underneath in image mode."""
    label = qrgen.KIND_LABELS.get(row.get("type") or "", "Code")
    preview = (row.get("data_preview") or "").strip() or "no preview"
    stamp = (row.get("created_at") or "")[:10]
    text = (
        f"**{number}.** {escape_md(label)}, saved {escape_md(stamp)}\n"
        f"{escape_md(preview[:70])}"
    )
    if with_image and row.get("image_url"):
        text += f"\n\n![{number}]({row['image_url']})"
    return text


async def _point_buttons(number: int, row: dict, page: int, sender_id: int,
                         images: bool) -> list:
    """Open and Delete for one entry. Open lands in the portal's editor with
    the code filled in."""
    return ui.row(
        ui.open_button(f"Open {number}", row.get("type") or "",
                       row.get("qr_data") or "", row.get("image_url")),
        await ui.inline_button(
            f"Delete {number}", "saved_delete_ask",
            {"id": row["id"], "page": page, "n": number, "images": images},
            owner_id=sender_id,
        ),
    )


async def _page_rows(user_id: str, page: int) -> list[dict]:
    return await supa.select(
        TABLE_CODES,
        {"user_id": f"eq.{user_id}"},
        columns=SAVED_COLUMNS,
        order="created_at.desc",
        limit=SAVED_PAGE_SIZE,
        offset=page * SAVED_PAGE_SIZE,
    )


def _waiting_note(waiting: int) -> str:
    if not waiting:
        return ""
    return (
        f"{waiting} {'code' if waiting == 1 else 'codes'} saved in this "
        "chat never made it onto your account. They are still here."
    )


async def _page_footer(page: int, pages: int, sender_id: int, waiting: int,
                       images: bool, any_rows: bool) -> list:
    """The rows under the entries: paging, the image toggle, the portal, and
    the retry for anything a link left behind."""
    rows = []
    nav = []
    if page > 0:
        nav.append(await ui.inline_button(
            "Previous", "saved_page", {"page": page - 1, "images": images},
            owner_id=sender_id))
    if page + 1 < pages:
        nav.append(await ui.inline_button(
            "Next", "saved_page", {"page": page + 1, "images": images},
            owner_id=sender_id))
    if nav:
        rows.append(nav)

    toggle = None
    if any_rows:
        toggle = await ui.inline_button(
            "Just the list" if images else "Send these as images",
            "saved_page", {"page": page, "images": not images},
            owner_id=sender_id,
        )
    rows.append(ui.row(toggle, ui.portal_button("On the web")))

    if waiting:
        rows.append(ui.row(
            await ui.inline_button(
                f"Move {waiting} waiting {'code' if waiting == 1 else 'codes'} across",
                "fav_merge", {"page": page, "images": images}, owner_id=sender_id),
        ))
    return rows


async def build_saved_page(sender_id: int, user_id: str, page: int,
                           images: bool = False):
    """The saved list as (rich, buttons). Raises SupabaseError if the portal
    is out, so the caller can say so.

    Text mode and image mode are the same page; only the entries differ.
    """
    total = await supa.count(TABLE_CODES, {"user_id": f"eq.{user_id}"})
    rows = await _page_rows(user_id, page)

    # Normally empty: the merge runs at link time and clears it. Anything still
    # here is a code the portal would not take, so the way to retry has to be
    # somewhere the owner will actually look.
    waiting = await db.count_favourites(sender_id)

    if total == 0 and not waiting:
        return ui.rich(
            "# Nothing saved yet\n"
            "\n"
            "Generate a code here and press Save, or save one from the portal. "
            "They all land in the same place."
        ), ui.keyboard(ui.row(ui.portal_button()))

    pages = max(1, -(-total // SAVED_PAGE_SIZE))
    page = max(0, min(page, pages - 1))
    first = page * SAVED_PAGE_SIZE

    parts = [
        "# Your saved codes\n"
        + (f"Page {page + 1} of {pages}, {total} in total." if total else
           "Nothing on the account yet.")
    ]
    keyboard_rows = []
    for offset, row in enumerate(rows, start=1):
        number = first + offset
        parts.append(_point_markdown(number, row, images))
        keyboard_rows.append(await _point_buttons(number, row, page, sender_id, images))

    if waiting:
        parts.append(_waiting_note(waiting))
    keyboard_rows += await _page_footer(page, pages, sender_id, waiting, images,
                                        any_rows=bool(rows))

    return ui.rich("\n\n".join(parts)), ui.keyboard(*keyboard_rows)


async def _show_page(client, chat_id: int, sender_id: int, user_id: str,
                     page: int, message=None, images: bool = False) -> None:
    try:
        rich, buttons = await build_saved_page(sender_id, user_id, page, images)
    except supa.SupabaseError:
        log.exception("Could not read the saved codes.")
        await ui.send_rich(
            client, chat_id,
            "The portal is not answering right now. Try again shortly.",
        )
        return

    if message is not None:
        await ui.edit_rich(message, rich=rich, buttons=buttons)
    else:
        await ui.send_rich(client, chat_id, rich=rich, buttons=buttons)


@dispatch.on("saved_page")
async def _cb_saved_page(event, button):
    """Paging and the image toggle, which are the same redraw."""
    link = await linking.link_for_telegram(event.sender_id)
    if not link:
        await event.answer("This chat is not connected.", alert=True)
        return
    payload = button["payload"]
    await event.answer("Loading the pictures." if payload.get("images") else None)
    await _show_page(event.client, event.chat_id, event.sender_id,
                     link["user_id"], int(payload.get("page", 0)),
                     message=await event.get_message(),
                     images=bool(payload.get("images")))


@dispatch.on("saved_delete_ask")
async def _cb_saved_delete_ask(event, button):
    payload = button["payload"]
    await event.answer()
    back = {"page": payload.get("page", 0), "images": payload.get("images", False)}
    buttons = ui.keyboard(ui.row(
        await ui.inline_button(
            "Delete it", "saved_delete", payload, owner_id=event.sender_id),
        await ui.inline_button(
            "Keep it", "saved_back", back, owner_id=event.sender_id),
    ))
    await ui.edit_rich(
        await event.get_message(),
        rich=ui.rich(
            f"# Delete code {payload.get('n', '')}?\n"
            "\n"
            "The image and the record both go, on the portal as well as here. "
            "There is no undo."
        ),
        buttons=buttons,
    )


@dispatch.on("saved_delete")
async def _cb_saved_delete(event, button):
    link = await linking.link_for_telegram(event.sender_id)
    if not link:
        await event.answer("This chat is not connected.", alert=True)
        return

    payload = button["payload"]
    row = await supa.select_one(
        TABLE_CODES, {"id": f"eq.{payload['id']}"}, columns="id,user_id,image_path"
    )
    if row is None or row["user_id"] != link["user_id"]:
        await event.answer("That code is not yours, or it is already gone.",
                           alert=True)
        return

    if row.get("image_path"):
        await supa.remove([row["image_path"]])
    await supa.delete(TABLE_CODES, {"id": f"eq.{payload['id']}"})

    await event.answer("Deleted.")
    await _show_page(event.client, event.chat_id, event.sender_id,
                     link["user_id"], int(payload.get("page", 0)),
                     message=await event.get_message(),
                     images=bool(payload.get("images")))


@dispatch.on("saved_back")
async def _cb_saved_back(event, button):
    link = await linking.link_for_telegram(event.sender_id)
    if not link:
        await event.answer("This chat is not connected.", alert=True)
        return
    await event.answer("Kept.")
    payload = button["payload"]
    await _show_page(event.client, event.chat_id, event.sender_id,
                     link["user_id"], int(payload.get("page", 0)),
                     message=await event.get_message(),
                     images=bool(payload.get("images")))


# -------------------------------------------------------------- saving one --


@dispatch.on("save_code")
async def _cb_save_code(event, button):
    row = await db.get_history(button["payload"]["h"])
    if not row:
        await event.answer("That code is no longer in the local history.",
                           alert=True)
        return

    link = None
    if supa.enabled():
        link = await linking.link_for_telegram(event.sender_id)
    if not link:
        await _save_favourite(event, row)
        return

    await event.answer("Saving.")
    prefs = await db.get_prefs(event.sender_id)
    try:
        png = await asyncio.to_thread(qrgen.render_with_prefs, row["payload"], prefs)
        path = f"{link['user_id']}/{int(time.time() * 1000)}.png"
        image_url = await supa.upload(path, png)
        await supa.insert(TABLE_CODES, {
            "user_id": link["user_id"],
            "type": row["kind"],
            "qr_data": row["payload"],
            "data_preview": row["payload"][:80],
            "image_path": path,
            "image_url": image_url,
        })
    except Exception:  # noqa: BLE001 - tell the user rather than swallowing it
        log.exception("Could not save a code to the portal.")
        await ui.send_rich(
            event.client, event.chat_id,
            "The save did not go through. The portal may be having a moment, "
            "so try again shortly.",
        )
        return

    username = (link.get("qr_users") or {}).get("username") or "your account"
    await ui.send_rich(
        event.client, event.chat_id,
        f"<b>Saved</b>\n\nThat code is now on {ui.esc(username)}. It shows up "
        "under My QRs on the portal and in /saved here.",
        buttons=ui.keyboard(ui.row(ui.portal_button("Open My QRs"))),
    )


# ------------------------------------------------------------- favourites --
#
# The same Save button, pressed by a chat that has nowhere to put it yet. The
# payload is kept and nothing else: the image is redrawn at merge time, from
# whatever the settings say then, so a code saved today does not arrive on the
# account in last month's colours.


async def _save_favourite(event, row: dict) -> None:
    try:
        added = await db.add_favourite(event.sender_id, row["kind"], row["payload"])
    except db.FavouritesFull:
        await event.answer("This chat is full.", alert=True)
        await ui.send_rich(
            event.client, event.chat_id,
            f"<b>That is {FAVOURITES_MAX} codes waiting</b>\n"
            "\n"
            "This chat can hold that many without an account behind it. Connect "
            "one with /link and the lot moves across, which clears the room, or "
            "drop a few with /saved."
            + ("" if supa.enabled() else
               "\n\nAccount features are switched off on this instance, so /link "
               "will not help here. Dropping a few is the only way on."),
            buttons=ui.keyboard(ui.row(ui.portal_button())),
        )
        return

    if not added:
        await event.answer("Already saved here.")
        return

    held = await db.count_favourites(event.sender_id)
    await event.answer("Saved to this chat.")

    if not supa.enabled():
        await ui.send_rich(
            event.client, event.chat_id,
            f"<b>Kept here</b>\n"
            "\n"
            f"That code is in this chat's list, {held} in total. /saved brings "
            "them all back.",
        )
        return

    await ui.send_rich(
        event.client, event.chat_id,
        f"<b>Kept here for now</b>\n"
        "\n"
        f"This chat is not connected to a portal account, so that code is "
        f"waiting in /saved instead. {held} in total.\n"
        "\n"
        "Connect an account with /link and every one of them moves across by "
        "itself, joining whatever is already there. Nothing gets saved twice.",
        buttons=ui.keyboard(ui.row(
            await ui.inline_button("Connect my account", "start_link",
                                   owner_id=event.sender_id),
        )),
    )


async def _show_favourites(client, chat_id: int, sender_id: int,
                           message=None) -> None:
    rows = await db.list_favourites(sender_id)

    if not rows:
        await ui.send_rich(
            client, chat_id,
            "<b>Nothing saved yet</b>\n"
            "\n"
            "Generate a code here and press Save, and it lands in this list."
            + ("" if not supa.enabled() else
               "\n\nThis chat is not connected to a portal account. It does not "
               "have to be: anything saved here waits until it is, then moves "
               "across on its own. /link does that whenever you are ready."),
            buttons=ui.keyboard(ui.row(ui.portal_button())) if supa.enabled() else None,
        )
        return

    rich, buttons = await build_favourites(rows, sender_id)
    if message is not None:
        await ui.edit_rich(message, rich=rich, buttons=buttons)
    else:
        await ui.send_rich(client, chat_id, rich=rich, buttons=buttons)


async def build_favourites(rows: list[dict], sender_id: int):
    """The chat-held list as (rich, buttons). No pictures: only the payload
    is kept here, and it is drawn fresh on the way to the account."""
    parts = [
        f"# Saved in this chat\n{len(rows)} "
        f"{'code' if len(rows) == 1 else 'codes'}, newest last."
    ]
    keyboard_rows = []
    for number, row in enumerate(rows, start=1):
        label = qrgen.KIND_LABELS.get(row["kind"], "Code")
        parts.append(
            f"**{number}.** {escape_md(label)}\n"
            f"{escape_md(qrgen.describe(row['payload'])[:70])}"
        )
        keyboard_rows.append([
            await ui.inline_button(
                f"Send {number}", "fav_send", {"id": row["id"]},
                owner_id=sender_id),
            await ui.inline_button(
                f"Delete {number}", "fav_delete", {"id": row["id"]},
                owner_id=sender_id),
        ])

    if supa.enabled():
        parts.append(
            "These live in this chat alone. Connect a portal account and they "
            "move onto it, skipping anything it already has."
        )
        keyboard_rows.append(ui.row(
            await ui.inline_button("Connect my account", "start_link",
                                   owner_id=sender_id),
        ))

    return ui.rich("\n\n".join(parts)), ui.keyboard(*keyboard_rows)


@dispatch.on("fav_send")
async def _cb_fav_send(event, button):
    row = await db.get_favourite(event.sender_id, button["payload"]["id"])
    if not row:
        await event.answer("That one is gone.", alert=True)
        return
    await event.answer()
    from handlers_qr import deliver_code

    await deliver_code(event.client, event.chat_id, event.sender_id,
                       row["payload"], kind=row["kind"])


@dispatch.on("fav_merge")
async def _cb_fav_merge(event, button):
    """Retry the hand over, for codes a link left behind."""
    link = await linking.link_for_telegram(event.sender_id)
    if not link:
        await event.answer("This chat is not connected.", alert=True)
        return
    await event.answer("Moving them.")
    await merge_favourites(event.client, event.sender_id, link["user_id"])
    payload = button["payload"]
    await _show_page(event.client, event.chat_id, event.sender_id,
                     link["user_id"], int(payload.get("page", 0)),
                     message=await event.get_message(),
                     images=bool(payload.get("images")))


@dispatch.on("fav_delete")
async def _cb_fav_delete(event, button):
    removed = await db.delete_favourite(event.sender_id, button["payload"]["id"])
    await event.answer("Deleted." if removed else "Already gone.")
    await _show_favourites(event.client, event.chat_id, event.sender_id,
                           message=await event.get_message())


# ------------------------------------------------------------- the merge ---


async def merge_favourites(client, telegram_id: int, user_id: str) -> None:
    """Move what this chat is holding onto the account it has just joined.

    Called once per link, from whichever half of the handshake finished it. It
    is deliberately quiet when there is nothing to move, because most links have
    nothing waiting and a report saying so is noise on top of the welcome.

    Duplicates are decided on the payload, which is the only thing both sides
    are guaranteed to agree on: the same WiFi network saved here and on the
    portal encodes byte for byte the same string, because qrgen's builders
    mirror the portal's. A row that matches is dropped rather than uploaded, so
    connecting late costs a second copy of nothing.
    """
    rows = await db.list_favourites(telegram_id)
    if not rows:
        return

    try:
        existing = await _account_payloads(user_id)
    except supa.SupabaseError:
        log.exception("Could not read the account before merging favourites.")
        waiting = "code" if len(rows) == 1 else "codes"
        await ui.send_rich(
            client, telegram_id,
            "<b>Your saved codes are still here</b>\n"
            "\n"
            f"The {len(rows)} {waiting} waiting in this chat could not be moved "
            "onto your account just now, because the portal did not answer. "
            "Nothing has been lost.\n"
            "\n"
            "/saved has a button to try the move again once the portal is "
            "answering.",
        )
        return

    prefs = await db.get_prefs(telegram_id)
    moved, duplicates, failed = 0, 0, 0

    for row in rows:
        if row["payload"] in existing:
            await db.delete_favourite(telegram_id, row["id"])
            duplicates += 1
            continue
        try:
            await _upload_one(user_id, row, prefs)
        except Exception:  # noqa: BLE001 - one bad code must not strand the rest
            log.exception("Could not merge favourite %s.", row["id"])
            failed += 1
            continue
        existing.add(row["payload"])
        await db.delete_favourite(telegram_id, row["id"])
        moved += 1

    await ui.send_rich(
        client, telegram_id, _merge_report(moved, duplicates, failed),
        buttons=ui.keyboard(ui.row(ui.portal_button("Open My QRs"))),
    )


async def _account_payloads(user_id: str) -> set[str]:
    """Every payload already on the account, which is the duplicate check."""
    payloads: set[str] = set()
    page, page_size = 0, 200
    while True:
        rows = await supa.select(
            TABLE_CODES,
            {"user_id": f"eq.{user_id}"},
            columns="qr_data",
            order="created_at.asc",
            limit=page_size,
            offset=page * page_size,
        )
        payloads.update(row["qr_data"] for row in rows if row.get("qr_data"))
        if len(rows) < page_size:
            return payloads
        page += 1


async def _upload_one(user_id: str, row: dict, prefs: dict) -> None:
    png = await asyncio.to_thread(qrgen.render_with_prefs, row["payload"], prefs)
    path = f"{user_id}/{int(time.time() * 1000)}-{row['id']}.png"
    image_url = await supa.upload(path, png)
    await supa.insert(TABLE_CODES, {
        "user_id": user_id,
        "type": row["kind"],
        "qr_data": row["payload"],
        "data_preview": row["payload"][:80],
        "image_path": path,
        "image_url": image_url,
    })


def _merge_report(moved: int, duplicates: int, failed: int) -> str:
    """One message covering all three outcomes, in whatever mix happened."""
    def codes(n: int) -> str:
        return f"{n} code" if n == 1 else f"{n} codes"

    was = "was" if duplicates == 1 else "were"
    parts = []

    if moved:
        head = f"<b>{codes(moved)} moved across</b>"
        parts.append(
            ("It is" if moved == 1 else "They are")
            + " on your account now, alongside whatever was already there. "
            "/saved and My QRs show the same list from here on."
        )
        if duplicates:
            parts.append(
                f"{codes(duplicates)} {was} already there, so no second copy "
                "was made."
            )
    elif duplicates and not failed:
        head = "<b>Nothing new to move</b>"
        parts.append(
            f"{codes(duplicates)} waiting in this chat {was} already on your "
            "account, so there was nothing to add. /saved and My QRs show the "
            "same list from here on."
        )
    else:
        head = "<b>Nothing moved</b>"
        if duplicates:
            parts.append(
                f"{codes(duplicates)} {was} already on your account and needed "
                "nothing doing."
            )

    if failed:
        is_are = "is" if failed == 1 else "are"
        parts.append(
            f"{codes(failed)} would not upload and {is_are} still waiting here. "
            "/saved keeps a button for trying the move again."
        )

    return "\n\n".join([head, *parts])


# ---------------------------------------------------------------- settings --


def _next_in(sequence, current):
    values = list(sequence)
    try:
        return values[(values.index(current) + 1) % len(values)]
    except ValueError:
        return values[0]


def _colour_name(fg: str, bg: str) -> str:
    for name, preset_fg, preset_bg in COLOUR_PRESETS:
        if preset_fg.lower() == fg.lower() and preset_bg.lower() == bg.lower():
            return name
    return "Custom"


def _watermark_text_of(prefs: dict) -> str:
    return str(prefs.get("watermark_text") or WATERMARK_TEXT)


async def _show_settings(client, chat_id: int, sender_id: int, message=None) -> None:
    prefs = await db.get_prefs(sender_id)
    watermark_on = bool(prefs["watermark"])
    mark = _watermark_text_of(prefs)

    warning = ""
    if watermark_on and prefs["ec"] != "H":
        warning = (
            "\n\nThe watermark covers part of the symbol, and correction "
            f"{prefs['ec']} may not have the headroom to survive it. Level H is "
            "what the portal uses for exactly this reason."
        )
    if watermark_on and len(mark) > WATERMARK_TEXT_ROOMY:
        warning += (
            f"\n\nA {len(mark)} character mark is a wide hole in the middle of "
            "every code. It is drawn smaller so it cannot swallow the symbol, "
            "but do scan one before you print it."
        )

    body = ui.rich(
        "# Your defaults\n"
        "\n"
        + reply.table(["Setting"], [
            ["Size", f"{prefs['size']} px"],
            ["Quiet zone", f"{prefs['margin']} modules"],
            ["Error correction", prefs["ec"]],
            ["Watermark", "on" if watermark_on else "off"],
            ["The mark reads", mark],
            ["Colours", _colour_name(prefs["fg"], prefs["bg"])],
        ])
        + "\n\n"
        "These apply to everything generated in this chat, including inline "
        "results and anything you save to your account. Each button steps to "
        "the next option." + warning
    )

    buttons = ui.keyboard(
        ui.row(
            await ui.inline_button(f"Size {prefs['size']}", "pref_cycle",
                                   {"field": "size"}, owner_id=sender_id),
            await ui.inline_button(f"Margin {prefs['margin']}", "pref_cycle",
                                   {"field": "margin"}, owner_id=sender_id),
        ),
        ui.row(
            await ui.inline_button(f"Correction {prefs['ec']}", "pref_cycle",
                                   {"field": "ec"}, owner_id=sender_id),
            await ui.inline_button(
                f"Watermark {'on' if watermark_on else 'off'}", "pref_cycle",
                {"field": "watermark"}, owner_id=sender_id),
        ),
        ui.row(
            await ui.inline_button(f"Change the mark, {mark}", "wm_ask",
                                   owner_id=sender_id),
        ),
        ui.row(
            await ui.inline_button(
                f"Colours, {_colour_name(prefs['fg'], prefs['bg'])}",
                "pref_cycle", {"field": "colour"}, owner_id=sender_id),
        ),
        ui.row(
            await ui.inline_button("Back to the portal defaults", "pref_reset",
                                   owner_id=sender_id),
        ),
        ui.row(
            await ui.inline_button("Show me a sample", "pref_sample",
                                   owner_id=sender_id),
        ),
    )

    if message is not None:
        await ui.edit_rich(message, rich=body, buttons=buttons)
    else:
        await ui.send_rich(client, chat_id, rich=body, buttons=buttons)


@dispatch.on("pref_cycle")
async def _cb_pref_cycle(event, button):
    field = button["payload"]["field"]
    prefs = await db.get_prefs(event.sender_id)

    if field == "size":
        prefs["size"] = _next_in(SIZE_STEPS, prefs["size"])
    elif field == "margin":
        prefs["margin"] = _next_in(MARGIN_STEPS, prefs["margin"])
    elif field == "ec":
        prefs["ec"] = _next_in(EC_STEPS, prefs["ec"])
    elif field == "watermark":
        prefs["watermark"] = 0 if prefs["watermark"] else 1
    elif field == "colour":
        names = [name for name, _, _ in COLOUR_PRESETS]
        nxt = _next_in(names, _colour_name(prefs["fg"], prefs["bg"]))
        for name, fg, bg in COLOUR_PRESETS:
            if name == nxt:
                prefs["fg"], prefs["bg"] = fg, bg
                break

    await db.set_prefs(event.sender_id, prefs)
    await event.answer()
    await _show_settings(event.client, event.chat_id, event.sender_id,
                         message=await event.get_message())


@dispatch.on("pref_reset")
async def _cb_pref_reset(event, button):
    await db.reset_prefs(event.sender_id)
    await event.answer("Back to the defaults.")
    await _show_settings(event.client, event.chat_id, event.sender_id,
                         message=await event.get_message())


@dispatch.on("pref_sample")
async def _cb_pref_sample(event, button):
    await event.answer()
    from handlers_qr import deliver_code

    await deliver_code(
        event.client, event.chat_id, event.sender_id,
        "https://qr.uwuapps.org",
        note="A sample drawn with your current settings.",
    )


# ----------------------------------------------------------- the mark text --
#
# The portal always writes uwu in the middle. Here it is only where everyone
# starts. The text is asked for as one plain message rather than through a
# builder, because there is exactly one field and a one step wizard is worse
# than a question.


async def _ask_watermark_text(client, chat_id: int, sender_id: int) -> None:
    prefs = await db.get_prefs(sender_id)
    mark = _watermark_text_of(prefs)

    await db.set_flow(sender_id, "watermark", "text", {}, chat_id)

    off_note = ""
    if not prefs["watermark"]:
        off_note = (
            "\n\nThe mark is switched off at the moment, so nothing is drawn "
            "either way. Changing the text turns it back on."
        )

    rows = [
        ui.row(
            await ui.inline_button("Put uwu back", "wm_default",
                                   owner_id=sender_id),
        ),
        ui.row(
            await ui.inline_button("Cancel", "wm_cancel", owner_id=sender_id),
        ),
    ]

    await ui.send_rich(
        client, chat_id,
        "<b>The mark in the middle</b>\n"
        "\n"
        f"Right now every code you make here says {ui.code(mark)} across its "
        "centre.\n"
        "\n"
        f"Send me what it should say instead. One line, up to "
        f"{WATERMARK_TEXT_MAX} characters. Short is better: the mark is a hole "
        "punched through the symbol, and a wide one leaves the scanner less to "
        "work with." + off_note,
        buttons=ui.keyboard(*rows),
    )


async def _apply_watermark_text(client, chat_id: int, sender_id: int,
                                typed: str) -> None:
    """Validate and store a new mark, then show it working."""
    try:
        text = qrgen.clean_watermark_text(typed)
    except qrgen.WatermarkTextError as exc:
        # The flow is left running on a rejection, so the next message is
        # another go rather than a code of whatever they typed.
        retry = ""
        if await db.get_flow(sender_id):
            retry = "\n\nSend another one, or /cancel to leave the mark alone."
        await ui.send_rich(client, chat_id, ui.esc(str(exc)) + retry)
        return

    prefs = await db.get_prefs(sender_id)
    prefs["watermark_text"] = text
    # Asking for a mark and getting a blank code back would be a puzzle, so
    # setting the text turns the mark on if it was off.
    prefs["watermark"] = 1
    await db.set_prefs(sender_id, prefs)
    await db.clear_flow(sender_id)

    from handlers_qr import deliver_code

    await deliver_code(
        client, chat_id, sender_id, "https://qr.uwuapps.org",
        note=f"The mark now reads {ui.code(text)}. Every code you make here "
             "carries it until you change it again with /watermark.",
    )


@dispatch.text_flow("watermark", "watermark change")
async def _flow_watermark(client, chat_id, sender_id, flow_row, value) -> None:
    await _apply_watermark_text(client, chat_id, sender_id, value)


@dispatch.on("wm_ask")
async def _cb_wm_ask(event, button):
    await event.answer()
    await _ask_watermark_text(event.client, event.chat_id, event.sender_id)


@dispatch.on("wm_default")
async def _cb_wm_default(event, button):
    await event.answer("Back to uwu.")
    await ui.edit_rich(
        await event.get_message(),
        "Back to the mark the portal draws.",
    )
    await _apply_watermark_text(event.client, event.chat_id, event.sender_id,
                                WATERMARK_TEXT)


@dispatch.on("wm_cancel")
async def _cb_wm_cancel(event, button):
    await db.clear_flow(event.sender_id)
    await event.answer("Left as it was.")
    await ui.edit_rich(
        await event.get_message(),
        "The mark is unchanged. /watermark reopens this whenever you want it.",
    )
