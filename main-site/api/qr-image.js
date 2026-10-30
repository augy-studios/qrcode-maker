import supabase from '../lib/supabase.js';
import { err } from '../lib/response.js';
import { requireAuth } from '../lib/session.js';

// The picture behind a saved code, sent as the PNG itself. The page shows it
// through a blob: URL, so the storage address it lives at never reaches the
// browser: not in the list, not in the page, not in a tab or a download.
//
// GET with the session in the Authorization header rather than the query
// string, so the token stays out of URLs and logs, and the worker can still
// keep the last copy for offline use.
export default async function handler(req, res) {
    if (req.method !== 'GET') return err(res, 'Method not allowed', 405);

    const id = req.query.id;
    if (!id) return err(res, 'Missing id', 400);

    let userId;
    try {
        ({ userId } = await requireAuth(req));
    } catch (e) {
        return err(res, e.message, e.status || 401);
    }

    // Matching on the owner as well as the id means someone else's code reads
    // as missing, the same as one that does not exist.
    const { data: row, error } = await supabase
        .from('qr_codes')
        .select('image_path')
        .eq('id', id)
        .eq('user_id', userId)
        .maybeSingle();
    if (error) return err(res, error.message, 500);
    if (!row || !row.image_path) return err(res, 'Not found', 404);

    const { data: file, error: dlErr } = await supabase.storage
        .from('qr_images')
        .download(row.image_path);
    if (dlErr || !file) return err(res, 'Image unavailable', 404);

    const buffer = Buffer.from(await file.arrayBuffer());
    res.setHeader('Content-Type', file.type || 'image/png');
    res.setHeader('Content-Length', buffer.length);
    // A saved image never changes under its id. Private keeps it out of the
    // CDN, which must never hand one account's code to another.
    res.setHeader('Cache-Control', 'private, max-age=86400');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    return res.status(200).send(buffer);
}
