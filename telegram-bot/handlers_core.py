"""Welcome, help, and everything to do with connecting an account."""

import logging

from telethon import events

import db
import dispatch
import linking
import reply
import runtime
import supa
import ui
from config import (
    DEEPLINK_TTL,
    OWNER_TELEGRAM_IDS,
    POLL_INTERVAL,
    PULL_OTP_TTL,
    TABLE_LINKS,
    TABLE_TOKENS,
    WEBAPP_URL,
)
from reply import escape_md

log = logging.getLogger(__name__)


def _needs_supabase(func):
    """Refuse account commands cleanly when the portal is not configured."""

    async def wrapper(event):
        if not supa.enabled():
            await ui.reply_rich(event, ui.NOT_CONFIGURED)
            return
        return await func(event)

    wrapper.__name__ = func.__name__
    return wrapper


def register(client) -> None:

    # ------------------------------------------------------------- start --

    @client.on(events.NewMessage(
        pattern=dispatch.command("start"), func=dispatch.private
    ))
    async def on_start(event):
        token_code = dispatch.argument(event)
        if token_code and supa.enabled():
            handled = await _handle_deeplink(event, token_code)
            if handled:
                raise events.StopPropagation

        buttons = ui.keyboard(
            ui.row(ui.portal_button(), ui.donate_button()),
            ui.row(
                await ui.inline_button(
                    "Connect my account", "start_link", owner_id=event.sender_id
                )
            ) if supa.enabled() and event.is_private else [],
        )
        await ui.reply_rich(event, rich=ui.start_text(), buttons=buttons)
        raise events.StopPropagation

    @client.on(events.NewMessage(
        pattern=dispatch.command("donate", "support"), func=dispatch.private
    ))
    async def on_donate(event):
        from config import DONATION_URL

        if not DONATION_URL:
            await ui.reply_rich(
                event,
                "No donation link is set on this instance. Everything here is "
                "free to use regardless.",
            )
            raise events.StopPropagation
        await ui.reply_rich(
            event,
            "<b>Support the project</b>\n"
            "\n"
            "QR Maker is free and stays that way. If it saved you some time, a "
            "contribution keeps the servers paid for.",
            buttons=ui.keyboard(ui.row(ui.donate_button("Donate"), ui.portal_button())),
        )
        raise events.StopPropagation

    @client.on(events.NewMessage(
        pattern=dispatch.command("cancel", "stop"), func=dispatch.private
    ))
    async def on_cancel(event):
        flow = await db.get_flow(event.sender_id)
        await db.clear_flow(event.sender_id)
        if flow:
            await ui.reply_rich(
                event,
                f"Dropped the half finished {ui.esc(dispatch.flow_label(flow['flow']))}. "
                "Nothing was saved.",
            )
        else:
            await ui.reply_rich(event, "Nothing was in progress.")
        raise events.StopPropagation

    # -------------------------------------------------------------- link --

    @client.on(events.NewMessage(
        pattern=dispatch.command("link"), func=dispatch.private
    ))
    @_needs_supabase
    async def on_link(event):
        await _offer_link(event.client, event.chat_id, event.sender_id)
        raise events.StopPropagation

    @client.on(events.NewMessage(
        pattern=dispatch.command("code", "otp"), func=dispatch.private
    ))
    @_needs_supabase
    async def on_code(event):
        await _send_pull_otp(event.client, event.chat_id, await event.get_sender())
        raise events.StopPropagation

    @client.on(events.NewMessage(
        pattern=dispatch.command("unlink", "disconnect"), func=dispatch.private
    ))
    @_needs_supabase
    async def on_unlink(event):
        link = await linking.link_for_telegram(event.sender_id)
        if not link:
            await ui.reply_rich(event, ui.NO_LINK)
            raise events.StopPropagation

        username = (link.get("qr_users") or {}).get("username") or "your account"
        warning = ""
        if link.get("twofa_enabled"):
            warning = (
                "\n\nSign in approval is currently on. Disconnecting turns it "
                "off too, so the portal goes back to password only."
            )

        buttons = ui.keyboard(
            ui.row(
                await ui.inline_button(
                    "Yes, disconnect", "unlink_confirm", owner_id=event.sender_id
                ),
                await ui.inline_button(
                    "Keep it", "dismiss", owner_id=event.sender_id
                ),
            )
        )
        await ui.reply_rich(
            event,
            f"<b>Disconnect {ui.esc(username)}?</b>\n"
            "\n"
            "Your saved codes stay exactly where they are. This chat simply "
            "stops being able to reach them." + warning,
            buttons=buttons,
        )
        raise events.StopPropagation

    @client.on(events.NewMessage(
        pattern=dispatch.command("twofa", "2fa"), func=dispatch.private
    ))
    @_needs_supabase
    async def on_twofa(event):
        link = await linking.link_for_telegram(event.sender_id)
        if not link:
            await ui.reply_rich(event, ui.NO_LINK)
            raise events.StopPropagation
        await _show_twofa(event.client, event.chat_id, event.sender_id, link)
        raise events.StopPropagation

    # ------------------------------------------------------------ health --
    # Deliberately absent from the command list. It is for whoever runs the
    # bot, not for the people using it, and an unlisted command that answers
    # nobody else is the least confusing way to do that.

    @client.on(events.NewMessage(
        pattern=dispatch.command("health", "status"), func=dispatch.private
    ))
    async def on_health(event):
        if event.sender_id not in OWNER_TELEGRAM_IDS:
            # Say nothing useful. An unlisted command should not confirm to a
            # stranger that it exists.
            raise events.StopPropagation
        await ui.reply_rich(event, rich=await _health_report(), buttons=None)
        raise events.StopPropagation


# ------------------------------------------------------------------ health --


async def _health_report() -> dict:
    """Everything worth knowing about the running process, as tables."""
    import handlers_qr  # imported here to keep the module import graph flat

    counts = await db.counts()
    size_mb = counts["bytes"] / (1024 * 1024)

    sections = [
        "# Health",
        reply.table(["Value"], [
            ["Uptime", runtime.human_duration(runtime.uptime_seconds())],
            ["Reading codes", "on" if handlers_qr.DECODING_AVAILABLE else "off"],
            ["Portal", WEBAPP_URL],
        ]),
        "## Local database",
        reply.table(["Count"], [
            ["Buttons", f"{counts['buttons']} total, {counts['buttons_active']} still live"],
            ["Builders in progress", counts["flows"]],
            ["People with saved settings", counts["prefs"]],
            ["History rows", counts["history"]],
            ["Codes waiting on a link", counts["favourites"]],
            ["Size on disk", f"{size_mb:.1f} MB"],
        ]),
        "## Portal link",
    ]

    if not supa.enabled():
        sections.append("Off, no credentials configured.")
        return ui.rich("\n\n".join(sections))

    portal = [
        ["Token sweep", f"{runtime.sweeper_state()}, every {POLL_INTERVAL}s"],
        ["Last good reply", runtime.ago(runtime.last_supabase_ok_at)],
    ]
    if runtime.last_supabase_error:
        portal.append(["Last refusal", runtime.ago(runtime.last_supabase_error_at)])

    # A live count doubles as proof the credentials still work.
    unreachable = ""
    try:
        linked = await supa.count(TABLE_LINKS)
        live = await supa.count(
            TABLE_TOKENS, {"status": "in.(pending,delivered)"}
        )
        portal += [["Connected accounts", linked], ["Tokens still open", live]]
    except supa.SupabaseError as exc:
        unreachable = (
            "Could not reach the portal just now: " + escape_md(str(exc)[:200])
        )

    sections.append(reply.table(["Value"], portal))
    if runtime.last_supabase_error:
        # A fenced block keeps the refusal verbatim, whatever it contains.
        fence = "```"
        sections.append(
            f"{fence}\n{runtime.last_supabase_error.replace(fence, '~~~')}\n{fence}"
        )
    else:
        sections.append("No refusals since start up.")
    if unreachable:
        sections.append(unreachable)

    return ui.rich("\n\n".join(sections))


# ------------------------------------------------------------- shared work --


async def _handle_deeplink(event, token_code: str) -> bool:
    """A start link carrying a token the portal minted moments ago."""
    try:
        token = await linking.find_deeplink(token_code)
    except supa.SupabaseError:
        log.exception("Could not read the deep link token.")
        await ui.reply_rich(
            event, "The portal is not answering right now. Try again shortly."
        )
        return True

    if token is None:
        await ui.reply_rich(
            event,
            "That connect link has already been used, or it was never valid. "
            "Start again from the portal, or run /code for a six digit "
            "alternative.",
            buttons=ui.keyboard(ui.row(ui.portal_button())),
        )
        return True

    if linking.is_expired(token):
        await linking.mark_token(token["id"], "expired")
        await ui.reply_rich(
            event,
            "That connect link expired. They only last ten minutes. Press the "
            "connect button on the portal again.",
            buttons=ui.keyboard(ui.row(ui.portal_button())),
        )
        return True

    username = (token.get("qr_users") or {}).get("username") or "a portal account"
    await linking.mark_token(token["id"], "delivered")

    buttons = ui.keyboard(
        ui.row(
            await ui.inline_button(
                "Yes, connect it", "link_confirm",
                {"token_id": token["id"]}, owner_id=event.sender_id, ttl=DEEPLINK_TTL,
            ),
            await ui.inline_button(
                "No", "link_cancel",
                {"token_id": token["id"]}, owner_id=event.sender_id, ttl=DEEPLINK_TTL,
            ),
        )
    )
    await ui.reply_rich(
        event,
        "<b>Connect your account?</b>\n"
        "\n"
        f"The portal asked to connect this chat to {ui.esc(username)}.\n"
        "\n"
        "Once connected you can list and save codes from here, and this chat "
        "can act as the second factor when you sign in. Confirm only if you "
        "started this yourself, just now.",
        buttons=buttons,
    )
    return True


async def _offer_link(client, chat_id: int, sender_id: int) -> None:
    link = await linking.link_for_telegram(sender_id)
    if link:
        username = (link.get("qr_users") or {}).get("username") or "your account"
        state = "on" if link.get("twofa_enabled") else "off"
        await ui.send_rich(
            client, chat_id,
            f"<b>Already connected</b>\n"
            "\n"
            f"This chat belongs to {ui.esc(username)}. Sign in approval is {state}.\n"
            "\n"
            "Use /saved to browse your codes, /twofa to change the approval "
            "setting, or /unlink to disconnect.",
            buttons=ui.keyboard(ui.row(ui.portal_button())),
        )
        return

    buttons = ui.keyboard(
        ui.row(ui.url_button("Open the portal and connect", f"{WEBAPP_URL}/#link")),
        ui.row(
            await ui.inline_button(
                "Give me a code instead", "issue_code", owner_id=sender_id
            )
        ),
    )
    await ui.send_rich(
        client, chat_id,
        "<b>Connect your account</b>\n"
        "\n"
        "Connecting lets this chat reach the codes saved on your portal "
        "account, and lets it approve sign ins on your behalf. There are two "
        "ways to do it, and neither one asks for your password here.\n"
        "\n"
        "<b>From the portal</b>\n"
        "Sign in, open My QRs, and press Connect Telegram. It hands you "
        "straight back here for one confirmation tap.\n"
        "\n"
        "<b>From this chat</b>\n"
        "Ask for a six digit code below, then type it into the same panel on "
        "the portal. Handy when the portal is open on another device.",
        buttons=buttons,
    )


async def _send_pull_otp(client, chat_id: int, sender) -> None:
    if await linking.link_for_telegram(sender.id):
        await ui.send_rich(
            client, chat_id,
            "This chat is already connected. Run /unlink first if you want to "
            "attach it to a different portal account.",
        )
        return

    try:
        token = await linking.issue_pull_otp(sender)
    except (supa.SupabaseError, linking.LinkError):
        log.exception("Could not issue a pull code.")
        await ui.send_rich(
            client, chat_id,
            "The portal is not answering right now. Try again shortly.",
        )
        return

    minutes = PULL_OTP_TTL // 60
    await ui.send_rich(
        client, chat_id,
        "<b>Your connect code</b>\n"
        "\n"
        f"{ui.code(token['code'])}\n"
        "\n"
        f"Sign in to the portal, open My QRs, press Connect Telegram, and type "
        f"those six digits. The code is good for {minutes} minutes and works "
        "once.\n"
        "\n"
        "You will get a message here the moment it lands.",
        buttons=ui.keyboard(ui.row(ui.portal_button("Open My QRs"))),
    )


async def _show_twofa(client, chat_id: int, sender_id: int, link: dict,
                      message=None) -> None:
    enabled = bool(link.get("twofa_enabled"))
    username = (link.get("qr_users") or {}).get("username") or "your account"

    if enabled:
        body = (
            "<b>Sign in approval is on</b>\n"
            "\n"
            f"A password alone will not get anyone into {ui.esc(username)}. "
            "Every sign in also has to be approved here, either by tapping the "
            "button in the message or by typing the six digits it carries.\n"
            "\n"
            "Keep this chat reachable. If you cannot, the backup codes on the "
            "portal are the way back in, so make a set under My QRs before you "
            "need them."
        )
        label = "Turn it off"
    else:
        body = (
            "<b>Sign in approval is off</b>\n"
            "\n"
            f"{ui.esc(username)} is protected by its password alone. Turn "
            "approval on and every sign in gets held until you allow it here, "
            "with one tap or six digits.\n"
            "\n"
            "It costs you a couple of seconds per sign in and it makes a "
            "stolen password useless on its own."
        )
        label = "Turn it on"

    buttons = ui.keyboard(
        ui.row(
            await ui.inline_button(
                label, "twofa_toggle", {"enable": not enabled}, owner_id=sender_id
            )
        )
    )
    if message is not None:
        await ui.edit_rich(message, body, buttons=buttons)
    else:
        await ui.send_rich(client, chat_id, body, buttons=buttons)


# --------------------------------------------------------------- callbacks --


@dispatch.on("start_link")
async def _cb_start_link(event, button):
    await event.answer()
    await _offer_link(event.client, event.chat_id, event.sender_id)


@dispatch.on("issue_code")
async def _cb_issue_code(event, button):
    await event.answer()
    await _send_pull_otp(event.client, event.chat_id, await event.get_sender())


@dispatch.on("link_confirm")
async def _cb_link_confirm(event, button):
    token = await linking.find_token(button["payload"]["token_id"])
    message = await event.get_message()

    if token is None or token["status"] not in ("pending", "delivered"):
        await event.answer("That request is no longer open.", alert=True)
        await ui.edit_rich(
            message,
            "That connect request has already been dealt with. Start a new one "
            "from the portal if you still need it.",
        )
        return

    if linking.is_expired(token):
        await linking.mark_token(token["id"], "expired")
        await event.answer("That request expired.", alert=True)
        await ui.edit_rich(
            message,
            "That connect request expired before it was confirmed. Press "
            "Connect Telegram on the portal again.",
        )
        return

    sender = await event.get_sender()
    await linking.write_link(token["user_id"], sender)
    await linking.mark_token(token["id"], "confirmed", telegram_id=sender.id,
                             telegram_username=getattr(sender, "username", None),
                             notified=True)

    username = (token.get("qr_users") or {}).get("username") or "your portal account"
    await event.answer("Connected.")
    await ui.edit_rich(
        message,
        "<b>Connected</b>\n"
        "\n"
        f"This chat now belongs to {ui.esc(username)}. The portal tab you "
        "started from will notice within a second or two.\n"
        "\n"
        "Try /saved to browse the codes on your account, or /twofa to make "
        "this chat guard your sign ins.",
        buttons=ui.keyboard(ui.row(ui.portal_button())),
    )

    # Anything saved here while there was nowhere to put it now has somewhere.
    from handlers_account import merge_favourites

    await merge_favourites(event.client, sender.id, token["user_id"])


@dispatch.on("link_cancel")
async def _cb_link_cancel(event, button):
    token_id = button["payload"].get("token_id")
    if token_id:
        await linking.mark_token(token_id, "denied", notified=True)
    await event.answer("Turned down.")
    await ui.edit_rich(
        await event.get_message(),
        "Left alone. Nothing was connected and the request is now dead.\n"
        "\n"
        "If you did not start that request, someone else has your portal "
        "password. Change it.",
    )


@dispatch.on("unlink_confirm")
async def _cb_unlink_confirm(event, button):
    removed = await linking.remove_link(event.sender_id)
    await event.answer("Disconnected." if removed else "Nothing to disconnect.")
    await ui.edit_rich(
        await event.get_message(),
        "<b>Disconnected</b>\n"
        "\n"
        "This chat no longer reaches any portal account, and sign in approval "
        "is off. Your saved codes are untouched and still on the portal.\n"
        "\n"
        "Run /link whenever you want to connect again."
        if removed else
        "There was nothing connected to remove.",
        buttons=ui.keyboard(ui.row(ui.portal_button())),
    )


@dispatch.on("twofa_toggle")
async def _cb_twofa_toggle(event, button):
    enable = bool(button["payload"].get("enable"))
    link = await linking.link_for_telegram(event.sender_id)
    if not link:
        await event.answer("This chat is not connected.", alert=True)
        return

    await linking.set_twofa(event.sender_id, enable)
    await event.answer("Approval is on." if enable else "Approval is off.")
    link["twofa_enabled"] = enable
    await _show_twofa(
        event.client, event.chat_id, event.sender_id, link,
        message=await event.get_message(),
    )


@dispatch.on("push_deny")
async def _cb_push_deny(event, button):
    token_id = button["payload"].get("token_id")
    if token_id:
        await linking.mark_token(token_id, "denied", notified=True)
    await event.answer("Blocked.")
    await ui.edit_rich(
        await event.get_message(),
        "<b>Sign in blocked</b>\n"
        "\n"
        "That attempt was refused and the browser waiting on it has been told "
        "so. Whoever tried it knows your password, so change it now.",
        buttons=ui.keyboard(ui.row(ui.portal_button("Change my password"))),
    )


@dispatch.on("backup_approve")
async def _cb_backup_approve(event, button):
    """Let the portal mint a set of backup codes.

    Confirmed is as far as this goes. The codes themselves are made by the
    portal, on the page that is polling for this, so they only ever exist in
    front of whoever asked, and never in a chat that could be read later.
    """
    token = await linking.find_token(button["payload"]["token_id"])
    message = await event.get_message()

    if token is None or token["status"] not in ("pending", "delivered"):
        await event.answer("That request is no longer open.", alert=True)
        await ui.edit_rich(
            message,
            "That backup code request has already been dealt with. Ask again "
            "from the portal if you still want a set.",
        )
        return

    if linking.is_expired(token):
        await linking.mark_token(token["id"], "expired", notified=True)
        await event.answer("That request expired.", alert=True)
        await ui.edit_rich(
            message,
            "That backup code request sat here too long and has expired. Ask "
            "again from the portal.",
        )
        return

    await linking.mark_token(token["id"], "confirmed")
    await event.answer("Allowed.")
    await ui.edit_rich(
        message,
        "<b>Allowed</b>\n"
        "\n"
        "The portal is drawing the codes now. They appear on the page you asked "
        "from, once.",
    )


@dispatch.on("backup_deny")
async def _cb_backup_deny(event, button):
    token_id = button["payload"].get("token_id")
    if token_id:
        await linking.mark_token(token_id, "denied", notified=True)
    await event.answer("Refused.")
    await ui.edit_rich(
        await event.get_message(),
        "<b>Refused</b>\n"
        "\n"
        "No codes were made and the page waiting on this has been told so.\n"
        "\n"
        "That request came from a browser already signed in to your account, so "
        "if it was not you, someone is holding a session they should not have. "
        "Change your password, which throws every session away.",
        buttons=ui.keyboard(ui.row(ui.portal_button("Change my password"))),
    )


@dispatch.on("dismiss")
async def _cb_dismiss(event, button):
    await event.answer()
    await ui.edit_rich(await event.get_message(), "Left as it was.")
