-- Migration 0004: making backup codes has to be approved in Telegram too.
--
-- Backup codes are a way past the second factor, so minting a set is worth as
-- much to an attacker as signing in is. A stolen portal session was enough to
-- make one, which handed whoever held it a permanent way back in long after the
-- session expired. Now the request is held the same way a sign in is: the chat
-- is asked first, and the codes are only drawn once it says yes.
--
-- That needs a fourth token kind, which means widening the check constraint.
--
--   backup_gen   The portal asks for a set. The bot puts the request in the
--                chat with Approve and Refuse. Approving marks it confirmed,
--                and the portal, still polling, mints the codes and shows them
--                exactly once.
--
-- Safe to run twice.

alter table qr_tokens drop constraint if exists qr_tokens_kind_check;

alter table qr_tokens add constraint qr_tokens_kind_check
    check (kind in ('deeplink', 'pull_otp', 'push_otp', 'backup_gen'));

comment on column qr_tokens.kind is
    'Which hand off this token belongs to: deeplink, pull_otp, push_otp or backup_gen.';
