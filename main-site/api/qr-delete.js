import supabase from '../lib/supabase.js';
import { ok, err } from '../lib/response.js';
import { requireAuth } from '../lib/session.js';

export default async function handler(req, res) {
    if (req.method !== 'POST') return err(res, 'Method not allowed', 405);
    const { id, token } = req.body;

    let userId;
    try {
        req.headers['authorization'] = `Bearer ${token}`;
        ({ userId } = await requireAuth(req));
    } catch (e) {
        return err(res, e.message, e.status || 401);
    }

    const { data: row, error: fetchErr } = await supabase
        .from('qr_codes')
        .select('image_path, user_id')
        .eq('id', id)
        .single();

    if (fetchErr || !row) return err(res, 'Not found', 404);
    if (row.user_id !== userId) return err(res, 'Forbidden', 403);

    await supabase.storage.from('qr_images').remove([row.image_path]);
    const { error } = await supabase.from('qr_codes').delete().eq('id', id);
    if (error) return err(res, error.message, 500);

    return ok(res, { ok: true });
}
