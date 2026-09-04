"""Account linking and two factor sign in.

Four hand offs share one token table. Which one is in play is decided by the
direction the token travels and who issues it.

  Deep link      The portal mints a token, drops the user at a start link, and
                 polls. The bot asks for a confirmation tap and marks the row
                 confirmed. Nothing secret is ever typed anywhere.

  Pull OTP       The user asks the bot for six digits and types them into the
                 portal. The portal matches the digits to a Telegram id and
                 writes the link. The bot notices and says so.

  Push OTP       A password login on an account with two factor turned on gets
                 held back. The portal records the attempt, the bot delivers
                 the digits unprompted, and the session only becomes real once
                 the user proves they are here.

  Magic link     The same push message carries a Sign In button. One tap hits
                 the redemption endpoint and the browser, still polling, is
                 signed in without any digits changing hands.

The bot owns the Telegram half of all four. The portal half lives in
main-site/api/telegram-link.js.

There is a fifth way to finish a held back sign in, and the bot has no half of
it at all: a backup code, typed into the portal when this chat cannot be
reached. The bot only ever hears about it afterwards, from the token, and says
so in the chat, because a sign in that went around Telegram is exactly the sort
of thing the owner should be told about.
"""

import asyncio
import logging
import secrets
from datetime import datetime, timezone

import db
import supa
import ui
from config import (
    POLL_INTERVAL,
    PULL_OTP_TTL,
    SESSION_TTL_DAYS,
    TABLE_LINKS,
    TABLE_SESSIONS,
    TABLE_TOKENS,
    WARN_AFTER_ATTEMPTS,
    WEBAPP_URL,
)

log = logging.getLogger(__name__)


class LinkError(Exception):
    """Something the user should be told about, in plain words."""


# ------------------------------------------------------------------- links --


async def link_for_telegram(telegram_id: int) -> dict | None:
    if not supa.enabled():
        return None
    return await supa.select_one(
        TABLE_LINKS,
        {"telegram_id": f"eq.{telegram_id}"},
        columns="*,qr_users(username)",
    )


async def link_for_user(user_id: str) -> dict | None:
    if not supa.enabled():
        return None
    return await supa.select_one(TABLE_LINKS, {"user_id": f"eq.{user_id}"})


async def username_for(telegram_id: int) -> str | None:
    link = await link_for_telegram(telegram_id)
    if not link:
        return None
    user = link.get("qr_users") or {}
    return user.get("username")


async def write_link(user_id: str, sender) -> dict:
    """Create or move the mapping between a portal account and this chat.

    A Telegram account can only hold one portal account and the reverse, so an
    existing mapping on either side is cleared before the new one is written.
    """
    await supa.delete(TABLE_LINKS, {"telegram_id": f"eq.{sender.id}"})
    return await supa.upsert(
        TABLE_LINKS,
        {
            "user_id": user_id,
            "telegram_id": sender.id,
            "telegram_username": getattr(sender, "username", None),
            "telegram_name": display_name(sender),
            "linked_at": supa.now_iso(),
        },
        on_conflict="user_id",
    )


async def remove_link(telegram_id: int) -> bool:
    removed = await supa.delete(TABLE_LINKS, {"telegram_id": f"eq.{telegram_id}"})
    return bool(removed)


async def set_twofa(telegram_id: int, enabled: bool) -> None:
    await supa.update(
        TABLE_LINKS,
        {"telegram_id": f"eq.{telegram_id}"},
        {"twofa_enabled": enabled},
    )


def display_name(sender) -> str:
    parts = [getattr(sender, "first_name", None), getattr(sender, "last_name", None)]
    name = " ".join(p for p in parts if p).strip()
    return name or (getattr(sender, "username", None) or str(sender.id))


# ------------------------------------------------------------------ tokens --


def _digits(n: int = 6) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(n))


async def _insert_token(row: dict, retries: int = 5) -> dict:
    """Insert a token, minting a fresh code if the live code index collides."""
    for attempt in range(retries):
        try:
            return await supa.insert(TABLE_TOKENS, row)
        except supa.SupabaseError as exc:
            if "duplicate key" not in str(exc).lower() or attempt == retries - 1:
                raise
            row = dict(row, code=_digits(len(row["code"])))
    raise LinkError("Could not issue a code just now. Try again in a moment.")


async def issue_pull_otp(sender) -> dict:
    """Six digits the user types into the portal to claim this chat."""
    # Retire anything still live for this chat so only the newest code works.
    await supa.update(
        TABLE_TOKENS,
        {
            "kind": "eq.pull_otp",
            "telegram_id": f"eq.{sender.id}",
            "status": "in.(pending,delivered)",
        },
        {"status": "expired"},
    )
    return await _insert_token(
        {
            "kind": "pull_otp",
            "code": _digits(),
            "status": "pending",
            "telegram_id": sender.id,
            "telegram_username": getattr(sender, "username", None),
            "expires_at": supa.in_seconds_iso(PULL_OTP_TTL),
        }
    )


async def find_deeplink(code: str) -> dict | None:
    return await supa.select_one(
        TABLE_TOKENS,
        {"kind": "eq.deeplink", "code": f"eq.{code}", "status": "in.(pending,delivered)"},
        columns="*,qr_users(username)",
    )


async def mark_token(token_id: str, status: str, **extra) -> None:
    patch = {"status": status, "consumed_at": supa.now_iso()}
    patch.update(extra)
    await supa.update(TABLE_TOKENS, {"id": f"eq.{token_id}"}, patch)


async def find_token(token_id: str) -> dict | None:
    return await supa.select_one(
        TABLE_TOKENS, {"id": f"eq.{token_id}"}, columns="*,qr_users(username)"
    )


def is_expired(token: dict) -> bool:
    raw = token.get("expires_at")
    if not raw:
        return False
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment < datetime.now(timezone.utc)


def magic_link(token: dict) -> str:
    return f"{WEBAPP_URL}/api/telegram-link?action=approve&t={token['approval_secret']}"


async def activate_session(token: dict) -> None:
    """Turn the pre minted session into a real one the browser can use."""
    if not token.get("session_token") or not token.get("user_id"):
        raise LinkError("This sign in request is incomplete.")
    await supa.insert(
        TABLE_SESSIONS,
        {
            "token": token["session_token"],
            "user_id": token["user_id"],
            "expires_at": supa.in_days_iso(SESSION_TTL_DAYS),
        },
    )


# ------------------------------------------------------------------ sweeps --
#
# The portal cannot reach the bot, so the bot watches the token table instead.
# Three seconds is quick enough that a sign in prompt feels immediate and slow
# enough that the sweep costs almost nothing.


async def poll_forever(client) -> None:
    log.info("Token sweep running every %s seconds.", POLL_INTERVAL)
    while True:
        try:
            await _sweep(client)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a bad sweep must not stop the bot
            log.exception("Token sweep failed, carrying on.")
        await asyncio.sleep(POLL_INTERVAL)


async def _sweep(client) -> None:
    await _expire_stale()
    await _deliver_push_prompts(client)
    await _warn_about_guessing(client)
    await _announce_completions(client)


async def _expire_stale() -> None:
    await supa.update(
        TABLE_TOKENS,
        {"status": "in.(pending,delivered)", "expires_at": f"lt.{supa.now_iso()}"},
        {"status": "expired"},
    )


async def _for_each(rows, work) -> None:
    """Run one coroutine per row, so a single bad row costs only itself."""
    for row in rows:
        try:
            await work(row)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Token %s could not be handled.", row.get("id"))


async def _deliver_push_prompts(client) -> None:
    """Push the sign in challenge to whoever owns the account."""
    pending = await supa.select(
        TABLE_TOKENS,
        {"kind": "eq.push_otp", "status": "eq.pending"},
        columns="*,qr_users(username)",
        order="created_at.asc",
        limit=20,
    )
    await _for_each(pending, lambda token: _deliver_one(client, token))


async def _deliver_one(client, token: dict) -> None:
    if not token.get("telegram_id"):
        await mark_token(token["id"], "expired")
        return
    if not await db.mark_seen(f"push:{token['id']}"):
        return

    user = token.get("qr_users") or {}
    username = user.get("username") or "your account"
    meta = token.get("meta") or {}
    where = meta.get("ip") or "an unrecognised address"
    agent = meta.get("agent") or "an unknown browser"

    buttons = ui.keyboard(
        ui.row(ui.url_button("Approve and sign in", magic_link(token))),
        ui.row(
            await ui.inline_button(
                "This was not me",
                "push_deny",
                {"token_id": token["id"]},
                owner_id=token["telegram_id"],
            )
        ),
    )

    text = (
        "<b>Sign in request</b>\n"
        "\n"
        f"Someone is signing in to {ui.esc(username)} on the portal.\n"
        f"From {ui.esc(where)} using {ui.esc(agent)}.\n"
        "\n"
        f"Your code is {ui.code(token['code'])}\n"
        "\n"
        "Type it into the page you are signing in from, or tap the button below "
        "and approve it there instead. The request drops itself in five minutes.\n"
        "\n"
        "If this was not you, say so below and change your password."
    )

    message = await ui.send_rich(client, token["telegram_id"], text, buttons=buttons)
    patch = {"status": "delivered"}
    if message is not None:
        patch["meta"] = dict(meta, chat_id=message.chat_id, message_id=message.id)
    await supa.update(TABLE_TOKENS, {"id": f"eq.{token['id']}"}, patch)


async def _warn_about_guessing(client) -> None:
    """Say something when wrong codes start piling up against a live challenge.

    The portal counts the wrong answers and burns the token at five. This turns
    that counter into something the account owner actually sees, because a
    stranger guessing at your second factor means they already have your
    password.
    """
    under_attack = await supa.select(
        TABLE_TOKENS,
        {
            "kind": "eq.push_otp",
            "status": "in.(pending,delivered)",
            "attempts": f"gte.{WARN_AFTER_ATTEMPTS}",
            "warned": "eq.false",
        },
        columns="*,qr_users(username)",
        limit=20,
    )
    await _for_each(under_attack, lambda token: _warn_one(client, token))


async def _warn_one(client, token: dict) -> None:
    await supa.update(TABLE_TOKENS, {"id": f"eq.{token['id']}"}, {"warned": True})
    if not token.get("telegram_id"):
        return
    if not await db.mark_seen(f"warn:{token['id']}"):
        return

    username = (token.get("qr_users") or {}).get("username") or "your account"
    await ui.send_rich(
        client,
        token["telegram_id"],
        "<b>Someone is guessing your code</b>\n"
        "\n"
        f"{token['attempts']} wrong codes have been tried against the sign in to "
        f"{ui.esc(username)} in the last few minutes. The request cancels itself "
        "after five.\n"
        "\n"
        "Whoever is doing this already knows your password, otherwise they would "
        "never have reached the code step. Change it as soon as you can, and do "
        "not approve anything you did not start.",
        buttons=ui.keyboard(ui.row(ui.portal_button("Change my password"))),
    )


async def _announce_completions(client) -> None:
    """Tell the user when something finished, or was taken away, on the portal."""
    finished = await supa.select(
        TABLE_TOKENS,
        {
            "kind": "in.(pull_otp,push_otp)",
            "status": "in.(used,confirmed,expired)",
            "notified": "eq.false",
        },
        columns="*,qr_users(username)",
        order="created_at.asc",
        limit=20,
    )
    # Time expiry is silent. Only a burned token is worth interrupting someone for.
    worth_saying = [
        token for token in finished
        if token.get("burned") or token["status"] in ("used", "confirmed")
    ]
    await _for_each(worth_saying, lambda token: _announce_one(client, token))


async def _announce_one(client, token: dict) -> None:
    await supa.update(TABLE_TOKENS, {"id": f"eq.{token['id']}"}, {"notified": True})
    if not token.get("telegram_id"):
        return
    if not await db.mark_seen(f"done:{token['id']}"):
        return

    username = (token.get("qr_users") or {}).get("username") or "your portal account"
    meta = token.get("meta") or {}

    if token.get("burned"):
        await _replace_prompt(
            client, token, meta,
            "<b>Sign in cancelled</b>\n"
            "\n"
            f"Five wrong codes were tried against the sign in to {ui.esc(username)}, "
            "so the request has been thrown away. Nobody got in.\n"
            "\n"
            "Change your password. Reaching the code step at all means the "
            "password was right.",
            buttons=ui.keyboard(ui.row(ui.portal_button("Change my password"))),
        )
        return

    if token["kind"] == "pull_otp":
        await ui.send_rich(
            client,
            token["telegram_id"],
            "<b>Connected</b>\n"
            "\n"
            f"This chat now belongs to {ui.esc(username)}. Your saved codes are "
            "reachable with /saved, and anything you generate here can be pushed "
            "straight to your account.\n"
            "\n"
            "Turn on sign in approval with /twofa if you want this chat to guard "
            "the portal login as well.",
            buttons=ui.keyboard(ui.row(ui.portal_button())),
        )
        return

    # A backup code finished this one, which means the chat was never part of
    # it. Usually that is the owner, locked out and using the way back in. When
    # it is not, this message is the only place they would ever find out.
    if meta.get("via") == "backup":
        left = meta.get("backup_left")
        remaining = (
            f"{left} backup {'code' if left == 1 else 'codes'} left."
            if isinstance(left, int)
            else "Check how many you have left on the portal."
        )
        await _replace_prompt(
            client, token, meta,
            "<b>Signed in with a backup code</b>\n"
            "\n"
            f"The sign in to {ui.esc(username)} was finished with one of your "
            "backup codes rather than from here. That code is now spent. "
            f"{ui.esc(remaining)}\n"
            "\n"
            "If that was not you, change your password and make a fresh set of "
            "codes, which throws away every one that still works.",
            buttons=ui.keyboard(ui.row(ui.portal_button("Open My QRs"))),
        )
        return

    await _replace_prompt(
        client, token, meta,
        "<b>Signed in</b>\n"
        "\n"
        f"The sign in to {ui.esc(username)} went through. Nothing else to do.",
    )


async def _replace_prompt(client, token, meta, text, buttons=None) -> None:
    """Rewrite the sign in prompt in place, or send a new message if it is gone."""
    chat_id, message_id = meta.get("chat_id"), meta.get("message_id")
    if chat_id and message_id:
        try:
            await client.edit_message(
                chat_id, message_id, text, parse_mode="html", buttons=buttons
            )
            await db.retire_message_buttons(chat_id, message_id)
            return
        except Exception:  # noqa: BLE001 - fall back to a fresh message
            log.debug("Could not edit the sign in prompt, sending a new one.")
    await ui.send_rich(client, token["telegram_id"], text, buttons=buttons)
