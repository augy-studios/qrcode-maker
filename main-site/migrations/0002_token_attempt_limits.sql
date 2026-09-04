-- Migration 0002: guessing limits on the one time codes.
--
-- Six digits is a small space. Without a ceiling on wrong answers, a five
-- minute window is long enough to be worth attacking. Two mechanisms, because
-- the two codes fail differently.
--
--   push_otp   The attacker holds the challenge id, so every wrong guess lands
--              on a known row and can be counted there. Counting per row also
--              lets the bot warn the account owner that it is happening.
--
--   pull_otp   A wrong guess matches no row at all, so there is nothing to
--              count against. Those are limited per signed in portal account
--              instead, which is the only identity a redeem attempt carries.
--
-- Safe to run twice.

alter table qr_tokens
    add column if not exists attempts int     not null default 0,
    add column if not exists warned   boolean not null default false,
    add column if not exists burned   boolean not null default false;

comment on column qr_tokens.attempts is
    'Wrong codes offered against this token.';
comment on column qr_tokens.warned is
    'The owner has already been told that someone is guessing.';
comment on column qr_tokens.burned is
    'Cancelled by repeated wrong codes, rather than by time or by choice.';

-- The bot sweeps for tokens under attack, so make that lookup cheap.
create index if not exists qr_tokens_under_attack
    on qr_tokens (kind, status, attempts)
    where attempts > 0;

-- --------------------------------------------------------------------------
-- A general purpose counter, keyed by whatever the caller wants to limit on.
-- Only the redeem endpoint uses it today, keyed on the portal account id.
-- --------------------------------------------------------------------------

create table if not exists qr_rate_limits (
    key          text        primary key,
    count        int         not null default 0,
    window_start timestamptz not null default now()
);

comment on table qr_rate_limits is
    'Rolling counters for endpoints that cannot count against a token row.';

alter table qr_rate_limits enable row level security;

-- Count one hit against a key and report whether the caller is still under the
-- limit. The window restarts once it has fully elapsed, so this is a fixed
-- window rather than a sliding one, which is plenty here.
create or replace function qr_rate_hit(
    p_key    text,
    p_limit  int,
    p_window interval
) returns boolean
language plpgsql as $$
declare
    v_count int;
begin
    insert into qr_rate_limits as r (key, count, window_start)
         values (p_key, 1, now())
    on conflict (key) do update
        set count        = case when r.window_start < now() - p_window
                                then 1 else r.count + 1 end,
            window_start = case when r.window_start < now() - p_window
                                then now() else r.window_start end
      returning r.count into v_count;

    return v_count <= p_limit;
end;
$$;

-- Housekeeping for counters nobody came back to.
create or replace function qr_rate_prune() returns void
language sql as $$
    delete from qr_rate_limits where window_start < now() - interval '1 day';
$$;
