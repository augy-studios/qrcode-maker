"""The codes saved on a portal account, and the rendering preferences.

Everything here needs a connected account except the settings command, which
is local to the chat and works whether or not the portal is reachable.
"""

import asyncio
import logging
import time

import db
import dispatch
import linking
import qrgen
import supa
import ui
from config import (
    COLOUR_PRESETS,
    EC_STEPS,
    MARGIN_STEPS,
    SAVED_PAGE_SIZE,
    SIZE_STEPS,
    TABLE_CODES,
)
from telethon import events

log = logging.getLogger(__name__)


def register(client) -> None:

    @client.on(events.NewMessage(
        pattern=dispatch.command("saved", "myqrs", "list"), func=dispatch.private
    ))
    async def on_saved(event):
        if not supa.enabled():
            await ui.reply_rich(event, ui.NOT_CONFIGURED)
            raise events.StopPropagation
        link = await linking.link_for_telegram(event.sender_id)
        if not link:
            await ui.reply_rich(
                event, ui.NO_LINK,
                buttons=ui.keyboard(ui.row(ui.portal_button())),
            )
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


# ------------------------------------------------------------ saved codes ---


async def _show_page(client, chat_id: int, sender_id: int, user_id: str,
                     page: int, message=None) -> None:
    try:
        total = await supa.count(TABLE_CODES, {"user_id": f"eq.{user_id}"})
        rows = await supa.select(
            TABLE_CODES,
            {"user_id": f"eq.{user_id}"},
            columns="id,type,data_preview,image_url,created_at",
            order="created_at.desc",
            limit=SAVED_PAGE_SIZE,
            offset=page * SAVED_PAGE_SIZE,
        )
    except supa.SupabaseError:
        log.exception("Could not read the saved codes.")
        await ui.send_rich(
            client, chat_id,
            "The portal is not answering right now. Try again shortly.",
        )
        return

    if total == 0:
        await ui.send_rich(
            client, chat_id,
            "<b>Nothing saved yet</b>\n"
            "\n"
            "Generate a code here and press Save to my account, or save one "
            "from the portal. They all land in the same place.",
            buttons=ui.keyboard(ui.row(ui.portal_button())),
        )
        return

    pages = max(1, -(-total // SAVED_PAGE_SIZE))
    page = max(0, min(page, pages - 1))
    first = page * SAVED_PAGE_SIZE

    lines = [f"<b>Your saved codes</b>\nPage {page + 1} of {pages}, {total} in total.\n"]
    keyboard_rows = []

    for offset, row in enumerate(rows, start=1):
        number = first + offset
        label = qrgen.KIND_LABELS.get(row.get("type") or "", "Code")
        preview = (row.get("data_preview") or "").strip() or "no preview"
        stamp = (row.get("created_at") or "")[:10]
        lines.append(
            f"<b>{number}.</b> {ui.esc(label)}, saved {ui.esc(stamp)}\n"
            f"    {ui.esc(preview[:70])}"
        )
        keyboard_rows.append([
            ui.url_button(f"Open {number}", row["image_url"]),
            await ui.inline_button(
                f"Delete {number}", "saved_delete_ask",
                {"id": row["id"], "page": page, "n": number},
                owner_id=sender_id,
            ),
        ])

    nav = []
    if page > 0:
        nav.append(await ui.inline_button(
            "Previous", "saved_page", {"page": page - 1}, owner_id=sender_id))
    if page + 1 < pages:
        nav.append(await ui.inline_button(
            "Next", "saved_page", {"page": page + 1}, owner_id=sender_id))
    if nav:
        keyboard_rows.append(nav)

    keyboard_rows.append(ui.row(
        await ui.inline_button(
            "Send these as images", "saved_images", {"page": page},
            owner_id=sender_id,
        ),
        ui.portal_button("On the web"),
    ))

    body = "\n".join(lines)
    buttons = ui.keyboard(*keyboard_rows)
    if message is not None:
        await ui.edit_rich(message, body, buttons=buttons)
    else:
        await ui.send_rich(client, chat_id, body, buttons=buttons)


@dispatch.on("saved_page")
async def _cb_saved_page(event, button):
    link = await linking.link_for_telegram(event.sender_id)
    if not link:
        await event.answer("This chat is not connected.", alert=True)
        return
    await event.answer()
    await _show_page(event.client, event.chat_id, event.sender_id,
                     link["user_id"], int(button["payload"]["page"]),
                     message=await event.get_message())


@dispatch.on("saved_images")
async def _cb_saved_images(event, button):
    link = await linking.link_for_telegram(event.sender_id)
    if not link:
        await event.answer("This chat is not connected.", alert=True)
        return

    page = int(button["payload"]["page"])
    await event.answer("Sending.")
    rows = await supa.select(
        TABLE_CODES,
        {"user_id": f"eq.{link['user_id']}"},
        columns="id,type,data_preview,image_url",
        order="created_at.desc",
        limit=SAVED_PAGE_SIZE,
        offset=page * SAVED_PAGE_SIZE,
    )
    urls = [row["image_url"] for row in rows if row.get("image_url")]
    if not urls:
        await ui.send_rich(event.client, event.chat_id, "That page is empty now.")
        return
    try:
        await event.client.send_file(event.chat_id, urls)
    except Exception:  # noqa: BLE001 - a bad URL should not kill the handler
        log.exception("Could not send the saved images.")
        await ui.send_rich(
            event.client, event.chat_id,
            "Those images would not upload. The Open buttons still reach them.",
        )


@dispatch.on("saved_delete_ask")
async def _cb_saved_delete_ask(event, button):
    payload = button["payload"]
    await event.answer()
    buttons = ui.keyboard(ui.row(
        await ui.inline_button(
            "Delete it", "saved_delete", payload, owner_id=event.sender_id),
        await ui.inline_button(
            "Keep it", "saved_back", {"page": payload.get("page", 0)},
            owner_id=event.sender_id),
    ))
    await ui.edit_rich(
        await event.get_message(),
        f"<b>Delete code {payload.get('n', '')}?</b>\n"
        "\n"
        "The image and the record both go, on the portal as well as here. "
        "There is no undo.",
        buttons=buttons,
    )


@dispatch.on("saved_delete")
async def _cb_saved_delete(event, button):
    link = await linking.link_for_telegram(event.sender_id)
    if not link:
        await event.answer("This chat is not connected.", alert=True)
        return

    code_id = button["payload"]["id"]
    row = await supa.select_one(
        TABLE_CODES, {"id": f"eq.{code_id}"}, columns="id,user_id,image_path"
    )
    if row is None or row["user_id"] != link["user_id"]:
        await event.answer("That code is not yours, or it is already gone.",
                           alert=True)
        return

    if row.get("image_path"):
        await supa.remove([row["image_path"]])
    await supa.delete(TABLE_CODES, {"id": f"eq.{code_id}"})

    await event.answer("Deleted.")
    await _show_page(event.client, event.chat_id, event.sender_id,
                     link["user_id"], int(button["payload"].get("page", 0)),
                     message=await event.get_message())


@dispatch.on("saved_back")
async def _cb_saved_back(event, button):
    link = await linking.link_for_telegram(event.sender_id)
    if not link:
        await event.answer("This chat is not connected.", alert=True)
        return
    await event.answer("Kept.")
    await _show_page(event.client, event.chat_id, event.sender_id,
                     link["user_id"], int(button["payload"].get("page", 0)),
                     message=await event.get_message())


# -------------------------------------------------------------- saving one --


@dispatch.on("save_code")
async def _cb_save_code(event, button):
    if not supa.enabled():
        await event.answer("Account features are switched off here.", alert=True)
        return

    link = await linking.link_for_telegram(event.sender_id)
    if not link:
        await event.answer("Connect an account first with /link.", alert=True)
        await ui.send_rich(
            event.client, event.chat_id, ui.NO_LINK,
            buttons=ui.keyboard(ui.row(ui.portal_button())),
        )
        return

    row = await db.get_history(button["payload"]["h"])
    if not row:
        await event.answer("That code is no longer in the local history.",
                           alert=True)
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


async def _show_settings(client, chat_id: int, sender_id: int, message=None) -> None:
    prefs = await db.get_prefs(sender_id)
    watermark_on = bool(prefs["watermark"])

    warning = ""
    if watermark_on and prefs["ec"] != "H":
        warning = (
            "\n\nThe watermark covers part of the symbol, and correction "
            f"{prefs['ec']} may not have the headroom to survive it. Level H is "
            "what the portal uses for exactly this reason."
        )

    body = (
        "<b>Your defaults</b>\n"
        "\n"
        f"Size, {prefs['size']} px\n"
        f"Quiet zone, {prefs['margin']} modules\n"
        f"Error correction, {prefs['ec']}\n"
        f"Watermark, {'on' if watermark_on else 'off'}\n"
        f"Colours, {_colour_name(prefs['fg'], prefs['bg'])}\n"
        "\n"
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
        await ui.edit_rich(message, body, buttons=buttons)
    else:
        await ui.send_rich(client, chat_id, body, buttons=buttons)


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
