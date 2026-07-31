import supabase from './supabase.js';

export async function requireAuth(req) {
    const auth = req.headers['authorization'] || '';
    const token = auth.replace(/^Bearer\s+/i, '').trim();
    if (!token) throw Object.assign(new Error('Unauthorised'), { status: 401 });

    const { data, error } = await supabase
        .from('qr_sessions')
        .select('user_id, expires_at, qr_users(username)')
        .eq('token', token)
        .single();

    if (error || !data) throw Object.assign(new Error('Unauthorised'), { status: 401 });
    if (new Date(data.expires_at) < new Date()) {
        await supabase.from('qr_sessions').delete().eq('token', token);
        throw Object.assign(new Error('Session expired'), { status: 401 });
    }

    return { userId: data.user_id, username: data.qr_users.username };
}
