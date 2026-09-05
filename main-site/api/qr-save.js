import supabase from '../lib/supabase.js';
import { ok, err } from '../lib/response.js';
import { requireAuth } from '../lib/session.js';

// A device that was not signed in keeps its codes in localStorage. Signing in
// hands the pile over here, and the merge is the same rule the bot applies when
// a chat links: anything the account already holds is skipped, everything else
// is uploaded, and nothing ends up stored twice.
//
// Sameness is decided on qr_data, the encoded payload itself, because that is
// the one field every writer agrees on. The site and the bot build a WiFi or a
// vCard payload byte for byte identically, so the same network saved in both
// places really is one row.
const MERGE_MAX = 50;

export default async function handler(req, res) {
    if (req.method !== 'POST') return err(res, 'Method not allowed', 405);

    let body;
    try {
        body = req.body;
    } catch {
        return err(res, 'Invalid body', 400);
    }

    const { token, action, data, type, imageDataUrl, items } = body || {};
    if (!token) return err(res, 'Missing fields', 400);

    let userId;
    try {
        req.headers['authorization'] = `Bearer ${token}`;
        ({ userId } = await requireAuth(req));
    } catch (e) {
        return err(res, e.message, e.status || 401);
    }

    if (action === 'merge') return merge(res, userId, items);

    if (!imageDataUrl) return err(res, 'Missing fields', 400);
    try {
        await store(userId, data, type, imageDataUrl);
    } catch (e) {
        return err(res, e.message, 500);
    }
    return ok(res, { ok: true });
}

/** Upload one PNG and record the row that points at it. */
async function store(userId, data, type, imageDataUrl) {
    const base64 = String(imageDataUrl).replace(/^data:image\/\w+;base64,/, '');
    const buffer = Buffer.from(base64, 'base64');
    const path = `${userId}/${Date.now()}-${Math.random().toString(36).slice(2, 8)}.png`;

    const { error: uploadErr } = await supabase.storage
        .from('qr_images')
        .upload(path, buffer, {
            contentType: 'image/png',
            upsert: false,
        });
    if (uploadErr) throw new Error(uploadErr.message);

    const { data: urlData } = supabase.storage.from('qr_images').getPublicUrl(path);

    const { error: dbErr } = await supabase.from('qr_codes').insert({
        user_id: userId,
        type,
        qr_data: data,
        data_preview: (data || '').slice(0, 80),
        image_path: path,
        image_url: urlData.publicUrl,
    });
    if (dbErr) throw new Error(dbErr.message);
}

/** Fold a device's saved codes into the account, skipping what it already has. */
async function merge(res, userId, items) {
    if (!Array.isArray(items)) return err(res, 'Nothing to merge', 400);
    if (items.length > MERGE_MAX) {
        return err(res, `That is more than ${MERGE_MAX} codes at once`, 413);
    }

    const { data: existing, error } = await supabase
        .from('qr_codes')
        .select('qr_data')
        .eq('user_id', userId);
    if (error) return err(res, error.message, 500);

    const seen = new Set((existing || []).map((row) => row.qr_data));
    let added = 0;
    let skipped = 0;
    const failed = [];

    for (const item of items) {
        const payload = item && item.data;
        if (!payload || !item.imageDataUrl) {
            skipped += 1;
            continue;
        }
        // Two identical codes in one batch are one code, so the set is grown as
        // it goes rather than only read at the start.
        if (seen.has(payload)) {
            skipped += 1;
            continue;
        }
        try {
            await store(userId, payload, item.type, item.imageDataUrl);
            seen.add(payload);
            added += 1;
        } catch {
            // Report it rather than losing it. The client keeps whatever comes
            // back in this list and tries again next time.
            failed.push(item.id);
        }
    }

    return ok(res, { added, skipped, failed });
}
