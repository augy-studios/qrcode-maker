import supabase from '../../lib/supabase.js';
import { ok, err } from '../../lib/response.js';
import crypto from 'crypto';

const GUEST_TTL_MS = 10 * 60 * 1000;

export default async function handler(req, res) {
    if (req.method !== 'GET') return err(res, 'Method not allowed', 405);

    const origin = req.headers['origin'];
    if (origin) {
        const allowed = (process.env.ALLOWED_ORIGINS || '').split(',').map((o) => o.trim()).filter(Boolean);
        if (!allowed.includes(origin)) return err(res, 'Origin not allowed', 403);
    }

    const appId = req.query.app || 'unknown';
    const signingKey = crypto.randomBytes(32).toString('hex');
    const sessionToken = crypto.randomUUID();
    const expires = new Date(Date.now() + GUEST_TTL_MS);

    const { data: row, error } = await supabase
        .from('uwu_signing_keys')
        .insert({
            session_token: sessionToken,
            signing_key: signingKey,
            is_guest: true,
            app_id: appId,
            expires_at: expires.toISOString(),
        })
        .select('id')
        .single();
    if (error) return err(res, error.message, 500);

    return ok(res, { key_id: row.id, signing_key: signingKey });
}
