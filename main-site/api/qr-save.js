import supabase from '../lib/supabase.js';
import { err } from '../lib/response.js';
import { requireAuth } from '../lib/session.js';

export default async function handler(req, res) {
    if (req.method !== 'POST') return err(res, 'Method not allowed', 405);

    let body;
    try {
        body = req.body;
    } catch {
        return err(res, 'Invalid body', 400);
    }

    const { token, data, type, imageDataUrl } = body || {};
    if (!token || !imageDataUrl) return err(res, 'Missing fields', 400);

    let userId;
    try {
        req.headers['authorization'] = `Bearer ${token}`;
        ({ userId } = await requireAuth(req));
    } catch (e) {
        return err(res, e.message, e.status || 401);
    }

    // Decode base64 data URL to buffer
    const base64 = imageDataUrl.replace(/^data:image\/\w+;base64,/, '');
    const buffer = Buffer.from(base64, 'base64');
    const path = `${userId}/${Date.now()}.png`;

    const { error: uploadErr } = await supabase.storage
        .from('qr_images')
        .upload(path, buffer, {
            contentType: 'image/png',
            upsert: false,
        });
    if (uploadErr) return err(res, uploadErr.message, 500);

    const { data: urlData } = supabase.storage.from('qr_images').getPublicUrl(path);

    const { error: dbErr } = await supabase.from('qr_codes').insert({
        user_id: userId,
        type,
        qr_data: data,
        data_preview: (data || '').slice(0, 80),
        image_path: path,
        image_url: urlData.publicUrl,
    });
    if (dbErr) return err(res, dbErr.message, 500);

    res.status(200).json({ ok: true });
}
