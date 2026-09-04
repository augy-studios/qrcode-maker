import crypto from 'crypto';
import supabase from './supabase.js';

// Table added by migrations/0003_backup_codes.sql.
export const BACKUP_CODES = 'qr_backup_codes';

// Ten is enough to cover a lost phone twice over without being a list nobody
// bothers to keep.
export const CODE_COUNT = 10;

// No 0, 1, i, l or o. These get written on paper and typed back in months
// later, and the pairs that look alike are the ones that cost people the
// account they were trying to protect.
const ALPHABET = '23456789abcdefghjkmnpqrstuvwxyz';
const HALF = 5;
const LENGTH = HALF * 2;

/**
 * Key behind the stored hash.
 *
 * Ten characters of this alphabet is about fifty bits, which is plenty against
 * anyone guessing at the endpoint but not against someone grinding a plain
 * digest offline. Keying the hash means a stolen database is not enough on its
 * own. Set BACKUP_CODE_SECRET to separate the two; without it the service key
 * already present in the environment does the job.
 */
const hashKey = () =>
    process.env.BACKUP_CODE_SECRET || process.env.SUPABASE_SERVICE_KEY || '';

/** Codes are shown grouped and typed back in however the user feels like it. */
export const normalise = (raw) =>
    String(raw || '')
        .toLowerCase()
        .replace(/[^a-z0-9]/g, '');

export const hashCode = (code) =>
    crypto.createHmac('sha256', hashKey()).update(`qr-backup:${code}`).digest('hex');

function mintCode() {
    let out = '';
    for (let i = 0; i < LENGTH; i++) {
        out += ALPHABET[crypto.randomInt(0, ALPHABET.length)];
    }
    return `${out.slice(0, HALF)}-${out.slice(HALF)}`;
}

/** How many codes this account has left, and when the set was made. */
export async function backupSummary(userId) {
    const { data, error } = await supabase
        .from(BACKUP_CODES)
        .select('created_at, used_at')
        .eq('user_id', userId);

    if (error || !data) return { total: 0, remaining: 0, generated_at: null };

    return {
        total: data.length,
        remaining: data.filter((row) => !row.used_at).length,
        generated_at: data.reduce(
            (newest, row) =>
                !newest || row.created_at > newest ? row.created_at : newest,
            null
        ),
    };
}

export async function remainingCount(userId) {
    const { count, error } = await supabase
        .from(BACKUP_CODES)
        .select('id', { count: 'exact', head: true })
        .eq('user_id', userId)
        .is('used_at', null);
    return error ? 0 : count || 0;
}

/**
 * Replace the account's whole set and hand back the plaintext, once.
 *
 * Regenerating throws away whatever was there, spent or not. A half known set
 * is worse than no set at all, so there is no way to top one up.
 */
export async function generateCodes(userId) {
    await supabase.from(BACKUP_CODES).delete().eq('user_id', userId);

    const codes = [];
    const rows = [];
    while (codes.length < CODE_COUNT) {
        const code = mintCode();
        const code_hash = hashCode(normalise(code));
        if (rows.some((row) => row.code_hash === code_hash)) continue;
        codes.push(code);
        rows.push({ user_id: userId, code_hash });
    }

    const { error } = await supabase.from(BACKUP_CODES).insert(rows);
    if (error) throw new Error('Could not save the backup codes.');

    return codes;
}

/**
 * Spend one code, if it is one of this account's and still live.
 *
 * Returns how many are left, or null when the code is wrong or already used.
 * The claim carries the same `used_at is null` filter as the lookup, so two
 * requests racing on one code leave exactly one winner.
 */
export async function consumeCode(userId, raw, meta = {}) {
    const code = normalise(raw);
    if (code.length !== LENGTH) return null;

    const { data: row } = await supabase
        .from(BACKUP_CODES)
        .select('id')
        .eq('user_id', userId)
        .eq('code_hash', hashCode(code))
        .is('used_at', null)
        .maybeSingle();
    if (!row) return null;

    const { data: claimed } = await supabase
        .from(BACKUP_CODES)
        .update({ used_at: new Date().toISOString(), used_meta: meta || {} })
        .eq('id', row.id)
        .is('used_at', null)
        .select('id')
        .maybeSingle();
    if (!claimed) return null;

    return { remaining: await remainingCount(userId) };
}

/** Nothing is left to fall back on, so the panel can say so plainly. */
export async function clearCodes(userId) {
    await supabase.from(BACKUP_CODES).delete().eq('user_id', userId);
}
