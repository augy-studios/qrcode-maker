# QR Maker

A QR code generator that runs in a browser tab and in a Telegram chat, sharing
one account and one library of saved codes between them.

Made by [Augy Studios](https://github.com/augy-studios) under the UwU Apps
name. Live at **[qr.uwuapps.org](https://qr.uwuapps.org)**.

Every code it makes carries a small `uwu` mark at its centre, drawn in Jua and
backed by the highest error correction level, so the mark sits in the middle of
the symbol without stopping it from scanning.

## What is in here

| Directory | What it is |
| --------- | ---------- |
| [`main-site/`](main-site/) | The web app. Static front end, a handful of serverless functions, Supabase behind them |
| [`main-site/migrations/`](main-site/migrations/) | Numbered SQL applied by hand to the Supabase project |
| [`telegram-bot/`](telegram-bot/) | The Telegram bot, Python and Telethon, running on a VPS |

The two halves are deployed separately and independently. The site can run
without the bot. The bot can run without the site, minus the account features.
When both are up they share the same Supabase project.

## The web app

A single page, no build step, no framework. Open it and start typing.

- **Five kinds of code.** A link, plain text, WiFi credentials, a calendar
  event as iCalendar, or a contact card as vCard 3.0.
- **Live preview.** The code redraws as you type, on a canvas.
- **Accounts.** Register to save codes to your account and get at them from
  any device, under My QRs.
- **Themes.** Seven colour swatches and a light or dark mode, remembered
  between visits and applied before the first paint so nothing flashes.
- **Installable.** A progressive web app, so it can sit on a home screen and
  show up in the share sheet.

Hosted on Vercel. `main-site/api/` holds the serverless functions, `lib/` the
shared pieces they lean on, and everything else is served as it sits.

Read more in [main-site/README.md](main-site/README.md).

## The Telegram bot

Everything the site does, in a chat, plus the things a chat is better at.

- **Make a code** from a link or some text sent on its own, or step through a
  short builder for the shapes with several fields.
- **Read a code** by sending a photo of one and getting the text back.
- **Inline mode**, so a code can be generated inside any conversation without
  the bot being in it.
- **Your saved codes**, browsable and deletable from the chat once the account
  is connected, and new ones pushed straight to it.
- **Sign in approval.** With it turned on, a correct password is not enough to
  get into the portal. The attempt is held until you allow it in Telegram,
  either by typing six digits or by tapping through an approval page.
- **Backup codes**, ten of them, made on the portal and kept somewhere that is
  not your phone. Each one finishes a held back sign in on its own, for the day
  Telegram is not reachable at all.

It is a private chat bot and ignores groups. Codes it makes are identical, byte
for byte, to codes the site makes from the same input.

Read more in [telegram-bot/README.md](telegram-bot/README.md), and set it up
with [telegram-bot/SETUP.md](telegram-bot/SETUP.md).

## How the two connect

An account on the portal and an account on Telegram are joined by a record in
Supabase. There are four ways to create that join, depending on which side you
are standing on when you start.

| Route | Starts at | How it finishes |
| ----- | --------- | --------------- |
| Deep link | The portal | Opens Telegram, one confirmation tap, the page updates itself |
| Pull code | Telegram | Six digits typed into the portal, the bot confirms in the chat |
| Push code | A portal sign in | The bot delivers the digits unprompted, you type them into the page |
| Magic link | A portal sign in | The same message carries a button, and an approval page finishes it |

Every token is single use and short lived, wrong codes are counted, and a
password is never typed into a chat on any of the four routes.

**When the chat is gone.** Sign in approval leans on one account being
reachable, so an account with it turned on can hold ten backup codes, made
under My QRs and shown once. A backup code is typed into the same field the
six digits would go in and finishes the sign in without Telegram being involved
at all. Wrong ones burn the same attempt counter, only the hashes are stored,
and the bot reports in the chat whenever one is spent. Once back in, Disconnect
turns approval off and a fresh Telegram account can be linked.

## Running it yourself

Both halves are independent, so start with whichever you need.

**The web app** deploys to Vercel from `main-site/`. It needs a Supabase
project with `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` set, the `qr_users`,
`qr_sessions` and `qr_codes` tables, and a public `qr_images` storage bucket.
Add `TELEGRAM_BOT_USERNAME` as well if the bot is in play, and
`BACKUP_CODE_SECRET` if you would rather backup codes were not hashed with the
same key that reaches the database.

**The bot** runs on any machine that stays on. It is developed against Debian
13 and driven with tmux. Full walkthrough in
[telegram-bot/SETUP.md](telegram-bot/SETUP.md).

**The database** is shared. Apply the files in
[`main-site/migrations/`](main-site/migrations/) in order, in the Supabase SQL
editor, before connecting the two.

## Contributing

Issues and pull requests are welcome. Please read the
[Code of Conduct](CODE_OF_CONDUCT.md) first.

Two things worth knowing before changing code:

- The site and the bot build QR payloads separately, in JavaScript and in
  Python. They are written to agree exactly. Change one and change the other,
  or codes will stop matching across the two.
- Supabase schema changes belong in a new numbered file under
  `main-site/migrations/`, never as an edit to one already applied.

## Licence

[MIT](LICENSE), copyright Augy Studios.

The Jua font bundled at `telegram-bot/assets/Jua-Regular.ttf` is not covered by
that. It is licensed separately under the SIL Open Font License 1.1, with the
terms alongside it in `telegram-bot/assets/OFL.txt`.
