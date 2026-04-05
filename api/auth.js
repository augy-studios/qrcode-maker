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
        action,
        username,
        email,
        password,
        token
    } = req.body;

    try {
        if (action === 'register') {
            // Check username not already taken
            const { data: existing } = await supabase
                .from('qr_profiles')
                .select('id')
                .eq('username', username)
                .maybeSingle();
            if (existing) return err(res, 'Username already taken.');

            const { error } = await supabase.auth.signUp({
                email,
                password,
                options: { data: { username } }
            });
            if (error) return err(res, error.message);
            return ok(res, { message: 'Check your email to confirm.' });
        }

        if (action === 'login') {
            // Look up email by username
            const { data: profile, error: profileErr } = await supabase
                .from('qr_profiles')
                .select('id')
                .eq('username', username)
                .maybeSingle();
            if (profileErr || !profile) return err(res, 'Username not found.');

            // Get email from auth.users via admin API
            const { data: userData, error: userErr } = await supabase.auth.admin.getUserById(profile.id);
            if (userErr || !userData.user) return err(res, 'Account not found.');

            const { data, error } = await supabase.auth.signInWithPassword({
                email: userData.user.email,
                password
            });
            if (error) return err(res, error.message);
            return ok(res, {
                user: {
                    id: data.user.id,
                    username,
                    email: data.user.email
                },
                token: data.session.access_token
            });
        }

        if (action === 'me') {
            const { data, error } = await supabase.auth.getUser(token);
            if (error || !data.user) return err(res, 'Invalid session', 401);

            const { data: profile } = await supabase
                .from('qr_profiles')
                .select('username')
                .eq('id', data.user.id)
                .maybeSingle();

            return ok(res, {
                user: {
                    id: data.user.id,
                    username: profile?.username,
                    email: data.user.email
                }
            });
        }

        return err(res, 'Unknown action');
    } catch (e) {
        return err(res, e.message, 500);
    }
}