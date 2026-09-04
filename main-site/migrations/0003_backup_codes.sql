-- Migration 0003: backup codes, the way back in when Telegram is gone.
--
-- Sign in approval leans on one chat. Lose the phone, the account, or the app
-- and a correct password is no longer enough to reach anything, including the
-- switch that turns approval off. Backup codes are the second key: ten single
-- use strings, printed once when they are made and never shown again.
--
-- They are checked against the same held back sign in as the six digits, so a
-- backup code still needs the password first, and wrong ones burn the same
-- attempt counter added in 0002.
--
-- Safe to run twice.

-- --------------------------------------------------------------------------
-- One row per code. Only the hash is kept, so a leak of this table is not a
-- pile of working codes.
--
-- The hash is an HMAC keyed by BACKUP_CODE_SECRET on the portal, falling back
-- to the Supabase service key when that is unset. Ten characters of random is
-- a small enough space that a plain digest could be ground through offline;
-- keying it means an attacker needs the database and the environment.
-- --------------------------------------------------------------------------

create table if not exists qr_backup_codes (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid        not null references qr_users(id) on delete cascade,
    code_hash  text        not null,
    created_at timestamptz not null default now(),
    used_at    timestamptz,
    -- Address and browser of whoever spent it, for the notice sent afterwards.
    used_meta  jsonb       not null default '{}'::jsonb
);

comment on table qr_backup_codes is
    'Single use recovery codes for accounts guarded by Telegram sign in approval.';
comment on column qr_backup_codes.code_hash is
    'Keyed HMAC of the normalised code. The code itself is shown once and never stored.';
comment on column qr_backup_codes.used_at is
    'When it was spent. Null means still live. Rows are kept so a set can be counted.';

-- Verification is one indexed lookup: the challenge already names the account,
-- so the pair is enough to find the row without scanning the user's set.
create unique index if not exists qr_backup_codes_lookup
    on qr_backup_codes (user_id, code_hash);

-- Counting what is left of a set, which the sign in page asks for every time.
create index if not exists qr_backup_codes_live
    on qr_backup_codes (user_id)
    where used_at is null;

-- --------------------------------------------------------------------------
-- Row level security, same reasoning as 0001: reached only by the service key,
-- and no policies at all is what shuts the anon key out.
-- --------------------------------------------------------------------------

alter table qr_backup_codes enable row level security;

-- --------------------------------------------------------------------------
-- Housekeeping. Spent codes are worth keeping for a while, because "you used a
-- backup code last month" is the sort of thing someone comes back to ask. They
-- are worthless once the set has been replaced, so this only clears the ones
-- nobody could look up any more.
-- --------------------------------------------------------------------------

create or replace function qr_backup_codes_prune() returns void
language sql as $$
    delete from qr_backup_codes
     where used_at is not null
       and used_at < now() - interval '180 days';
$$;
