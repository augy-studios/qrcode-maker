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
        .select('user_id, telegram_id, telegram_username, twofa_enabled, linked_at')
        .eq('user_id', userId)
        .maybeSingle();
    return data || null;
}

/** A unique violation, which for these inserts always means the code collided. */
const isDuplicate = (error) =>
    error?.code === '23505' || /duplicate key/i.test(error?.message || '');

/**
 * Hold a password login back and ask the linked Telegram account to allow it.
 *
 * The session token is minted here but deliberately not written to qr_sessions.
 * It only becomes a real session once the user approves, either by typing the
 * six digits or by tapping the button in Telegram.
 *
 * One challenge per sign in, never one per account: two browsers signing in at
 * the same moment each get their own, each with its own digits and its own
 * pre minted session, and approving one has no bearing on the other. The only
 * thing they share is the live code index, which is unique across every open
 * challenge, so a collision is possible and is retried here rather than being
 * reported to the second browser as a failure. The bot does the same when it
 * mints a pull code.
 */
export async function startTwofaChallenge(userId, telegramId, meta) {
    for (let attempt = 0; attempt < 5; attempt++) {
        const { data, error } = await supabase
            .from(TOKENS)
            .insert({
                kind: 'push_otp',
                code: digits(6),
                status: 'pending',
                user_id: userId,
                telegram_id: telegramId,
                session_token: randomHex(32),
                approval_secret: randomHex(24),
                meta: meta || {},
                expires_at: iso(PUSH_TTL_MS),
            })
            .select('id, expires_at')
            .single();

        if (!error) return data;
        if (!isDuplicate(error)) break;
    }
    throw new Error('Could not start the sign in check.');
}

/**
 * Ask the linked chat to allow a fresh set of backup codes.
 *
 * A set of backup codes is a standing way past the second factor, so making one
 * is worth as much to a thief as a sign in is, and a session on its own is not
 * enough to authorise it. Nothing is minted here: the row only records that the
 * account asked, and the codes are drawn once the chat has said yes.
 *
 * The code column is filled with hex nobody ever sees. This kind is approved by
 * tapping a button, never by typing digits, and hex keeps it out of the way of
 * the six digit codes sharing the live code index.
 */
export async function startBackupRequest(userId, telegramId, meta) {
    // Only the newest request stays live, so a forgotten prompt in the chat
    // cannot be tapped later to mint a set nobody is watching for.
    await supabase
        .from(TOKENS)
        .update({ status: 'expired' })
        .eq('kind', 'backup_gen')
        .eq('user_id', userId)
        .in('status', ['pending', 'delivered']);

    const { data, error } = await supabase
        .from(TOKENS)
        .insert({
            kind: 'backup_gen',
            code: randomHex(16),
            status: 'pending',
            user_id: userId,
            telegram_id: telegramId,
            meta: meta || {},
            expires_at: iso(PUSH_TTL_MS),
        })
        .select('id, expires_at')
        .single();

    if (error) throw new Error('Could not ask Telegram about that.');
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
