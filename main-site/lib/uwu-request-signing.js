// Shared client-side request signing for UwU Apps PWAs. Classic script - exposes window.UwuSigning.

const LS_KEY = 'uwu_signing_key';
const SS_KEY = 'uwu_signing_key';

function storeSigningKey(signingKey, keyId, persistent = false) {
    const payload = JSON.stringify({ signingKey, keyId });
    if (persistent) {
        localStorage.setItem(LS_KEY, payload);
        sessionStorage.removeItem(SS_KEY);
    } else {
        sessionStorage.setItem(SS_KEY, payload);
        localStorage.removeItem(LS_KEY);
    }
}

function getSigningKey() {
    const fromLocal = localStorage.getItem(LS_KEY);
    if (fromLocal) {
        try { return JSON.parse(fromLocal); } catch { /* fall through */ }
    }
    const fromSession = sessionStorage.getItem(SS_KEY);
    if (fromSession) {
        try { return JSON.parse(fromSession); } catch { /* fall through */ }
    }
    return null;
}

function clearSigningKey() {
    localStorage.removeItem(LS_KEY);
    sessionStorage.removeItem(SS_KEY);
}

async function initGuestKey(appId) {
    if (getSigningKey()) return;
    const res = await fetch(`/api/auth/guest-key?app=${encodeURIComponent(appId)}`);
    if (!res.ok) throw new Error('Failed to obtain guest signing key');
    const { key_id, signing_key } = await res.json();
    storeSigningKey(signing_key, key_id, false);
}

function toHex(buf) {
    return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function hmacHex(keyString, message) {
    const enc = new TextEncoder();
    const cryptoKey = await crypto.subtle.importKey(
        'raw', enc.encode(keyString), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
    );
    const sig = await crypto.subtle.sign('HMAC', cryptoKey, enc.encode(message));
    return toHex(sig);
}

// "no body" must match the server's rule exactly: absent, or stringifies to '{}'.
function normalizeBody(body) {
    if (body == null) return null;
    const s = typeof body === 'string' ? body : JSON.stringify(body);
    return s === '{}' || s === '' ? null : s;
}

async function signedFetch(url, options = {}) {
    const key = getSigningKey();
    if (!key) throw new Error('No signing key available - cannot send signed request');

    const method = (options.method || 'GET').toUpperCase();
    const path = new URL(url, location.origin).pathname;
    const ts = Date.now().toString();

    const bodyStr = normalizeBody(options.body);
    const bodyHash = bodyStr !== null ? await hmacHex(key.signingKey, bodyStr) : 'empty';

    const message = `${ts}:${method}:${path}:${bodyHash}`;
    const token = await hmacHex(key.signingKey, message);

    const headers = new Headers(options.headers || {});
    headers.set('X-Request-Token', token);
    headers.set('X-Request-TS', ts);
    headers.set('X-Key-ID', key.keyId);

    return fetch(url, { ...options, headers, body: bodyStr !== null ? bodyStr : options.body });
}

window.UwuSigning = { storeSigningKey, getSigningKey, clearSigningKey, initGuestKey, signedFetch };
