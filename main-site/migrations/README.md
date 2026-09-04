# Migrations

Numbered SQL files applied in order against the Supabase project behind the
portal. Every table added here keeps the existing `qr_` prefix so it sits
alongside `qr_users`, `qr_sessions` and `qr_codes` rather than beside them.

Apply one by opening the Supabase dashboard, going to the SQL editor, pasting
the file, and running it. Each file is written to be safe to run twice.

| File | What it adds |
| ---- | ------------ |
| `0001_telegram_bot_linking.sql` | `qr_telegram_links` and `qr_tokens`, backing the Telegram bot's account linking and two factor sign in |
| `0002_token_attempt_limits.sql` | Guessing limits: attempt counters on `qr_tokens`, plus `qr_rate_limits` and the `qr_rate_hit` function |
| `0003_backup_codes.sql` | `qr_backup_codes`, the single use codes that finish a sign in when Telegram cannot be reached |

Record which ones you have applied somewhere you will remember, since Supabase
does not track these for you unless you adopt the Supabase CLI.
