import {
    createClient
} from '@supabase/supabase-js';
import {
    ok,
    err
} from '../lib/response.js';

const supabase = createClient(
    process.env.SUPABASE_URL,
    process.env.SUPABASE_SERVICE_ROLE_KEY
);

export default async function handler(req, res) {
    if (req.method !== 'POST') return err(res, 'Method not allowed', 405);
    const {
        id,
        token
    } = req.body;

    const {
        data: authData,
        error: authErr
    } = await supabase.auth.getUser(token);
    if (authErr || !authData.user) return err(res, 'Unauthorised', 401);

    const {
        data: row,
        error: fetchErr
    } = await supabase
        .from('qr_codes')
        .select('image_path, user_id')
        .eq('id', id)
        .single();

    if (fetchErr || !row) return err(res, 'Not found', 404);
    if (row.user_id !== authData.user.id) return err(res, 'Forbidden', 403);

    await supabase.storage.from('qr_images').remove([row.image_path]);
    const {
        error
    } = await supabase.from('qr_codes').delete().eq('id', id);
    if (error) return err(res, error.message, 500);

    return ok(res, {
        ok: true
    });
}