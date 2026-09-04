# Setting the bot up

Start to finish: registering with BotFather, filling in the environment,
applying the Supabase migrations, and pointing the portal at it. Roughly half
an hour, most of which is waiting for BotFather.

Running it day to day is covered in [README.md](README.md).

1. [API credentials](#1-api-credentials)
2. [Creating the bot](#2-creating-the-bot)
3. [Profile text](#3-profile-text)
4. [The command list](#4-the-command-list)
5. [Behaviour switches](#5-behaviour-switches)
6. [The environment file](#6-the-environment-file)
7. [The Supabase migrations](#7-the-supabase-migrations)
8. [The portal side](#8-the-portal-side)
9. [First run](#9-first-run)
10. [Checking each flow](#10-checking-each-flow)

## 1. API credentials

Telethon is a full client library, so it needs an API id and hash of its own,
separate from the bot token. These identify the library, not the bot, and one
pair covers every bot you ever run.

1. Open <https://my.telegram.org> and sign in with your phone number.
2. Choose **API development tools**.
3. Fill the short form in. App title `QR Maker Bot`, short name `qrmakerbot`,
   platform Other. The URL field can stay empty.
4. Copy **App api_id** and **App api_hash**.

Those two become `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`. Treat the hash the
way you would a password.

## 2. Creating the bot

Open [@BotFather](https://t.me/BotFather) in Telegram and send `/newbot`.

- **Name**, shown at the top of the chat: `QR Maker`
- **Username**, must end in `bot`: `uwuqr_bot`

BotFather replies with the token, in the shape `1234567890:AA...`. That is
`TELEGRAM_BOT_TOKEN`. Anyone holding it controls the bot completely, so it goes
in `.env` and nowhere else. If it ever leaks, `/revoke` in BotFather issues a
new one.

## 3. Profile text

Still in BotFather. Each of these asks which bot first.

### `/setabouttext`

Shown on the profile card before anyone starts the bot. Telegram caps it at 120
characters.

```text
Make and read QR codes without leaving Telegram. Links, WiFi, contacts, events. Syncs with your QR Maker account.
```

### `/setdescription`

Shown on the empty chat screen, above the Start button. Capped at 512.

```text
Turn a link, a note, a WiFi network, a contact or a calendar event into a scannable code, right here in the chat. Send a photo of a code and get the text back out of it.

Connect your QR Maker account to browse everything you have saved, push new codes straight to it, and approve portal sign ins from here.

Every code is drawn at the highest error correction level and carries the uwu mark at its centre, exactly as the website does it.
```

### `/setuserpic`

Send `main-site/icons/qrmakericon1.png` from this repository. Telegram wants a
square image, and that one already is.

### `/setinlinegeo`

Leave this off. Nothing here uses location.

## 4. The command list

Send `/setcommands`, pick the bot, then paste this whole block in one message.
Order matters, since it is the order the menu shows.

```text
start - What this is, and the full command list
qr - Turn a link or some text into a code
wifi - Build a WiFi code step by step
contact - Build a contact card step by step
event - Build a calendar event step by step
decode - Read a QR code out of an image
link - Connect this chat to your portal account
code - Get a six digit code for the portal
unlink - Disconnect this chat from your account
saved - Browse the codes on your account
twofa - Turn sign in approval on or off
settings - Size, colour and error correction
cancel - Abandon whatever is half finished
```

There is no help entry. Running `/start` again prints the same list, so a
second command for it was just one more thing to keep in step.

The bot can also push that list itself, which avoids the two drifting apart:

```bash
./run.sh start --sync-commands
```

It reads `COMMAND_DESCRIPTIONS` in `ui.py`, which is the same list. Do it once
after changing the commands, not on every start.

## 5. Behaviour switches

### `/setinline`

Turn inline mode **on**. BotFather asks for a placeholder, which is the grey
text in the message box while someone is typing a query:

```text
Type something to turn it into a code
```

### `/setinlinefeedback`

Leave it **Disabled**. Nothing here collects usage statistics.

### `/setjoingroups`

Set this to **Disabled**. This is a private chat bot. It ignores group messages
in code regardless, and turning the invitation off means nobody wastes their
time adding it somewhere it will not answer.

### `/setprivacy`

Leave this **Enabled**, the default. With group invitations off it changes
nothing, but if the bot is ever already sitting in a group when that setting
gets flipped, privacy mode keeps it from being handed the conversation.

Inline mode is unaffected by both of these. It works in any chat without the
bot being a member of it.

## 6. The environment file

On the VPS:

```bash
cd qrcode-maker/telegram-bot
cp .env.example .env
nano .env
```

| Variable | Where it comes from | Needed |
| -------- | ------------------- | ------ |
| `TELEGRAM_API_ID` | my.telegram.org, step 1 | yes |
| `TELEGRAM_API_HASH` | my.telegram.org, step 1 | yes |
| `TELEGRAM_BOT_TOKEN` | BotFather, step 2 | yes |
| `SUPABASE_URL` | Supabase dashboard, Project settings, API | for account features |
| `SUPABASE_SERVICE_KEY` | same page, the `service_role` key | for account features |
| `DONATION_URL` | wherever you take donations | no, hides the button |
| `OWNER_TELEGRAM_ID` | your own id, from [@userinfobot](https://t.me/userinfobot) | no, disables `/health` |

`OWNER_TELEGRAM_ID` takes a comma separated list if more than one person should
be able to run the unlisted `/health` command. Left blank, that command answers
nobody.

The service key bypasses row level security. It is a root password for the
database, so it belongs on the VPS in `.env` and nowhere near a browser.
`.env` is gitignored. Keep it that way.

Leave both Supabase values blank and the bot still generates and reads codes.
The account commands say plainly that they are switched off.

The portal address is not an environment variable. It is `WEBAPP_URL` at the
top of `config.py`, currently `https://qr.uwuapps.org`. One line to change if
the site ever moves.

## 7. The Supabase migrations

Open the Supabase dashboard for the project the portal already uses, go to the
**SQL editor**, and run both files in order.

**[`0001_telegram_bot_linking.sql`](../main-site/migrations/0001_telegram_bot_linking.sql)**
adds two tables next to the ones the portal owns:

- **`qr_telegram_links`**, which Telegram account belongs to which portal
  account, and whether sign in approval is on
- **`qr_tokens`**, the short lived tokens behind all four linking routes

**[`0002_token_attempt_limits.sql`](../main-site/migrations/0002_token_attempt_limits.sql)**
puts a ceiling on guessing:

- three counter columns on `qr_tokens`, so a sign in challenge dies after five
  wrong codes and the bot can warn the owner at three
- **`qr_rate_limits`** and the `qr_rate_hit` function, which cap redemption
  attempts per portal account, since a wrong pull code matches no row and
  cannot be counted anywhere else

Every new table gets row level security switched on with no policies at all,
which shuts the anon key out entirely. The service key bypasses RLS, so the bot
and the portal's functions still reach them.

Both files are safe to run twice. Confirm afterwards under **Table editor**
that `qr_telegram_links`, `qr_tokens` and `qr_rate_limits` are all listed.

## 8. The portal side

All of it is committed. There is nothing to paste, and one variable to add.

### What changed on the site

| File | What it does |
| ---- | ------------ |
| `api/telegram-link.js` | The endpoint every flow talks to, plus the approval page behind the Sign In button |
| `lib/telegram.js` | Shared helpers: token minting, session activation, the guessing counters |
| `api/auth.js` | Holds a session back when sign in approval is on, instead of returning it |
| `index.html` | The connect panel in the My QRs modal, and the six digit step in the sign in modal |
| `script.js` | Drives both of those, including the poll that notices a one tap approval |
| `style.css` | Styles for the panel, using the existing colour tokens |

### The one variable

Add this to the Vercel project so the endpoint can build `t.me` links:

```text
TELEGRAM_BOT_USERNAME=uwuqr_bot
```

It falls back to `uwuqr_bot` when unset, so this only matters if the handle ever
changes. Redeploy after adding it.

### How the pieces meet

Opening **My QRs** while signed in now also asks the endpoint whether the
account is connected, and draws one of two things underneath the grid. When it
is not connected, a Connect Telegram button and a six digit field. When it is,
the account name, a switch for sign in approval, and a Disconnect button.

Signing in with approval turned on no longer returns a session. The auth
endpoint answers `{ twofa_required: true, challenge }`, the modal swaps to a six
digit field, and two things then race each other: whatever gets typed into that
field, and a poll watching for the Sign In button being pressed in the chat.
Whichever lands first signs you in, and the other stops.

The same answer carries `backup_available`, which decides whether the modal
offers the third way to finish: a backup code, typed into the same field.
Spending one never touches the bot, which is the point of it, and it is the
only thing standing between a lost phone and a lost account.

Making the set does touch the bot. The panel asks the portal, the portal writes
a `backup_gen` token, and the sweep puts a prompt in the chat with Make the
codes and No, I did not ask. The panel polls, and the codes are drawn only
after the tap, on the page that asked, once. Nothing about them travels through
Telegram. Set `BACKUP_CODE_SECRET` on the portal if you want them hashed with a
key that is not the service key; without it the service key is used, and either
way the codes themselves are never stored.

The approval page deserves a note. The Sign In button in Telegram opens a plain
`GET`, and a `GET` never approves anything. It draws a page naming the account,
the address and the browser, with a single button that `POST`s back. That split
exists because a URL sitting in a chat message can be fetched by things that
are not the recipient: a forwarded copy, a link scanner, an over eager preview.
Any of those would silently approve a sign in if the `GET` did the work.

## 9. First run

```bash
cd qrcode-maker/telegram-bot
./run.sh check
```

Read what it prints. Everything should say ready or configured, apart from
reading codes if you skipped `libzbar0t64`. The watermark line should say
**Jua, matching the portal**; anything else means `assets/Jua-Regular.ttf` did
not survive the clone. Then:

```bash
./run.sh start --sync-commands
./run.sh attach
```

The log should show it signing in, naming the portal, and confirming that
account features and the token sweep are on. Detach with ctrl-b then d, which
leaves it running.

## 10. Checking each flow

Work down the list. Each one exercises a different path.

**Generating.** Message the bot `hello world`. A code comes back with a caption
and two buttons.

**A builder.** Send `/wifi` and answer the four questions. Press Skip on the
password and confirm it still finishes.

**Buttons across a restart.** With a code on screen, run `./run.sh restart`,
wait for it to come up, then press Show the data on the old message. It should
answer. That is the button registry doing its job.

**Reading.** Send back a screenshot of a code the bot made. The payload should
come back as text.

**Inline.** In any chat type the bot handle, a space, then `hello`. A result
should appear.

**Deep link.** Sign in to the portal, open My QRs, press Connect Telegram.
Confirm in the chat. The portal panel should update on its own within a couple
of seconds.

**Pull code.** Disconnect, send `/code`, and type the digits into the portal
panel. The bot should confirm in the chat without being asked.

**Saving.** Generate something, press Save to my account, then check both
`/saved` and My QRs on the portal.

**Sign in approval, typed.** Turn `/twofa` on, sign out of the portal, sign
back in. The prompt should arrive unprompted within a few seconds, and the six
digit field should appear in the sign in modal. Type the digits.

**Sign in approval, tapped.** Same again, but ignore the field and press
Approve and sign in. You should get the confirmation page first, with the
address and browser named on it, and only the button on that page should let
you in. The browser you started from should follow within a couple of seconds.

**Refusing.** Start a sign in and press This was not me. The waiting browser
should give up rather than hang.

**Backup codes, asking.** With approval on, open My QRs and press Generate
backup codes. A prompt should arrive in the chat within a few seconds, naming
the address and browser. Press No, I did not ask first: the panel should say it
was refused and no codes should appear. Ask again and press Make the codes. Ten
should appear on the page, and the prompt in the chat should turn into a record
that a set was made.

**Backup codes, using one.** Sign out, sign back in, and press the line under
the code field instead of touching Telegram. Type one of the codes. You should
be let in, the count in the panel should drop by one, and the prompt in the chat
should turn into a notice saying a backup code was used. The same code should
not work a second time.

**Guessing.** Start a sign in and type three wrong codes. A warning should
arrive in the chat unprompted. Two more and the request should be thrown away
and the prompt in the chat replaced.

**Groups.** Add the bot to a group, if BotFather still lets you, and send it a
command. Nothing should happen at all.

**Health.** With your id in `OWNER_TELEGRAM_ID`, send `/health`. You should get
uptime, sweep state and database counts. From any other account it should stay
silent.

If any of those stall, `./run.sh logs` usually says why in the last few lines,
and `/health` names the last thing Supabase refused.
