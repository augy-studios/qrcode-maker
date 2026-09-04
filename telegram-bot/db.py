"""Local SQLite store.

This database holds state that belongs to the bot alone:

    buttons   every inline button ever sent, so a button keeps working after a
              restart instead of dying with the process memory
    flows     guided builder progress, so a half finished WiFi code survives
    prefs     per user rendering defaults
    history   recent payloads, so the Save button knows what to re-render
    rate      a small per user rate limit
    seen      de-duplication keys for the Supabase token sweep

Anything the portal also has to read lives in Supabase instead. See schema.sql.

SQLite calls are cheap but still blocking, so every public helper hands the
work to a worker thread and the event loop stays free.
"""

import asyncio
import json
import secrets
import sqlite3
import threading
import time

from config import DB_PATH, DEFAULT_PREFS, HISTORY_KEEP

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS buttons (
    id         TEXT PRIMARY KEY,
    kind       TEXT    NOT NULL,
    payload    TEXT    NOT NULL DEFAULT '{}',
    owner_id   INTEGER,
    chat_id    INTEGER,
    message_id INTEGER,
    state      TEXT    NOT NULL DEFAULT 'active',
    created_at INTEGER NOT NULL,
    expires_at INTEGER
);
CREATE INDEX IF NOT EXISTS buttons_owner ON buttons (owner_id, created_at);
CREATE INDEX IF NOT EXISTS buttons_msg   ON buttons (chat_id, message_id);

CREATE TABLE IF NOT EXISTS flows (
    telegram_id INTEGER PRIMARY KEY,
    flow        TEXT    NOT NULL,
    step        TEXT    NOT NULL,
    data        TEXT    NOT NULL DEFAULT '{}',
    chat_id     INTEGER,
    updated_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS prefs (
    telegram_id INTEGER PRIMARY KEY,
    size        INTEGER NOT NULL,
    margin      INTEGER NOT NULL,
    ec          TEXT    NOT NULL,
    watermark   INTEGER NOT NULL,
    fg          TEXT    NOT NULL,
    bg          TEXT    NOT NULL,
    updated_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    kind        TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS history_owner ON history (telegram_id, id DESC);

CREATE TABLE IF NOT EXISTS rate (
    telegram_id  INTEGER NOT NULL,
    bucket       TEXT    NOT NULL,
    count        INTEGER NOT NULL,
    window_start INTEGER NOT NULL,
    PRIMARY KEY (telegram_id, bucket)
);

CREATE TABLE IF NOT EXISTS seen (
    key     TEXT PRIMARY KEY,
    seen_at INTEGER NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        _conn.commit()
    return _conn


def _write(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    with _lock:
        conn = _connect()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur


def _read_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    with _lock:
        return _connect().execute(sql, params).fetchone()


def _read_all(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return _connect().execute(sql, params).fetchall()


def init() -> None:
    """Open the database and apply the schema. Called once at start up."""
    _connect()


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _now() -> int:
    return int(time.time())


# ----------------------------------------------------------------- buttons --
#
# A callback carries only an opaque id. The meaning lives in this table, which
# is why a button pressed months later, on the far side of several restarts,
# still does the right thing. Buttons never expire unless a caller asks for it,
# and the ones that do are the security sensitive sign in prompts.


def _create_button_sync(kind, payload, owner_id, ttl) -> str:
    button_id = secrets.token_hex(8)
    expires_at = _now() + ttl if ttl else None
    _write(
        "INSERT INTO buttons (id, kind, payload, owner_id, created_at, expires_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (button_id, kind, json.dumps(payload or {}), owner_id, _now(), expires_at),
    )
    return button_id


async def create_button(kind: str, payload: dict | None = None,
                        owner_id: int | None = None, ttl: int | None = None) -> bytes:
    """Register a button and return the callback data to attach to it."""
    button_id = await asyncio.to_thread(
        _create_button_sync, kind, payload, owner_id, ttl
    )
    return f"b:{button_id}".encode()


async def get_button(button_id: str) -> dict | None:
    row = await asyncio.to_thread(
        _read_one, "SELECT * FROM buttons WHERE id = ?", (button_id,)
    )
    if row is None:
        return None
    item = dict(row)
    item["payload"] = json.loads(item["payload"])
    return item


async def update_button(button_id: str, *, payload: dict | None = None,
                        state: str | None = None) -> None:
    sets, params = [], []
    if payload is not None:
        sets.append("payload = ?")
        params.append(json.dumps(payload))
    if state is not None:
        sets.append("state = ?")
        params.append(state)
    if not sets:
        return
    params.append(button_id)
    await asyncio.to_thread(
        _write, f"UPDATE buttons SET {', '.join(sets)} WHERE id = ?", tuple(params)
    )


async def bind_button_message(button_ids, chat_id: int, message_id: int) -> None:
    """Remember which message a set of buttons was attached to."""
    for button_id in button_ids:
        await asyncio.to_thread(
            _write,
            "UPDATE buttons SET chat_id = ?, message_id = ? WHERE id = ?",
            (chat_id, message_id, button_id),
        )


async def retire_message_buttons(chat_id: int, message_id: int) -> None:
    """Mark every button on one message as spent, after the message changes."""
    await asyncio.to_thread(
        _write,
        "UPDATE buttons SET state = 'spent' WHERE chat_id = ? AND message_id = ?",
        (chat_id, message_id),
    )


# ------------------------------------------------------------------- flows --


async def set_flow(telegram_id: int, flow: str, step: str,
                   data: dict, chat_id: int | None = None) -> None:
    await asyncio.to_thread(
        _write,
        "INSERT INTO flows (telegram_id, flow, step, data, chat_id, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(telegram_id) DO UPDATE SET"
        " flow = excluded.flow, step = excluded.step, data = excluded.data,"
        " chat_id = excluded.chat_id, updated_at = excluded.updated_at",
        (telegram_id, flow, step, json.dumps(data), chat_id, _now()),
    )


async def get_flow(telegram_id: int) -> dict | None:
    row = await asyncio.to_thread(
        _read_one, "SELECT * FROM flows WHERE telegram_id = ?", (telegram_id,)
    )
    if row is None:
        return None
    item = dict(row)
    item["data"] = json.loads(item["data"])
    return item


async def clear_flow(telegram_id: int) -> None:
    await asyncio.to_thread(
        _write, "DELETE FROM flows WHERE telegram_id = ?", (telegram_id,)
    )


# ------------------------------------------------------------------- prefs --


async def get_prefs(telegram_id: int) -> dict:
    row = await asyncio.to_thread(
        _read_one, "SELECT * FROM prefs WHERE telegram_id = ?", (telegram_id,)
    )
    if row is None:
        return dict(DEFAULT_PREFS)
    prefs = dict(row)
    prefs.pop("telegram_id", None)
    prefs.pop("updated_at", None)
    return prefs


async def set_prefs(telegram_id: int, prefs: dict) -> None:
    merged = dict(DEFAULT_PREFS)
    merged.update({k: v for k, v in prefs.items() if k in DEFAULT_PREFS})
    await asyncio.to_thread(
        _write,
        "INSERT INTO prefs (telegram_id, size, margin, ec, watermark, fg, bg,"
        " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(telegram_id) DO UPDATE SET"
        " size = excluded.size, margin = excluded.margin, ec = excluded.ec,"
        " watermark = excluded.watermark, fg = excluded.fg, bg = excluded.bg,"
        " updated_at = excluded.updated_at",
        (telegram_id, merged["size"], merged["margin"], merged["ec"],
         int(merged["watermark"]), merged["fg"], merged["bg"], _now()),
    )


async def reset_prefs(telegram_id: int) -> None:
    await asyncio.to_thread(
        _write, "DELETE FROM prefs WHERE telegram_id = ?", (telegram_id,)
    )


# ----------------------------------------------------------------- history --


def _add_history_sync(telegram_id, kind, payload) -> int:
    cur = _write(
        "INSERT INTO history (telegram_id, kind, payload, created_at)"
        " VALUES (?, ?, ?, ?)",
        (telegram_id, kind, payload, _now()),
    )
    row_id = cur.lastrowid
    _write(
        "DELETE FROM history WHERE telegram_id = ? AND id NOT IN ("
        " SELECT id FROM history WHERE telegram_id = ? ORDER BY id DESC LIMIT ?)",
        (telegram_id, telegram_id, HISTORY_KEEP),
    )
    return row_id


async def add_history(telegram_id: int, kind: str, payload: str) -> int:
    """Store a generated payload and return its id for a Save button."""
    return await asyncio.to_thread(_add_history_sync, telegram_id, kind, payload)


async def get_history(history_id: int) -> dict | None:
    row = await asyncio.to_thread(
        _read_one, "SELECT * FROM history WHERE id = ?", (history_id,)
    )
    return dict(row) if row else None


async def recent_history(telegram_id: int, limit: int = 10) -> list[dict]:
    rows = await asyncio.to_thread(
        _read_all,
        "SELECT * FROM history WHERE telegram_id = ? ORDER BY id DESC LIMIT ?",
        (telegram_id, limit),
    )
    return [dict(r) for r in rows]


# -------------------------------------------------------------- rate limit --


def _allow_sync(telegram_id, bucket, limit, window) -> bool:
    now = _now()
    row = _read_one(
        "SELECT count, window_start FROM rate WHERE telegram_id = ? AND bucket = ?",
        (telegram_id, bucket),
    )
    if row is None or now - row["window_start"] >= window:
        _write(
            "INSERT INTO rate (telegram_id, bucket, count, window_start)"
            " VALUES (?, ?, 1, ?)"
            " ON CONFLICT(telegram_id, bucket) DO UPDATE SET"
            " count = 1, window_start = excluded.window_start",
            (telegram_id, bucket, now),
        )
        return True
    if row["count"] >= limit:
        return False
    _write(
        "UPDATE rate SET count = count + 1 WHERE telegram_id = ? AND bucket = ?",
        (telegram_id, bucket),
    )
    return True


async def allow(telegram_id: int, bucket: str, limit: int, window: int) -> bool:
    """Consume one unit from a rolling window. False means the user is over."""
    return await asyncio.to_thread(_allow_sync, telegram_id, bucket, limit, window)


# -------------------------------------------------------------------- seen --


def _mark_seen_sync(key) -> bool:
    try:
        _write("INSERT INTO seen (key, seen_at) VALUES (?, ?)", (key, _now()))
    except sqlite3.IntegrityError:
        return False
    _write("DELETE FROM seen WHERE seen_at < ?", (_now() - 7 * 24 * 3600,))
    return True


# ------------------------------------------------------------------ health --


def _counts_sync() -> dict:
    tables = ("buttons", "flows", "prefs", "history", "rate", "seen")
    counts = {
        name: _read_one(f"SELECT COUNT(*) AS n FROM {name}")["n"] for name in tables
    }
    counts["buttons_active"] = _read_one(
        "SELECT COUNT(*) AS n FROM buttons WHERE state = 'active'"
    )["n"]
    page_count = _read_one("PRAGMA page_count")[0]
    page_size = _read_one("PRAGMA page_size")[0]
    counts["bytes"] = page_count * page_size
    return counts


async def counts() -> dict:
    """Row counts and on disk size, for the health command."""
    return await asyncio.to_thread(_counts_sync)


async def mark_seen(key: str) -> bool:
    """True the first time a key is offered, False every time after.

    The token sweep uses this so a Supabase row that is slow to change status
    is never acted on twice.
    """
    return await asyncio.to_thread(_mark_seen_sync, key)
