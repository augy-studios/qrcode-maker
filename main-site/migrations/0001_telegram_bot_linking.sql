-- Migration 0001: Telegram bot linking and two factor sign in.
--
-- Run this once in the Supabase SQL editor for the project the portal uses.
-- It is written to be safe to re-run: every statement is guarded.
--
-- The portal already owns qr_users, qr_sessions, qr_codes and the qr_images
-- storage bucket. This file adds only the two tables that the bot and the
-- portal have to share. Everything the bot alone cares about (button state,
-- wizard progress, preferences) lives in the bot's local SQLite database and
-- never touches Supabase.

-- --------------------------------------------------------------------------
-- Which Telegram account belongs to which portal account.
-- One portal account maps to at most one Telegram account, and the reverse.
-- --------------------------------------------------------------------------

create table if not exists qr_telegram_links (
    user_id            uuid primary key references qr_users(id) on delete cascade,
    telegram_id        bigint      not null unique,
    telegram_username  text,
    telegram_name      text,
    twofa_enabled      boolean     not null default false,
    linked_at          timestamptz not null default now()
);

comment on table qr_telegram_links is
    'Telegram account to portal account mapping, plus the two factor opt in.';

-- --------------------------------------------------------------------------
-- Short lived tokens covering all four hand off directions.
--
--   deeplink   portal issues it, user carries it into Telegram in a start link
--   pull_otp   bot issues it, user types it into the portal
--   push_otp   portal issues it during sign in, bot delivers it unprompted
--
-- The magic link is not a separate kind. It is the approval_secret on a
-- push_otp row, handed to the user as a one tap button instead of digits.
-- --------------------------------------------------------------------------

create table if not exists qr_tokens (
    id                 uuid primary key default gen_random_uuid(),
    kind               text not null
                       check (kind in ('deeplink', 'pull_otp', 'push_otp')),
    code               text not null,
    status             text not null default 'pending'
                       check (status in ('pending', 'delivered', 'confirmed',
                                         'used', 'denied', 'expired')),
    user_id            uuid references qr_users(id) on delete cascade,
    telegram_id        bigint,
    telegram_username  text,

    -- Pre minted portal session, activated only once the user approves.
    session_token      text,
    -- Secret behind the one tap Sign In button. Never shown as text.
    approval_secret    text,

    -- Set by whichever side has already told the user what happened.
    notified           boolean     not null default false,

    meta               jsonb       not null default '{}'::jsonb,
    created_at         timestamptz not null default now(),
    consumed_at        timestamptz,
    expires_at         timestamptz not null
);

comment on table qr_tokens is
    'One time tokens for account linking and for two factor sign in.';

-- A code only has to be unique while it is still live, so six digit codes can
-- be reused freely once they are spent or expired.
create unique index if not exists qr_tokens_live_code
    on qr_tokens (kind, code)
    where status in ('pending', 'delivered');

create index if not exists qr_tokens_status_kind
    on qr_tokens (kind, status, expires_at);

create index if not exists qr_tokens_approval
    on qr_tokens (approval_secret)
    where approval_secret is not null;

create index if not exists qr_tokens_user
    on qr_tokens (user_id, created_at desc);

-- --------------------------------------------------------------------------
-- Row level security.
--
-- Both tables are reached only by the service key, which is held by the bot
-- and by the portal's serverless functions. The service key bypasses RLS, so
-- turning RLS on with no policies at all is what shuts the anon key out.
-- --------------------------------------------------------------------------

alter table qr_telegram_links enable row level security;
alter table qr_tokens         enable row level security;

-- --------------------------------------------------------------------------
-- Housekeeping. The bot expires stale tokens on every sweep, so this is only
-- a floor for rows nobody ever came back for. Schedule it with pg_cron if the
-- extension is available, or leave it as a manual clean up.
-- --------------------------------------------------------------------------

create or replace function qr_tokens_prune() returns void
language sql as $$
    delete from qr_tokens where created_at < now() - interval '7 days';
$$;
