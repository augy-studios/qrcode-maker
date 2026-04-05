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
        email,
        password,
        token
    } = req.body;

    try {
        if (action === 'register') {
            const {
                error
            } = await supabase.auth.signUp({
                email,
                password
            });
            if (error) return err(res, error.message);
            return ok(res, {
                message: 'Check your email to confirm.'
            });
        }

        if (action === 'login') {
            const {
                data,
                error
            } = await supabase.auth.signInWithPassword({
                email,
                password
            });
            if (error) return err(res, error.message);
            return ok(res, {
                user: {
                    id: data.user.id,
                    email: data.user.email
                },
                token: data.session.access_token
            });
        }

        if (action === 'me') {
            const {
                data,
                error
            } = await supabase.auth.getUser(token);
            if (error || !data.user) return err(res, 'Invalid session', 401);
            return ok(res, {
                user: {
                    id: data.user.id,
                    email: data.user.email
                }
            });
        }

        return err(res, 'Unknown action');
    } catch (e) {
        return err(res, e.message, 500);
    }
}