# QR Maker, the Telegram side

A Telethon bot that brings [QR Maker by UwU Apps](https://qr.uwuapps.org) into
Telegram. It makes the same codes the portal makes, reads codes back out of
images, and connects a Telegram account to a portal account so the two share
one library of saved codes.

Codes carry the same small `uwu` mark at the centre and are drawn at error
correction H by default, which is what gives the mark room to sit there without
breaking the scan.

- [What it does](#what-it-does)
- [Commands](#commands)
- [Connecting an account](#connecting-an-account)
- [Where the data lives](#where-the-data-lives)
- [Installing on Debian 13](#installing-on-debian-13)
- [Running it under tmux](#running-it-under-tmux)
- [Updating](#updating)
- [Troubleshooting](#troubleshooting)
- [The files](#the-files)

For first time setup with BotFather, the Supabase migration and the portal
changes, read [SETUP.md](SETUP.md) instead. This file assumes that is done.

## What it does

**Makes codes.** Send a link or some text on its own in a private chat and a
code comes straight back. WiFi credentials, contact cards and calendar events
have several fields each, so those get a short guided builder rather than one
long line of syntax to remember.

**Reads codes.** Send a photo or an image file and the payload comes back as
text, labelled with what it turned out to be. Reading needs the zbar system
library, and the bot says so plainly on start up if it is missing.

**Works inline.** Type the bot handle followed by some text in any chat, and a
code appears as a result you can send without leaving the conversation.

**Remembers your settings.** Size, quiet zone, error correction, watermark and
colour live in the bot's own database, per person, and apply everywhere
including inline results.

**Talks to your portal account.** Once connected, codes made here can be pushed
to your account with one tap, everything already saved is browsable from the
chat, and the chat can act as the second factor when you sign in to the portal.

**Keeps its buttons alive.** Every inline button the bot has ever sent still
works. Buttons carry an opaque id rather than their meaning, and the meaning
lives in SQLite, so a restart, a redeploy or a month of silence changes
nothing. Scroll back to a message from weeks ago and its buttons still respond.

## Commands

| Command | What it does |
| ------- | ------------ |
| `/start` | What the bot is, the full command list, and links to the portal and the donation page. Run it again at any time to get the list back |
| `/qr <text or link>` | Turns whatever follows into a code |
| `/wifi` | Builds a WiFi code over four short questions |
| `/contact` | Builds a contact card, vCard 3.0 |
| `/event` | Builds a calendar event, iCalendar |
| `/decode` | Explains how to read a code, or reads one from the image you replied to |
| `/link` | Connects this chat to your portal account |
| `/code` | Hands you six digits to type into the portal |
| `/unlink` | Disconnects the chat again |
| `/saved` | Browses the codes on your account, five at a time |
| `/twofa` | Turns sign in approval on or off |
| `/settings` | Size, quiet zone, error correction, watermark, colours |
| `/cancel` | Abandons a half finished builder |

You can skip `/qr` entirely and send the text on its own. Sending a photo is
likewise the same as `/decode`.

There is one more, `/health`, which is deliberately not in that table or in the
command menu. It reports uptime, the state of the token sweep, the last thing
the portal refused and the size of the local database, and it answers only the
Telegram ids in `OWNER_TELEGRAM_ID`. To anyone else it does not respond at all,
which is the least confusing way for an unlisted command to behave.

**This is a private chat bot.** It ignores everything sent from a group, and
BotFather is told to refuse group invitations outright. Inline mode still works
in any conversation, because that does not require the bot to be a member of
it.

## Connecting an account

There are four routes, and none of them ever asks for your portal password in a
chat. Which one you get depends on where you started.

**Deep link, portal to Telegram.** Sign in on the portal, open My QRs, press
Connect Telegram. The portal writes a token and opens a start link. The bot
asks for one confirmation tap and writes the link. The portal tab, which has
been polling, updates by itself.

**Pull code, Telegram to portal.** Send `/code` and get six digits. Type them
into the same panel on the portal. Useful when the portal is open on a laptop
and Telegram is on your phone. The bot confirms in the chat the moment the
digits land.

**Push code, sign in approval.** With `/twofa` on, a correct password is no
longer enough. The portal holds the session back and records the attempt, the
bot delivers the digits unprompted along with the address and browser the
attempt came from, and you type them into the page you are signing in from. Get
a prompt you did not ask for and there is a button to refuse it, which tells the
waiting browser to give up and tells you to change your password.

**Magic link, no digits at all.** That same push message carries a Sign In
button. It opens a page naming the account, the address and the browser behind
the attempt, with one button to approve. The browser waiting on it is then let
in without anything being typed. The page exists on purpose: a URL that has
travelled through a chat can be fetched by a forwarded message or a link
scanner, so a bare visit shows the page and only the button press acts.

Tokens are short lived and single use. Deep links and pull codes last ten
minutes, sign in challenges last five.

Wrong codes are counted. Three wrong answers against a live sign in and the bot
warns the account owner unprompted, since reaching the code step at all means
somebody already has the password. Five and the request is thrown away. Pull
codes are limited the other way round, ten redemption attempts per portal
account every ten minutes, because a wrong guess there matches no record and so
cannot be counted against one.

## Where the data lives

Two stores, split by who needs to read them.

**SQLite, on the VPS, at `data/bot.db`.** Everything that belongs to the bot
alone. The button registry, guided builder progress, per person rendering
preferences, recent payloads behind the Save buttons, the rate limiter, and
de-duplication keys for the token sweep. None of it leaves the machine.

**Supabase, shared with the portal.** Only what both sides have to see. The
account mapping in `qr_telegram_links`, the one time tokens in `qr_tokens`, the
guessing counters in `qr_rate_limits`, and the existing `qr_users`,
`qr_sessions`, `qr_codes` and the `qr_images` bucket that the portal already
owned. Those are added by
[`0001_telegram_bot_linking.sql`](../main-site/migrations/0001_telegram_bot_linking.sql)
and [`0002_token_attempt_limits.sql`](../main-site/migrations/0002_token_attempt_limits.sql).

The bot never stores a password and never sees one. WiFi passwords typed into
the builder are used to construct the payload and are dropped as soon as the
code is sent.

Leave `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` empty and the bot runs happily
without any of the account features, generating and reading codes as normal.

## Installing on Debian 13

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip tmux git libzbar0t64
```

`libzbar0t64` is the reading half. On Debian 12 and older the package is called
`libzbar0`. Skip it and everything except `/decode` still works.

```bash
git clone <your repository> qrcode-maker
cd qrcode-maker/telegram-bot

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

cp .env.example .env
nano .env          # fill in the five values, see SETUP.md
chmod +x run.sh
```

Confirm the environment adds up before going near Telegram:

```bash
./run.sh check
```

That prints what it found, applies the SQLite schema, and exits. It does not
connect to anything.

The Jua font is committed under `assets/`, so the watermark comes out in the
same face the portal uses with nothing to install. A browser can pull a webfont
from Google; a server cannot, which is why the file lives in the repository.
It is licensed under the SIL Open Font License, and `assets/OFL.txt` is the
copy that goes with it. `./run.sh check` says which font is actually in use.

## Running it under tmux

```bash
./run.sh start      # start it detached
./run.sh attach     # watch it live, detach with ctrl-b then d
./run.sh logs       # follow data/bot.log instead
./run.sh status     # is it up
./run.sh restart    # after pulling changes
./run.sh stop
```

The session is called `uwuqr`. Set `QRBOT_SESSION` to change that if you run
more than one instance on the same box.

Attaching and detaching leaves the bot alone. Closing your SSH connection
leaves it alone too, which is the point. What does stop it is rebooting the
VPS, so either start it again by hand afterwards or write a small systemd unit
that runs `run.sh start` at boot.

To push the command list to Telegram at the same time as starting, which saves
pasting it into BotFather:

```bash
./run.sh start --sync-commands
```

Do that once, not on every start. The list only changes when the commands do.

## Updating

```bash
cd qrcode-maker
git pull
cd telegram-bot
.venv/bin/pip install -r requirements.txt
./run.sh restart
```

The SQLite schema applies itself on every start, so there is no migration step
on the bot side. Supabase migrations are numbered files under
`main-site/migrations/` and are applied by hand in the Supabase SQL editor.

Buttons sent before an update keep working, because their meaning was in the
database rather than in the running process.

## Troubleshooting

**It exits straight away.** Run `./run.sh check`. A missing environment
variable is named explicitly. Otherwise read `data/bot.log`, which holds the
same output the console had.

**Nothing happens when you message it.** Confirm it is running with
`./run.sh status`. If you are messaging it from a group, that is the reason:
the bot only answers private chats. `/health` is also silent to anyone whose
Telegram id is not in `OWNER_TELEGRAM_ID`.

**Reading codes is off.** Install `libzbar0t64`, then reinstall pyzbar inside
the virtual environment with `.venv/bin/pip install --force-reinstall pyzbar`.
The library is loaded at import, so the bot has to be restarted after.

**A button says the bot has no record of it.** The `data/` directory was wiped
or the database was replaced. Run the command again to get fresh buttons.

**Linking fails or `/saved` reports the portal is not answering.** Check
`SUPABASE_URL` and `SUPABASE_SERVICE_KEY`, and confirm both migrations in
`main-site/migrations/` have actually been applied. A missing table shows up in
the log as a PostgREST error naming it, and `/health` shows the last refusal
verbatim.

**Sign in prompts never arrive.** The sweep only runs when Supabase is
configured, and the log says so on start up. Confirm `/twofa` is on for that
account and that the portal is running the patched `api/auth.js`.

**The watermark looks wrong.** `assets/Jua-Regular.ttf` is missing, so the
renderer fell back to whatever system font it could find. `./run.sh check`
reports which one. Restore the file from the repository.

## The files

```text
bot.py                entry point, callback routing, start up and shut down
config.py             environment, constants, paths
db.py                 SQLite, the bot's own state
dispatch.py           button kind registry, command patterns, the private gate
runtime.py            live process state, read by the health command
ui.py                 send_rich and friends, plus every shared string
supa.py               async Supabase client over PostgREST and storage
qrgen.py              payload builders, renderer, watermark, detection
linking.py            the four link flows and the token sweep
handlers_core.py      start, help, link, unlink, code, twofa, cancel, health
handlers_qr.py        generating, the guided builders, decoding, inline mode
handlers_account.py   saved codes and settings
run.sh                tmux wrapper
requirements.txt      pinned to the Telethon 1.x line
.env.example          every variable, documented
assets/               Jua-Regular.ttf and its licence
```

On the portal side, this bot also relies on `main-site/api/telegram-link.js`,
`main-site/lib/telegram.js`, the sign in hold back in `main-site/api/auth.js`,
the connect panel in `index.html`, `script.js` and `style.css`, and the two
migrations under `main-site/migrations/`.
