"""Live process state, for the health command to read.

Deliberately tiny and dependency free, so anything can import it without
dragging half the bot along. Nothing here is persisted. A restart resets all of
it, which is exactly what makes it useful for answering "how is it doing right
now".
"""

import time

STARTED_AT: float = time.time()

# Set by bot.py once the sweep task exists, so the health command can say
# whether it is still alive rather than assuming it is.
sweeper = None

# The last thing Supabase refused, and when. Cleared by the next success, so a
# blank here means the portal has been answering since that moment.
last_supabase_error: str | None = None
last_supabase_error_at: float | None = None
last_supabase_ok_at: float | None = None


def note_supabase_error(message: str) -> None:
    global last_supabase_error, last_supabase_error_at
    last_supabase_error = message[:300]
    last_supabase_error_at = time.time()


def note_supabase_ok() -> None:
    global last_supabase_ok_at
    last_supabase_ok_at = time.time()


def uptime_seconds() -> float:
    return time.time() - STARTED_AT


def human_duration(seconds: float) -> str:
    """A rough, readable duration. Precision past the minute is not useful."""
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"

    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes and not days:
        parts.append(f"{minutes}m")
    return " ".join(parts) or "under a minute"


def ago(moment: float | None) -> str:
    return "never" if moment is None else f"{human_duration(time.time() - moment)} ago"


def sweeper_state() -> str:
    if sweeper is None:
        return "not running, no portal credentials"
    if sweeper.cancelled():
        return "cancelled"
    if sweeper.done():
        exception = sweeper.exception()
        return f"stopped, {type(exception).__name__}" if exception else "stopped"
    return "running"
