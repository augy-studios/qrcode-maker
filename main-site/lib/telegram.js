import crypto from 'crypto';
import supabase from './supabase.js';

// Tables added by migrations/0001_telegram_bot_linking.sql.
export const LINKS = 'qr_telegram_links';
export const TOKENS = 'qr_tokens';

// Only used to build t.me start links. Override it if the bot handle changes.
export const BOT_USERNAME = process.env.TELEGRAM_BOT_USERNAME || 'uwuqr_bot';

export const DEEPLINK_TTL_MS = 10 * 60 * 1000;
export const PUSH_TTL_MS = 5 * 60 * 1000;
export const SESSION_TTL_MS = 30 * 24 * 60 * 60 * 1000;

export const iso = (offsetMs = 0) => new Date(Date.now() + offsetMs).toISOString();
export const randomHex = (bytes) => crypto.randomBytes(bytes).toString('hex');
export const digits = (count = 6) =>
    String(crypto.randomInt(0, 10 ** count)).padStart(count, '0');

/** Everything the sign in prompt tells the user about where the attempt came from. */
export function requestMeta(req) {
    const forwarded = (req.headers['x-forwarded-for'] || '').split(',')[0].trim();
    const agent = (req.headers['user-agent'] || '').slice(0, 120);
    return { ip: forwarded || null, agent: agent || null };
}

export async function linkForUser(userId) {
    const { data } = await supabase
        .from(LINKS)
        .select('user_id, telegram_id, telegram_username, twofa_enabled')
        .eq('user_id', userId)
        .maybeSingle();
    return data || null;
}

/**
 * Hold a password login back and ask the linked Telegram account to allow it.
 *
 * The session token is minted here but deliberately not written to qr_sessions.
 * It only becomes a real session once the user approves, either by typing the
 * six digits or by tapping the button in Telegram.
 */
export async function startTwofaChallenge(userId, telegramId, meta) {
    const row = {
        kind: 'push_otp',
        code: digits(6),
        status: 'pending',
        user_id: userId,
        telegram_id: telegramId,
        session_token: randomHex(32),
        approval_secret: randomHex(24),
        meta: meta || {},
        expires_at: iso(PUSH_TTL_MS),
    };

    const { data, error } = await supabase
        .from(TOKENS)
        .insert(row)
        .select('id, expires_at')
        .single();

    if (error) throw new Error('Could not start the sign in check.');
    return data;
}

/** Turn a pre minted session token into a session the browser can use. */
export async function activateSession(token) {
    const { error } = await supabase.from('qr_sessions').insert({
        token: token.session_token,
        user_id: token.user_id,
        expires_at: iso(SESSION_TTL_MS),
    });
    if (error) throw new Error('Could not open the session.');
    return token.session_token;
}

export async function markToken(id, status, extra = {}) {
    await supabase
        .from(TOKENS)
        .update({ status, consumed_at: new Date().toISOString(), ...extra })
        .eq('id', id);
}

export const isExpired = (token) =>
    !!token?.expires_at && new Date(token.expires_at) < new Date();

// How many wrong codes a single challenge tolerates before it is thrown away.
export const MAX_ATTEMPTS = 5;

/**
 * Record a wrong code against a challenge.
 *
 * Returns the new count and whether that was the one that burned it. The bot
 * watches the same columns, warns the owner part way through, and clears the
 * prompt once it is burned.
 */
export async function countWrongCode(token) {
    const attempts = (token.attempts || 0) + 1;
    const burned = attempts >= MAX_ATTEMPTS;

    await supabase
        .from(TOKENS)
        .update(
            burned
                ? {
                      attempts,
                      burned: true,
                      notified: false,
                      status: 'expired',
                      consumed_at: new Date().toISOString(),
                  }
                : { attempts }
        )
        .eq('id', token.id);

    return { attempts, burned, left: Math.max(0, MAX_ATTEMPTS - attempts) };
}

/**
 * Count one hit against a rolling window and say whether it is still allowed.
 *
 * Used where a wrong guess matches no row, so there is nothing to count on the
 * token itself. Fails open: if the counter is unreachable the request proceeds,
 * because locking people out of their own account over a broken counter is the
 * worse failure.
 */
export async function underRateLimit(key, limit, windowSeconds) {
    const { data, error } = await supabase.rpc('qr_rate_hit', {
        p_key: key,
        p_limit: limit,
        p_window: `${windowSeconds} seconds`,
    });
    if (error) return true;
    return data !== false;
}
