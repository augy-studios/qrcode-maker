import supabase from '../lib/supabase.js';
import { ok, err } from '../lib/response.js';
import bcrypt from 'bcryptjs';
import crypto from 'crypto';

export default async function handler(req, res) {
    if (req.method !== 'POST') return err(res, 'Method not allowed', 405);
    const { action, username, email, password, token } = req.body;

    try {
        if (action === 'register') {
            if (!username || !email || !password)
                return err(res, 'Username, email, and password are required');
            if (password.length < 6)
                return err(res, 'Password must be at least 6 characters');
            if (!/^[a-zA-Z0-9_]{3,24}$/.test(username))
                return err(res, 'Username must be 3-24 alphanumeric/underscore characters');

            const { data: existing } = await supabase
                .from('qr_users')
                .select('id')
                .or(`username.eq.${username},email.eq.${email}`)
                .maybeSingle();
            if (existing) return err(res, 'Username or email already taken', 409);

            const hash = await bcrypt.hash(password, 12);
            const { data: user, error: insertErr } = await supabase
                .from('qr_users')
                .insert({ username, email, password_hash: hash })
                .select('id, username')
                .single();
            if (insertErr) return err(res, 'Registration failed', 500);

            const sessionToken = crypto.randomBytes(32).toString('hex');
            const expires = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000);
            await supabase.from('qr_sessions').insert({
                token: sessionToken,
                user_id: user.id,
                expires_at: expires.toISOString(),
            });

            return ok(res, {
                message: 'Account created! You can now log in.',
                username: user.username,
                session: { token: sessionToken, userId: user.id },
            });
        }

        if (action === 'login') {
            if (!username || !password)
                return err(res, 'Username and password are required');

            const { data: user, error: userErr } = await supabase
                .from('qr_users')
                .select('id, username, password_hash')
                .eq('username', username)
                .maybeSingle();
            if (userErr || !user) return err(res, 'Invalid username or password', 401);

            const valid = await bcrypt.compare(password, user.password_hash);
            if (!valid) return err(res, 'Invalid username or password', 401);

            const sessionToken = crypto.randomBytes(32).toString('hex');
            const expires = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000);
            await supabase.from('qr_sessions').insert({
                token: sessionToken,
                user_id: user.id,
                expires_at: expires.toISOString(),
            });

            return ok(res, {
                user: { id: user.id, username: user.username },
                token: sessionToken,
            });
        }

        if (action === 'logout') {
            if (token) await supabase.from('qr_sessions').delete().eq('token', token);
            return ok(res, { ok: true });
        }

        if (action === 'me') {
            if (!token) return err(res, 'Unauthorised', 401);

            const { data: session, error: sessionErr } = await supabase
                .from('qr_sessions')
                .select('user_id, expires_at, qr_users(username)')
                .eq('token', token)
                .single();
            if (sessionErr || !session) return err(res, 'Invalid session', 401);
            if (new Date(session.expires_at) < new Date()) {
                await supabase.from('qr_sessions').delete().eq('token', token);
                return err(res, 'Session expired', 401);
            }

            return ok(res, {
                user: { id: session.user_id, username: session.qr_users.username },
            });
        }

        return err(res, 'Unknown action');
    } catch (e) {
        return err(res, e.message, 500);
    }
}
