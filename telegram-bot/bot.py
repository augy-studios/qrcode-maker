#!/usr/bin/env python3
"""Entry point.

    python bot.py                 run the bot
    python bot.py --sync-commands set the command list, then run
    python bot.py --check         verify the environment and exit

Run it under tmux on the VPS. See README.md for the exact incantation.
"""

import argparse
import asyncio
import logging
import re
import sys
import time

from telethon import TelegramClient, events, functions, types

import config
import db
import dispatch
import handlers_account
import handlers_core
import handlers_qr
import linking
import runtime
import supa
import ui

log = logging.getLogger("qrbot")

CALLBACK_PREFIX = re.compile(rb"^b:")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)

    file_handler = logging.FileHandler(config.LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [stream, file_handler]

    # Telethon is chatty at INFO and has nothing useful to say most of the time.
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def register_callbacks(client: TelegramClient) -> None:
    """One handler for every inline button the bot has ever sent.

    The callback carries an opaque id. The row behind it says what the button
    means, who may press it, and whether it has expired. That indirection is
    why a button still works after the process has been restarted, redeployed,
    or left alone for a month.
    """

    @client.on(events.CallbackQuery(pattern=CALLBACK_PREFIX))
    async def on_callback(event):
        button_id = event.data[2:].decode(errors="ignore")
        button = await db.get_button(button_id)

        if button is None:
            await event.answer(
                "That button belongs to a message this bot no longer has any "
                "record of. Run the command again.",
                alert=True,
            )
            return

        if button["owner_id"] and button["owner_id"] != event.sender_id:
            await event.answer("That one is not yours to press.", alert=True)
            return

        if button["expires_at"] and button["expires_at"] < int(time.time()):
            await event.answer("That request has expired.", alert=True)
            return

        handler = dispatch.get(button["kind"])
        if handler is None:
            log.warning("No handler registered for button kind %r", button["kind"])
            await event.answer(
                "That button does something this version does not know about.",
                alert=True,
            )
            return

        try:
            await handler(event, button)
        except supa.SupabaseDisabled:
            await event.answer("Account features are switched off here.", alert=True)
        except supa.SupabaseError:
            log.exception("Supabase failed while handling %r", button["kind"])
            await event.answer(
                "The portal is not answering right now. Try again shortly.",
                alert=True,
            )
        except Exception:  # noqa: BLE001 - a bad button must not kill the bot
            log.exception("Button %r failed", button["kind"])
            await event.answer("Something went wrong with that one.", alert=True)


async def sync_commands(client: TelegramClient) -> None:
    """Push the command list to Telegram, matching what SETUP.md describes."""
    commands = [
        types.BotCommand(command=name, description=description)
        for name, description in ui.COMMAND_DESCRIPTIONS
    ]
    await client(functions.bots.SetBotCommandsRequest(
        scope=types.BotCommandScopeDefault(),
        lang_code="",
        commands=commands,
    ))
    log.info("Command list synced, %d entries.", len(commands))


async def run(args) -> None:
    db.init()

    client = TelegramClient(
        str(config.SESSION_PATH),
        config.TELEGRAM_API_ID,
        config.TELEGRAM_API_HASH,
        connection_retries=None,      # keep retrying, a VPS reboots its network
        retry_delay=5,
        auto_reconnect=True,
    )

    handlers_core.register(client)
    handlers_qr.register(client)
    handlers_account.register(client)
    register_callbacks(client)

    await client.start(bot_token=config.TELEGRAM_BOT_TOKEN)
    me = await client.get_me()
    log.info("Signed in as bot id %s.", me.id)
    log.info("Portal at %s.", config.WEBAPP_URL)
    log.info(
        "Account features %s.",
        "enabled" if supa.enabled() else "off, no Supabase credentials",
    )
    log.info(
        "Reading codes %s.",
        "enabled" if handlers_qr.DECODING_AVAILABLE else "off, zbar not installed",
    )
    log.info(
        "Health command %s.",
        f"available to {len(config.OWNER_TELEGRAM_IDS)} owner id(s)"
        if config.OWNER_TELEGRAM_IDS else "off, OWNER_TELEGRAM_ID not set",
    )
    log.info("Private chats only. Group messages are ignored.")
    log.info("Button kinds registered: %s", ", ".join(dispatch.known_kinds()))

    if args.sync_commands:
        await sync_commands(client)

    sweeper = None
    if supa.enabled():
        sweeper = asyncio.create_task(linking.poll_forever(client))
        runtime.sweeper = sweeper

    try:
        await client.run_until_disconnected()
    finally:
        if sweeper is not None:
            sweeper.cancel()
            try:
                await sweeper
            except asyncio.CancelledError:
                pass
        await supa.close()
        db.close()
        log.info("Stopped cleanly.")


def check() -> int:
    """Confirm the environment adds up, without touching Telegram."""
    print(f"API id         {config.TELEGRAM_API_ID}")
    print(f"Bot token      set, {len(config.TELEGRAM_BOT_TOKEN)} characters")
    print(f"Portal         {config.WEBAPP_URL}")
    print(f"Donation link  {config.DONATION_URL or 'not set, button hidden'}")
    print(f"Supabase       {'configured' if supa.enabled() else 'not configured'}")
    print(
        "Health command "
        + (", ".join(str(i) for i in sorted(config.OWNER_TELEGRAM_IDS))
           if config.OWNER_TELEGRAM_IDS else "off, OWNER_TELEGRAM_ID not set")
    )
    print(f"Database       {config.DB_PATH}")
    print(f"Session        {config.SESSION_PATH}.session")

    try:
        import qrcode  # noqa: F401
        from PIL import Image  # noqa: F401

        print("Generating     ready")
    except ImportError as exc:
        print(f"Generating     BROKEN, {exc}")
        return 1

    try:
        from pyzbar import pyzbar  # noqa: F401

        print("Reading        ready")
    except Exception as exc:  # noqa: BLE001
        print(f"Reading        off, {exc}")

    db.init()
    db.close()
    print("SQLite         schema applied")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="QR Maker Telegram bot")
    parser.add_argument("--sync-commands", action="store_true",
                        help="push the command list to Telegram on start up")
    parser.add_argument("--check", action="store_true",
                        help="verify the environment and exit")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="log at debug level")
    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.check:
        return check()

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        log.info("Interrupted, shutting down.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
