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
    if (req.method !== 'GET') return err(res, 'Method not allowed', 405);
    const token = req.query.token;
    if (!token) return err(res, 'Missing token', 401);

    const {
        data: authData,
        error: authErr
    } = await supabase.auth.getUser(token);
    if (authErr || !authData.user) return err(res, 'Unauthorised', 401);

    const {
        data: qrs,
        error
    } = await supabase
        .from('qr_codes')
        .select('id, type, data_preview, image_url, created_at')
        .eq('user_id', authData.user.id)
        .order('created_at', {
            ascending: false
        });

    if (error) return err(res, error.message, 500);
    return ok(res, {
        qrs
    });
}