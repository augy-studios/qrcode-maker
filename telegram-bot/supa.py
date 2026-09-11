"""Thin async Supabase client over PostgREST and the storage API.

The portal's serverless functions use the JavaScript SDK. The bot talks to the
same project over plain HTTP instead, which keeps the dependency list short and
makes every query visible at the call site.

Authentication is the service role key, so row level security is bypassed. Only
ever pass values that came from a trusted place into a filter.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

import runtime
from config import (
    STORAGE_BUCKET,
    SUPABASE_ENABLED,
    SUPABASE_SERVICE_KEY,
    SUPABASE_URL,
)

log = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


class SupabaseError(RuntimeError):
    """A Supabase request came back with something other than success."""


class SupabaseDisabled(SupabaseError):
    """The account features were used without SUPABASE_URL and a service key."""

    def __init__(self):
        super().__init__("Supabase is not configured for this bot.")


def enabled() -> bool:
    return SUPABASE_ENABLED


def _http() -> httpx.AsyncClient:
    global _client
    if not SUPABASE_ENABLED:
        raise SupabaseDisabled()
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=SUPABASE_URL,
            timeout=httpx.Timeout(20.0, connect=10.0),
            headers={
                "apikey": SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            },
        )
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def in_seconds_iso(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def in_days_iso(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


# Requests that can be sent twice without changing the outcome. A PATCH or a
# DELETE names its rows in the filter, so repeating one after a timeout does
# the same thing again. A POST does not: the insert may have landed just before
# the reply was lost, and a second one would make a second row.
_REPEATABLE = frozenset({"GET", "HEAD", "PATCH", "DELETE"})


def _describe(exc: BaseException) -> str:
    # httpx's timeout errors carry no message, which leaves the log ending in
    # nothing. The class name says what happened.
    return str(exc) or type(exc).__name__


async def _rest(method: str, table: str, **kwargs) -> list[dict]:
    prefer = kwargs.pop("prefer", "return=representation")
    headers = {"Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer

    attempts = 2 if method in _REPEATABLE else 1
    for attempt in range(1, attempts + 1):
        try:
            response = await _http().request(
                method, f"/rest/v1/{table}", headers=headers, **kwargs
            )
            break
        except httpx.TransportError as exc:
            # The network, not the database: a stalled read, a dropped
            # connection, a DNS blip. One quick retry covers the usual case
            # of a single lost packet without masking a real outage.
            if attempt < attempts:
                log.debug("%s %s: %s, retrying once.", method, table, _describe(exc))
                await asyncio.sleep(0.5)
                continue
            runtime.note_supabase_error(f"{method} {table}: {_describe(exc)}")
            raise SupabaseError(
                f"{method} {table} could not be reached: {_describe(exc)}"
            ) from exc
        except httpx.HTTPError as exc:
            runtime.note_supabase_error(f"{method} {table}: {_describe(exc)}")
            raise SupabaseError(
                f"{method} {table} could not be reached: {_describe(exc)}"
            ) from exc

    if response.status_code >= 400:
        detail = f"{method} {table} returned {response.status_code}: {response.text[:400]}"
        runtime.note_supabase_error(detail)
        raise SupabaseError(detail)

    runtime.note_supabase_ok()
    if not response.content:
        return []
    payload = response.json()
    return payload if isinstance(payload, list) else [payload]


# ------------------------------------------------------------------ tables --


async def select(table: str, filters: dict | None = None, *, columns: str = "*",
                 order: str | None = None, limit: int | None = None,
                 offset: int | None = None) -> list[dict]:
    params: dict[str, str] = {"select": columns}
    params.update(filters or {})
    if order:
        params["order"] = order
    if limit is not None:
        params["limit"] = str(limit)
    if offset is not None:
        params["offset"] = str(offset)
    return await _rest("GET", table, params=params)


async def select_one(table: str, filters: dict, *, columns: str = "*") -> dict | None:
    rows = await select(table, filters, columns=columns, limit=1)
    return rows[0] if rows else None


async def count(table: str, filters: dict | None = None) -> int:
    """Exact row count, read from the Content-Range header.

    Selects everything rather than a named column, because not every table here
    has an id. The Range header caps the body at a single row regardless.
    """
    params: dict[str, str] = {"select": "*"}
    params.update(filters or {})
    response = await _http().get(
        f"/rest/v1/{table}",
        params=params,
        headers={"Prefer": "count=exact", "Range": "0-0"},
    )
    if response.status_code >= 400:
        raise SupabaseError(f"count {table}: {response.text[:400]}")
    content_range = response.headers.get("content-range", "")
    total = content_range.split("/")[-1]
    return int(total) if total.isdigit() else 0


async def insert(table: str, row: dict) -> dict | None:
    rows = await _rest("POST", table, json=row)
    return rows[0] if rows else None


async def upsert(table: str, row: dict, on_conflict: str) -> dict | None:
    rows = await _rest(
        "POST", table,
        json=row,
        params={"on_conflict": on_conflict},
        prefer="return=representation,resolution=merge-duplicates",
    )
    return rows[0] if rows else None


async def update(table: str, filters: dict, patch: dict) -> list[dict]:
    return await _rest("PATCH", table, params=filters, json=patch)


async def delete(table: str, filters: dict) -> list[dict]:
    return await _rest("DELETE", table, params=filters)


# ----------------------------------------------------------------- storage --


async def upload(path: str, data: bytes, content_type: str = "image/png",
                 bucket: str = STORAGE_BUCKET) -> str:
    """Put an object in the bucket and return its public URL."""
    response = await _http().post(
        f"/storage/v1/object/{bucket}/{path}",
        content=data,
        headers={"Content-Type": content_type, "x-upsert": "false"},
    )
    if response.status_code >= 400:
        raise SupabaseError(f"upload {path}: {response.text[:400]}")
    return public_url(path, bucket)


def public_url(path: str, bucket: str = STORAGE_BUCKET) -> str:
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}"


async def remove(paths: list[str], bucket: str = STORAGE_BUCKET) -> None:
    if not paths:
        return
    response = await _http().request(
        "DELETE",
        f"/storage/v1/object/{bucket}",
        json={"prefixes": paths},
        headers={"Content-Type": "application/json"},
    )
    if response.status_code >= 400:
        # A missing object is not worth failing a delete over.
        log.warning("storage remove %s: %s", paths, response.text[:200])
