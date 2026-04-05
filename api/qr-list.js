import supabase from '../lib/supabase.js';
import { ok, err } from '../lib/response.js';
import { requireAuth } from '../lib/session.js';

export default async function handler(req, res) {
    if (req.method !== 'GET') return err(res, 'Method not allowed', 405);

    const token = req.query.token;
    if (!token) return err(res, 'Missing token', 401);

    let userId;
    try {
        req.headers['authorization'] = `Bearer ${token}`;
        ({ userId } = await requireAuth(req));
    } catch (e) {
        return err(res, e.message, e.status || 401);
    }

    const { data: qrs, error } = await supabase
        .from('qr_codes')
        .select('id, type, data_preview, image_url, created_at')
        .eq('user_id', userId)
        .order('created_at', { ascending: false });

    if (error) return err(res, error.message, 500);
    return ok(res, { qrs });
}
