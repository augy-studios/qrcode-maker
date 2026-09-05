"""Payload builders and the renderer.

The payload builders mirror getFormData() in the portal's script.js, so a WiFi
code made here and one made on the site encode byte for byte the same string.
The renderer mirrors updateQR(): error correction H by default, a two module
quiet zone, and a small mark boxed out at the centre. The portal always draws
uwu there; here it is only the default, and /watermark swaps it per chat.

The watermark punches a hole in the symbol. Level H tolerates roughly thirty
percent damage, which is why the portal pins it there and why the settings
command warns when you drop below it. A longer mark makes a bigger hole, so the
text is length capped on the way in and the font shrinks rather than letting the
box run past WATERMARK_MAX_WIDTH_RATIO of the image.

The mark is drawn in Jua, the same face the portal loads from Google Fonts. A
browser can fetch a webfont; a server cannot, so the file is committed under
assets/ and read from disk. Everything after it in FONT_CANDIDATES is a safety
net for a broken install, and will not look like the site.
"""

import io
import logging
import re
from datetime import datetime
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont
from qrcode.constants import (
    ERROR_CORRECT_H,
    ERROR_CORRECT_L,
    ERROR_CORRECT_M,
    ERROR_CORRECT_Q,
)

from config import (
    FONT_CANDIDATES,
    WATERMARK_FONT,
    WATERMARK_FONT_RATIO,
    WATERMARK_MAX_WIDTH_RATIO,
    WATERMARK_PAD_RATIO,
    WATERMARK_TEXT,
    WATERMARK_TEXT_MAX,
)

log = logging.getLogger(__name__)

EC_LEVELS = {
    "L": ERROR_CORRECT_L,
    "M": ERROR_CORRECT_M,
    "Q": ERROR_CORRECT_Q,
    "H": ERROR_CORRECT_H,
}

_font_cache: dict[int, ImageFont.FreeTypeFont] = {}
_font_path: Path | None = None


# ------------------------------------------------------------------- fonts --


def _resolve_font_path() -> Path | None:
    """The first usable font on the list, remembered for reporting."""
    global _font_path
    if _font_path is not None:
        return _font_path
    for candidate in FONT_CANDIDATES:
        try:
            if candidate.exists():
                ImageFont.truetype(str(candidate), 24)
                _font_path = candidate
                return _font_path
        except OSError:
            continue
    return None


def _font(size: int):
    if size in _font_cache:
        return _font_cache[size]

    path = _resolve_font_path()
    if path is not None:
        font = ImageFont.truetype(str(path), size)
    else:
        log.warning("No TrueType font found, falling back to the bitmap default.")
        font = ImageFont.load_default()

    _font_cache[size] = font
    return font


def watermark_font_name() -> str:
    """What the watermark is actually being drawn in, for logs and health."""
    path = _resolve_font_path()
    if path is None:
        return "none, using the bitmap default"
    if path == WATERMARK_FONT:
        return "Jua, matching the portal"
    return f"{path.name}, not Jua, so it will not match the portal"


# -------------------------------------------------------- watermark text ---


class WatermarkTextError(ValueError):
    """The mark someone asked for cannot be drawn, in words they can read."""


def clean_watermark_text(value: str) -> str:
    """Normalise a mark, or explain why it will not do.

    A mark is one short line drawn into a hole in the middle of the symbol, so
    line breaks and runs of spaces have nowhere to go. They are folded into
    single spaces rather than refused, because someone typing two spaces meant
    one word gap, not an error message.
    """
    text = " ".join((value or "").split())
    if not text:
        raise WatermarkTextError(
            "That came through empty. Send the text you want in the middle of "
            "the code, or turn the mark off entirely in /settings."
        )
    if len(text) > WATERMARK_TEXT_MAX:
        raise WatermarkTextError(
            f"That is {len(text)} characters and the mark holds "
            f"{WATERMARK_TEXT_MAX}. Anything longer covers so much of the "
            "symbol that scanners start giving up on it."
        )
    return text


# -------------------------------------------------------- payload builders --


def build_url(value: str) -> str:
    """A bare domain gets https, matching what the portal does on the URL tab."""
    value = value.strip()
    if value and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        value = "https://" + value
    return value


def build_text(value: str) -> str:
    return value.strip()


def _wifi_escape(value: str) -> str:
    # The same four characters the portal escapes, in the same order, so a
    # network encoded here and one encoded on the site come out identical.
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace('"', '\\"')
    )


def build_wifi(ssid: str, password: str = "", security: str = "WPA",
               hidden: bool = False) -> str:
    ssid = ssid.strip()
    if not ssid:
        return ""
    # The portal's own values, verbatim: WPA, WPA3, WEP, nopass. Case is part
    # of the convention, so it is passed through rather than normalised.
    security = (security or "WPA").strip() or "WPA"
    if security.lower() == "nopass":
        password = ""
    return (
        f"WIFI:T:{security};S:{_wifi_escape(ssid)};"
        f"P:{_wifi_escape(password)};H:{'true' if hidden else 'false'};;"
    )


def _vcard_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def build_vcard(first: str = "", last: str = "", phone: str = "", email: str = "",
                org: str = "", url: str = "") -> str:
    first, last = first.strip(), last.strip()
    phone, email = phone.strip(), email.strip()
    org, url = org.strip(), url.strip()
    if not any((first, last, phone, email)):
        return ""

    full = " ".join(part for part in (first, last) if part)
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"FN:{_vcard_escape(full)}",
        f"N:{_vcard_escape(last)};{_vcard_escape(first)};;;",
    ]
    if org:
        lines.append(f"ORG:{_vcard_escape(org)}")
    if phone:
        lines.append(f"TEL;TYPE=CELL:{_vcard_escape(phone)}")
    if email:
        lines.append(f"EMAIL;TYPE=INTERNET:{_vcard_escape(email)}")
    if url:
        lines.append(f"URL:{_vcard_escape(url)}")
    lines.append("END:VCARD")
    return "\n".join(lines)


ICAL_INPUT_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d",
)


def parse_datetime(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ICAL_INPUT_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _ical_stamp(moment: datetime) -> str:
    return moment.strftime("%Y%m%dT%H%M%S")


def build_event(title: str, start: str = "", end: str = "", location: str = "",
                description: str = "") -> str:
    title = title.strip()
    if not title:
        return ""

    uid = f"qrmaker-{int(datetime.now().timestamp() * 1000)}@uwuapps"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//UwU Apps//QR Maker//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"SUMMARY:{_vcard_escape(title)}",
    ]
    start_at = parse_datetime(start)
    end_at = parse_datetime(end)
    if start_at:
        lines.append(f"DTSTART:{_ical_stamp(start_at)}")
    if end_at:
        lines.append(f"DTEND:{_ical_stamp(end_at)}")
    if location.strip():
        lines.append(f"LOCATION:{_vcard_escape(location.strip())}")
    if description.strip():
        lines.append(f"DESCRIPTION:{_vcard_escape(description.strip())}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\n".join(lines)


# ----------------------------------------------------------------- reading --

KIND_LABELS = {
    "url": "Link",
    "text": "Text",
    "wifi": "WiFi network",
    "contact": "Contact card",
    "calendar": "Calendar event",
}


def detect_kind(data: str) -> str:
    """Best guess at what a payload represents, used for labels and decoding."""
    head = data.lstrip()[:32].upper()
    if head.startswith("WIFI:"):
        return "wifi"
    if head.startswith("BEGIN:VCARD"):
        return "contact"
    if head.startswith("BEGIN:VCALENDAR") or head.startswith("BEGIN:VEVENT"):
        return "calendar"
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", data.strip()):
        return "url"
    if re.match(r"^(mailto|tel|sms|geo|bitcoin|matmsg):", data.strip(), re.I):
        return "url"
    return "text"


def describe(data: str) -> str:
    """A short human label for a payload, for captions and list rows."""
    kind = detect_kind(data)
    if kind == "wifi":
        match = re.search(r"S:((?:\\.|[^;])*)", data)
        ssid = match.group(1).replace("\\", "") if match else "unknown network"
        return f"WiFi for {ssid}"
    if kind == "contact":
        match = re.search(r"^FN:(.+)$", data, re.M)
        return f"Contact card for {match.group(1).strip()}" if match else "Contact card"
    if kind == "calendar":
        match = re.search(r"^SUMMARY:(.+)$", data, re.M)
        return f"Event, {match.group(1).strip()}" if match else "Calendar event"
    single_line = " ".join(data.split())
    return single_line[:80] + ("..." if len(single_line) > 80 else "")


# ---------------------------------------------------------------- renderer --


def render(data: str, *, size: int = 600, margin: int = 2, ec: str = "H",
           fg: str = "#000000", bg: str = "#ffffff",
           watermark: bool = True,
           watermark_text: str = WATERMARK_TEXT) -> bytes:
    """Render a payload to PNG bytes."""
    if not data:
        raise ValueError("Nothing to encode.")

    code = qrcode.QRCode(
        version=None,
        error_correction=EC_LEVELS.get(ec.upper(), ERROR_CORRECT_H),
        box_size=10,
        border=max(0, int(margin)),
    )
    code.add_data(data)
    code.make(fit=True)

    image = code.make_image(fill_color=fg, back_color=bg).convert("RGB")
    # Nearest neighbour keeps the module edges hard at any scale.
    image = image.resize((size, size), Image.NEAREST)

    text = " ".join((watermark_text or "").split())
    if watermark and text:
        _draw_watermark(image, size, fg, bg, text)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _draw_watermark(image: Image.Image, size: int, fg: str, bg: str,
                    text: str) -> None:
    draw = ImageDraw.Draw(image)
    pad = max(2, round(size * WATERMARK_PAD_RATIO))
    ceiling = size * WATERMARK_MAX_WIDTH_RATIO

    # The portal asks the browser for "bold Jua", and Jua only ships a Regular
    # weight, so what it actually gets is a synthesised bold. A thin stroke is
    # how the same thickening is done here.
    bold = _resolve_font_path() is not None

    # "uwu" at the portal's ratio always fits, so the first pass is the portal's
    # own geometry. A longer mark steps the size down until the box is back
    # inside the ceiling, which trades a smaller mark for a code that still
    # scans.
    font_size = max(8, round(size * WATERMARK_FONT_RATIO))
    while True:
        font = _font(font_size)
        stroke = max(1, round(font_size * 0.04)) if bold else 0
        left, top, right, bottom = draw.textbbox(
            (0, 0), text, font=font, stroke_width=stroke
        )
        text_w, text_h = right - left, bottom - top
        if text_w + pad * 2 <= ceiling or font_size <= 8:
            break
        font_size -= 1

    box_w, box_h = text_w + pad * 2, font_size + pad * 2
    centre_x, centre_y = size / 2, size / 2

    draw.rectangle(
        [
            round(centre_x - box_w / 2),
            round(centre_y - box_h / 2),
            round(centre_x + box_w / 2),
            round(centre_y + box_h / 2),
        ],
        fill=bg,
    )
    draw.text(
        (centre_x - left - text_w / 2, centre_y - top - text_h / 2),
        text,
        font=font,
        fill=fg,
        stroke_width=stroke,
        stroke_fill=fg,
    )


def render_with_prefs(data: str, prefs: dict) -> bytes:
    return render(
        data,
        size=int(prefs.get("size", 600)),
        margin=int(prefs.get("margin", 2)),
        ec=str(prefs.get("ec", "H")),
        fg=str(prefs.get("fg", "#000000")),
        bg=str(prefs.get("bg", "#ffffff")),
        watermark=bool(prefs.get("watermark", 1)),
        watermark_text=str(prefs.get("watermark_text") or WATERMARK_TEXT),
    )


def to_upload(data: bytes, filename: str = "qr.png") -> io.BytesIO:
    """Wrap PNG bytes so Telethon gives the upload a sensible file name."""
    buffer = io.BytesIO(data)
    buffer.name = filename
    return buffer
