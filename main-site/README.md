# QR Maker — by UwU Apps

A fast, browser-based QR code generator with no installs required.

## Features

- **Multiple QR types** — generate QR codes for URLs, plain text, WiFi credentials, calendar events, and contact cards (vCard)
- **uwu watermark** — every generated QR code has a subtle "uwu" watermark in Jua font at the centre, backed by high error-correction so the code still scans perfectly
- **Instant preview** — QR codes update live as you type
- **Download** — save any QR code as a PNG. Downloads and opened images go out as `blob:` URLs made in the page, so the storage address behind a saved code never shows. Saved images come from `/api/qr-image`, which checks the session and sends the PNG itself, and `/api/qr-list` no longer returns `image_url`, so the address never reaches the browser at all
- **Scan** — read a code from the camera, an image file, a drop or a paste, then rebuild it as a code of your own with one press, the same as the Telegram bot's `/decode`. Reading happens in the browser, natively where `BarcodeDetector` exists and with the bundled jsQR elsewhere. A payload the form tabs cannot hold in full (an extra phone number, a time zone) is rebuilt as Text, so the new code scans exactly like the old one
- **Save & manage** — log in to save QR codes to your account and access them any time from the My QRs panel
- **Save before you sign up** — saving works signed out too, keeping codes in this browser under My QRs. The first sign in on that device moves them onto the account, skipping anything it already has, so nothing is stored twice and nothing is lost
- **Works on every device you are signed in on** — a Telegram connection belongs to the account, so every open session shares it. Connect or disconnect on one and the others notice within a few seconds; logging out of one leaves the rest signed in
- **Themes** — seven colour themes to personalise the interface
- **PWA** — installable as a Progressive Web App on mobile and desktop

## QR Code Types

| Type    | What it encodes                                          |
| ------- | -------------------------------------------------------- |
| URL     | Any web address (https:// added automatically)           |
| Text    | Freeform plain text                                      |
| WiFi    | Network name, password, security type, and hidden flag   |
| Event   | Calendar event (VCALENDAR / iCal format)                 |
| Contact | Full vCard 3.0 with name, phone, email, org, and website |
| Scan    | Reads an existing code and rebuilds it in the matching tab |
