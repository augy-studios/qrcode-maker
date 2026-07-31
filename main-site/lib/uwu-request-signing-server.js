import crypto from 'crypto';

const MAX_SKEW_MS = 30 * 1000;

function hmacHex(keyString, message) {
    return crypto.createHmac('sha256', keyString).update(message).digest('hex');
}

// "no body" must match the client's rule: absent, or stringifies to '{}'.
// Vercel's body parser sets req.body = {} for GET/DELETE even with no payload sent.
function bodyHashFor(req, signingKey) {
    const body = req.body;
    const s = body == null ? '' : (typeof body === 'string' ? body : JSON.stringify(body));
    if (s === '' || s === '{}') return 'empty';
    return hmacHex(signingKey, s);
}

function timingSafeEqualHex(a, b) {
    const bufA = Buffer.from(a || '', 'hex');
    const bufB = Buffer.from(b || '', 'hex');
    if (bufA.length !== bufB.length) return false;
    return crypto.timingSafeEqual(bufA, bufB);
}

export async function verifySignedRequest(req, supabase) {
    const token = req.headers['x-request-token'];
    const ts = req.headers['x-request-ts'];
    const keyId = req.headers['x-key-id'];

    if (!token || !ts || !keyId) return { valid: false, reason: 'Missing signing headers' };
    if (Math.abs(Date.now() - Number(ts)) > MAX_SKEW_MS) return { valid: false, reason: 'Stale timestamp' };

    const { data: keyRow, error: keyErr } = await supabase
        .from('uwu_signing_keys')
        .select('id, session_token, signing_key, expires_at')
        .eq('id', keyId)
        .maybeSingle();
    if (keyErr || !keyRow) return { valid: false, reason: 'Unknown signing key' };
    if (new Date(keyRow.expires_at) < new Date()) return { valid: false, reason: 'Signing key expired' };

    const method = (req.method || 'GET').toUpperCase();
    const path = (req.url || '').split('?')[0];
    const bodyHash = bodyHashFor(req, keyRow.signing_key);
    const message = `${ts}:${method}:${path}:${bodyHash}`;
    const expected = hmacHex(keyRow.signing_key, message);

    if (!timingSafeEqualHex(expected, token)) return { valid: false, reason: 'Invalid signature' };

    const { data: used } = await supabase
        .from('uwu_used_request_tokens')
        .select('token')
        .eq('token', token)
        .maybeSingle();
    if (used) return { valid: false, reason: 'Replayed request' };

    await supabase.from('uwu_used_request_tokens').insert({
        token,
        session_token: keyRow.session_token,
        used_at: new Date().toISOString(),
    });

    return { valid: true, reason: '' };
}
