import supabase from '../lib/supabase.js';
import { ok, err } from '../lib/response.js';
import { requireAuth } from '../lib/session.js';
import {
    LINKS,
    TOKENS,
    BOT_USERNAME,
    DEEPLINK_TTL_MS,
    MAX_ATTEMPTS,
    activateSession,
    countWrongCode,
    isExpired,
    iso,
    linkForUser,
    markToken,
    randomHex,
    requestMeta,
    startBackupRequest,
    underRateLimit,
} from '../lib/telegram.js';
import {
    CODE_COUNT,
    backupSummary,
    consumeCode,
    generateCodes,
} from '../lib/backup-codes.js';

// A signed in account gets ten redeem attempts every ten minutes. Wrong codes
// match no row at all, so this is the only place the guessing can be counted.
const REDEEM_LIMIT = 10;
const REDEEM_WINDOW_SECONDS = 600;

/**
 * The portal half of the Telegram link.
 *
 * POST actions, all of them JSON in and JSON out:
 *
 *   status           is this account linked, and is sign in approval on
 *   deeplink         mint a token and hand back a t.me start link to open
 *   poll             has the bot confirmed that deep link yet
 *   redeem           claim a six digit code the bot handed the user
 *   unlink           drop the link
 *   twofa            turn sign in approval on or off
 *   backup_status    how many backup codes are left on this account
 *   backup_request   ask the chat to allow a fresh set
 *   backup_poll      has it allowed it yet, and the codes when it has
 *   challenge        where has a held back sign in got to
 *   verify           finish a held back sign in with six digits
 *   verify_backup    finish it with a backup code instead, Telegram unreachable
 *
 * One GET action, because it is opened by tapping a button in Telegram:
 *
 *   approve     the magic link, one tap instead of six digits
 *
 * Everything except challenge, verify, verify_backup and approve needs a portal
 * session, for the obvious reason that those four run before there is one.
 */
export default async function handler(req, res) {
    if (req.method === 'GET') return handleApprove(req, res);
    if (req.method !== 'POST') return err(res, 'Method not allowed', 405);

    const { action } = req.body || {};

    try {
        switch (action) {
            case 'approve_confirm':  return approveConfirm(req, res);
            case 'challenge':        return challengeStatus(req, res);
            case 'verify':           return verifyChallenge(req, res);
            case 'verify_backup':    return verifyBackup(req, res);
            case 'status':           return withUser(req, res, status);
            case 'deeplink':         return withUser(req, res, deeplink);
            case 'poll':             return withUser(req, res, poll);
            case 'redeem':           return withUser(req, res, redeem);
            case 'unlink':           return withUser(req, res, unlink);
            case 'twofa':            return withUser(req, res, twofa);
            case 'backup_status':    return withUser(req, res, backupStatus);
            case 'backup_request':   return withUser(req, res, backupRequest);
            case 'backup_poll':      return withUser(req, res, backupPoll);
            default:                 return err(res, 'Unknown action');
        }
    } catch (e) {
        return err(res, e.message || 'Something went wrong', e.status || 500);
    }
}

/** Run a handler with the signed in user resolved from the body's session token. */
async function withUser(req, res, fn) {
    const { token } = req.body || {};
    if (!token) return err(res, 'Unauthorised', 401);
    let auth;
    try {
        req.headers['authorization'] = `Bearer ${token}`;
        auth = await requireAuth(req);
    } catch (e) {
        return err(res, e.message, e.status || 401);
    }
    return fn(req, res, auth);
}

// ------------------------------------------------------------------ status --

async function status(req, res, { userId }) {
    const { data } = await supabase
        .from(LINKS)
        .select('telegram_username, telegram_name, twofa_enabled, linked_at')
        .eq('user_id', userId)
        .maybeSingle();

    return ok(res, {
        linked: !!data,
        telegram: data
            ? {
                  username: data.telegram_username,
                  name: data.telegram_name,
                  twofa: !!data.twofa_enabled,
                  since: data.linked_at,
              }
            : null,
    });
}

// --------------------------------------------------------------- deep link --

async function deeplink(req, res, { userId }) {
    // Only the newest invitation stays live, so a start link left open in an
    // old tab cannot be walked into later. Superseding one is not the same as
    // failing it: poll below answers from the account, so the tab holding the
    // older code still sees the connection land.
    await supabase
        .from(TOKENS)
        .update({ status: 'expired' })
        .eq('kind', 'deeplink')
        .eq('user_id', userId)
        .in('status', ['pending', 'delivered']);

    const code = randomHex(16);
    const { error } = await supabase.from(TOKENS).insert({
        kind: 'deeplink',
        code,
        status: 'pending',
        user_id: userId,
        expires_at: iso(DEEPLINK_TTL_MS),
    });
    if (error) return err(res, 'Could not start the connection', 500);

    return ok(res, {
        code,
        url: `https://t.me/${BOT_USERNAME}?start=${code}`,
        expires_in: Math.floor(DEEPLINK_TTL_MS / 1000),
    });
}

/**
 * Where a connect attempt has got to.
 *
 * The question the tab is really asking is whether the account is connected,
 * not whether this particular invitation was the one that did it. The two come
 * apart as soon as the account is open in more than one place: a second tab
 * pressing Connect expires this code, and the tap that lands in Telegram then
 * confirms the other one. Reporting that as a failure here would leave a tab
 * saying the connection did not happen while the chat and every other session
 * says it did, so a dead code is checked against the link before it is believed.
 */
async function poll(req, res, { userId }) {
    const { code } = req.body;
    if (!code) return err(res, 'Missing code');

    const { data } = await supabase
        .from(TOKENS)
        .select('status, telegram_username, created_at')
        .eq('kind', 'deeplink')
        .eq('code', code)
        .eq('user_id', userId)
        .maybeSingle();

    if (!data) return ok(res, { status: 'gone' });
    if (['pending', 'delivered'].includes(data.status)) {
        return ok(res, { status: data.status, telegram_username: data.telegram_username });
    }

    // Only a link made since this invitation was issued can be the answer to
    // it. An older one belongs to a connection this tab already knew about.
    const link = await linkForUser(userId);
    if (link?.telegram_id && new Date(link.linked_at) >= new Date(data.created_at)) {
        return ok(res, {
            status: 'confirmed',
            telegram_username: link.telegram_username,
        });
    }

    return ok(res, { status: data.status, telegram_username: data.telegram_username });
}

// --------------------------------------------------------------- pull code --

async function redeem(req, res, { userId }) {
    const code = String(req.body.code || '').replace(/\D/g, '');
    if (code.length !== 6) return err(res, 'That code should be six digits.');

    const allowed = await underRateLimit(
        `redeem:${userId}`,
        REDEEM_LIMIT,
        REDEEM_WINDOW_SECONDS
    );
    if (!allowed) {
        return err(res, 'Too many attempts. Wait ten minutes and try again.', 429);
    }

    const { data: token } = await supabase
        .from(TOKENS)
        .select('*')
        .eq('kind', 'pull_otp')
        .eq('code', code)
        .in('status', ['pending', 'delivered'])
        .maybeSingle();

    if (!token) return err(res, 'That code is not valid. Ask for a fresh one.', 404);
    if (isExpired(token)) {
        await markToken(token.id, 'expired');
        return err(res, 'That code has expired. Ask for a fresh one.', 410);
    }

    // One Telegram account per portal account, and the reverse.
    await supabase.from(LINKS).delete().eq('telegram_id', token.telegram_id);
    const { error } = await supabase.from(LINKS).upsert(
        {
            user_id: userId,
            telegram_id: token.telegram_id,
            telegram_username: token.telegram_username,
            linked_at: new Date().toISOString(),
        },
        { onConflict: 'user_id' }
    );
    if (error) return err(res, 'Could not save the connection', 500);

    // notified stays false so the bot picks it up and confirms in the chat.
    await markToken(token.id, 'used', { user_id: userId });
    return ok(res, { linked: true, telegram_username: token.telegram_username });
}

// ------------------------------------------------------------------ unlink --

async function unlink(req, res, { userId }) {
    await supabase.from(LINKS).delete().eq('user_id', userId);
    return ok(res, { linked: false });
}

async function twofa(req, res, { userId }) {
    const enabled = !!req.body.enabled;
    const { data } = await supabase
        .from(LINKS)
        .update({ twofa_enabled: enabled })
        .eq('user_id', userId)
        .select('twofa_enabled')
        .maybeSingle();

    if (!data) return err(res, 'Connect a Telegram account first.', 409);
    return ok(res, { twofa: !!data.twofa_enabled });
}

// ------------------------------------------------------- held back sign in --

async function challengeStatus(req, res) {
    const { challenge } = req.body;
    if (!challenge) return err(res, 'Missing challenge');

    const { data: token } = await supabase
        .from(TOKENS)
        .select('id, status, session_token, user_id, expires_at, burned, qr_users(username)')
        .eq('id', challenge)
        .eq('kind', 'push_otp')
        .maybeSingle();

    if (!token) return ok(res, { status: 'gone' });
    if (isExpired(token) && ['pending', 'delivered'].includes(token.status)) {
        await markToken(token.id, 'expired');
        return ok(res, { status: 'expired' });
    }

    // Approved in Telegram, so hand the browser its session exactly once. The
    // status moves on immediately, which keeps the token out of every later
    // poll on the same challenge id.
    if (token.status === 'confirmed') {
        await markToken(token.id, 'used');
        return ok(res, {
            status: 'confirmed',
            token: token.session_token,
            user: { id: token.user_id, username: token.qr_users?.username },
        });
    }
    if (token.burned) return ok(res, { status: 'burned' });
    return ok(res, { status: token.status });
}

/**
 * Load a held back sign in and refuse it if it is not still answerable.
 *
 * Shared by both ways of finishing one, digits and backup code, so a request
 * that is expired, refused or burned reads the same whichever is offered.
 * Returns either the row or the { message, status } to send back.
 */
async function openChallenge(challenge) {
    const { data: token } = await supabase
        .from(TOKENS)
        .select('*, qr_users(username)')
        .eq('id', challenge)
        .eq('kind', 'push_otp')
        .maybeSingle();

    if (!token)
        return { message: 'That sign in request is gone. Start again.', status: 404 };
    if (token.status === 'denied')
        return { message: 'That sign in was refused.', status: 403 };
    if (token.burned)
        return {
            message: 'That request was cancelled after too many wrong codes.',
            status: 429,
        };
    if (!['pending', 'delivered'].includes(token.status))
        return { message: 'That sign in request is no longer open.', status: 409 };
    if (isExpired(token)) {
        await markToken(token.id, 'expired');
        return { message: 'That request expired. Sign in again.', status: 410 };
    }

    return { token };
}

async function verifyChallenge(req, res) {
    const { challenge } = req.body;
    const code = String(req.body.code || '').replace(/\D/g, '');
    if (!challenge || code.length !== 6) return err(res, 'Enter the six digits.');

    const { token, message, status } = await openChallenge(challenge);
    if (!token) return err(res, message, status);

    if (token.code !== code) {
        // The bot watches these columns. It warns the account owner part way
        // through, and clears the prompt entirely once the token burns.
        const { burned, left } = await countWrongCode(token);
        if (burned) {
            return err(
                res,
                `That is ${MAX_ATTEMPTS} wrong codes, so the request has been ` +
                    'cancelled. Sign in again to get a fresh one.',
                429
            );
        }
        return err(
            res,
            `Those digits do not match. ${left} ${left === 1 ? 'try' : 'tries'} left.`,
            401
        );
    }

    const sessionToken = await activateSession(token);
    // notified stays false, so the bot clears the prompt in the chat.
    await markToken(token.id, 'used');

    return ok(res, {
        token: sessionToken,
        user: { id: token.user_id, username: token.qr_users?.username },
    });
}

// ------------------------------------------------------------ backup codes --

/**
 * Finish a held back sign in with a backup code, Telegram out of reach.
 *
 * This is the only route that does not touch the chat at all, which is the
 * entire point of it: the phone is lost, the account is gone, the app will not
 * open. It is still gated on the password, because a backup code alone opens
 * nothing without a live challenge to spend it against, and wrong ones burn the
 * same counter as wrong digits so guessing costs the attacker the request.
 */
async function verifyBackup(req, res) {
    const { challenge } = req.body;
    const code = String(req.body.code || '');
    if (!challenge || !code.trim()) return err(res, 'Enter one of your backup codes.');

    const { token, message, status } = await openChallenge(challenge);
    if (!token) return err(res, message, status);

    const spent = await consumeCode(token.user_id, code, requestMeta(req));
    if (!spent) {
        const { burned, left } = await countWrongCode(token);
        if (burned) {
            return err(
                res,
                `That is ${MAX_ATTEMPTS} wrong codes, so the request has been ` +
                    'cancelled. Sign in again to get a fresh one.',
                429
            );
        }
        return err(
            res,
            'That backup code is not one of yours, or it has been used already. ' +
                `${left} ${left === 1 ? 'try' : 'tries'} left.`,
            401
        );
    }

    const sessionToken = await activateSession(token);
    // The bot reads via and backup_left off the token to say what happened in
    // the chat, which is where someone who did not do this would notice.
    await markToken(token.id, 'used', {
        meta: { ...(token.meta || {}), via: 'backup', backup_left: spent.remaining },
    });

    return ok(res, {
        token: sessionToken,
        user: { id: token.user_id, username: token.qr_users?.username },
        backup_left: spent.remaining,
    });
}

async function backupStatus(req, res, { userId }) {
    const summary = await backupSummary(userId);
    return ok(res, { ...summary, size: CODE_COUNT });
}

/**
 * Ask the chat for permission to mint a set. Nothing is made here.
 *
 * A signed in session is not enough on its own, because a set of backup codes
 * outlives the session that asked for it. Whoever holds the account has to say
 * yes from Telegram first, which is the same bar the sign in itself clears.
 */
async function backupRequest(req, res, { userId }) {
    const link = await linkForUser(userId);
    if (!link?.telegram_id) {
        return err(res, 'Connect a Telegram account first.', 409);
    }

    const request = await startBackupRequest(userId, link.telegram_id, requestMeta(req));
    return ok(res, {
        request: request.id,
        expires_at: request.expires_at,
        hint: link.telegram_username
            ? `Approve it in Telegram, @${link.telegram_username}`
            : 'Approve it in Telegram',
    });
}

/**
 * Where an approval has got to, and the codes themselves once it lands.
 *
 * The request is claimed before anything is minted, and the claim only takes if
 * the row is still confirmed. Two polls crossing therefore leave one winner and
 * one 'used', rather than two sets where the first one is shown and then
 * silently replaced by the second.
 */
async function backupPoll(req, res, { userId }) {
    const { request } = req.body;
    if (!request) return err(res, 'Missing request');

    const { data: token } = await supabase
        .from(TOKENS)
        .select('id, status, expires_at')
        .eq('id', request)
        .eq('kind', 'backup_gen')
        .eq('user_id', userId)
        .maybeSingle();

    if (!token) return ok(res, { status: 'gone' });

    if (isExpired(token) && ['pending', 'delivered'].includes(token.status)) {
        await markToken(token.id, 'expired');
        return ok(res, { status: 'expired' });
    }
    if (token.status !== 'confirmed') return ok(res, { status: token.status });

    const { data: claimed } = await supabase
        .from(TOKENS)
        .update({ status: 'used', consumed_at: new Date().toISOString() })
        .eq('id', token.id)
        .eq('status', 'confirmed')
        .select('id')
        .maybeSingle();
    if (!claimed) return ok(res, { status: 'used' });

    // notified stays false, so the bot turns the prompt in the chat into a
    // record of what it allowed.
    const codes = await generateCodes(userId);
    return ok(res, { status: 'ready', codes, size: CODE_COUNT });
}

// -------------------------------------------------------------- magic link --

/**
 * The magic link, in two halves.
 *
 * A GET only ever draws a page. It has to, because anything at all can fetch a
 * URL that has travelled through a chat: a forwarded message, a link scanner,
 * an over eager preview. Approving on a GET would let any of those sign someone
 * in silently. So the GET shows what is being approved and the POST does it.
 */
async function handleApprove(req, res) {
    const secret = String(req.query.t || '');
    if (req.query.action !== 'approve' || !secret) {
        return err(res, 'Method not allowed', 405);
    }

    const token = await findApprovable(secret);
    if (token.problem) return page(res, token.title, token.problem);

    const meta = token.row.meta || {};
    return page(
        res,
        'Approve this sign in?',
        `Someone is signing in to <b>${escapeHtml(token.username)}</b> on the portal.`,
        {
            facts: [
                ['Address', meta.ip || 'not recorded'],
                ['Browser', meta.agent || 'not recorded'],
            ],
            secret,
            footer:
                'Approve only if this is you, signing in right now. If it is not, ' +
                'go back to the chat and refuse it there.',
        }
    );
}

/** The POST the confirm page submits. This is the half that actually acts. */
async function approveConfirm(req, res) {
    const secret = String(req.body?.t || '');
    if (!secret) return page(res, 'Nothing to approve', 'That link was incomplete.');

    const token = await findApprovable(secret);
    if (token.problem) return page(res, token.title, token.problem);

    try {
        await activateSession(token.row);
        await markToken(token.row.id, 'confirmed');
    } catch {
        // This arrives as a form submit, so a JSON error body would be useless.
        return page(
            res,
            'That did not go through',
            'The sign in could not be opened. Go back to the portal and try again.'
        );
    }

    return page(
        res,
        'Signed in',
        'The browser you started from is being let in now. You can close this tab.'
    );
}

/** Shared lookup and gatekeeping for both halves of the magic link. */
async function findApprovable(secret) {
    const { data: row } = await supabase
        .from(TOKENS)
        .select('*, qr_users(username)')
        .eq('kind', 'push_otp')
        .eq('approval_secret', secret)
        .maybeSingle();

    if (!row) {
        return {
            title: 'Nothing to approve',
            problem: 'That approval link has already been used, or it was never valid.',
        };
    }
    if (row.status === 'denied') {
        return {
            title: 'Already refused',
            problem: 'That sign in was refused earlier and cannot be approved now.',
        };
    }
    if (row.burned) {
        return {
            title: 'Cancelled',
            problem:
                'That request was cancelled after too many wrong codes were tried ' +
                'against it. Sign in again to get a fresh one.',
        };
    }
    if (!['pending', 'delivered'].includes(row.status)) {
        return {
            title: 'Already handled',
            problem: 'That sign in has already gone through. Nothing else to do.',
        };
    }
    if (isExpired(row)) {
        await markToken(row.id, 'expired');
        return {
            title: 'Too late',
            problem: 'That request expired. Go back to the portal and sign in again.',
        };
    }

    return { row, username: row.qr_users?.username || 'your account' };
}

const escapeHtml = (value) =>
    String(value).replace(/[&<>"']/g, (c) =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    );

function page(res, title, body, options = {}) {
    const { facts = [], secret = null, footer = '' } = options;

    const factRows = facts
        .map(
            ([label, value]) =>
                `<div class="fact"><span>${escapeHtml(label)}</span>` +
                `<b>${escapeHtml(value)}</b></div>`
        )
        .join('');

    const form = secret
        ? `<form method="POST" action="/api/telegram-link">
             <input type="hidden" name="action" value="approve_confirm">
             <input type="hidden" name="t" value="${escapeHtml(secret)}">
             <button type="submit">Approve and sign in</button>
           </form>`
        : '';

    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.status(200).send(`<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>${escapeHtml(title)} | QR Maker</title>
<style>
  :root { color-scheme: light dark; }
  body { margin:0; min-height:100vh; display:grid; place-items:center;
         font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;
         background:#ccffcc; color:#123; padding:24px; }
  .card { max-width:26rem; width:100%; background:#fff; border-radius:18px;
          padding:28px 26px; box-shadow:0 10px 40px rgba(0,0,0,.12);
          text-align:center; }
  h1 { margin:0 0 .5rem; font-size:1.35rem; }
  p { margin:0; opacity:.85; }
  .facts { margin:20px 0 4px; text-align:left; font-size:.9rem; }
  .fact { display:flex; justify-content:space-between; gap:12px; padding:8px 0;
          border-top:1px solid rgba(0,0,0,.08); }
  .fact b { font-weight:600; text-align:right; word-break:break-word; }
  button { margin-top:20px; width:100%; padding:12px 20px; font:inherit;
           font-weight:600; border:0; border-radius:12px; cursor:pointer;
           background:#123; color:#ccffcc; }
  button:hover { opacity:.9; }
  .footer { margin-top:16px; font-size:.82rem; opacity:.7; }
  @media (prefers-color-scheme: dark) {
    body { background:#0d1f14; color:#e6f5ea; }
    .card { background:#14291c; box-shadow:none; }
    .fact { border-top-color:rgba(255,255,255,.12); }
    button { background:#ccffcc; color:#0d1f14; }
  }
</style>
</head><body><div class="card">
<h1>${escapeHtml(title)}</h1>
<p>${body}</p>
${factRows ? `<div class="facts">${factRows}</div>` : ''}
${form}
${footer ? `<p class="footer">${escapeHtml(footer)}</p>` : ''}
</div></body></html>`);
}
