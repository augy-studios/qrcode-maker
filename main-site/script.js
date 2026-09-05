/* -- TABS -- */
let activeTab = 'url';

document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        activeTab = btn.dataset.tab;
        document.getElementById(`panel-${activeTab}`).classList.add('active');
        updateQR();
    });
});

/* -- QR GENERATION -- */
let currentData = '';

function getFormData() {
    switch (activeTab) {
        case 'url': {
            let v = document.getElementById('urlInput').value.trim();
            if (v && !v.match(/^https?:\/\//)) v = 'https://' + v;
            return v;
        }
        case 'text':
            return document.getElementById('textInput').value.trim();
        case 'wifi': {
            const ssid = document.getElementById('wssid').value.trim();
            if (!ssid) return '';
            const pass = document.getElementById('wpass').value;
            const sec = document.getElementById('wsec').value;
            const hidden = document.getElementById('whidden').checked ? 'true' : 'false';
            const esc = s => s.replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/"/g, '\\"');
            return `WIFI:T:${sec};S:${esc(ssid)};P:${esc(pass)};H:${hidden};;`;
        }
        case 'calendar': {
            const title = document.getElementById('evtitle').value.trim();
            if (!title) return '';
            const toIcal = (dtStr) => {
                if (!dtStr) return '';
                return dtStr.replace(/[-:]/g, '').replace('T', 'T');
            };
            const start = toIcal(document.getElementById('evstart').value);
            const end = toIcal(document.getElementById('evend').value);
            const loc = document.getElementById('evloc').value.trim();
            const desc = document.getElementById('evdesc').value.trim();
            const uid = `qrmaker-${Date.now()}@uwuapps`;
            let ical = `BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:${uid}\nSUMMARY:${title}`;
            if (start) ical += `\nDTSTART:${start}`;
            if (end) ical += `\nDTEND:${end}`;
            if (loc) ical += `\nLOCATION:${loc}`;
            if (desc) ical += `\nDESCRIPTION:${desc}`;
            ical += `\nEND:VEVENT\nEND:VCALENDAR`;
            return ical;
        }
        case 'contact': {
            const fn = document.getElementById('cfn').value.trim();
            const ln = document.getElementById('cln').value.trim();
            const ph = document.getElementById('cph').value.trim();
            const em = document.getElementById('cem').value.trim();
            const org = document.getElementById('corg').value.trim();
            const url = document.getElementById('curl').value.trim();
            if (!fn && !ln && !ph && !em) return '';
            return `BEGIN:VCARD\nVERSION:3.0\nFN:${fn} ${ln}\nN:${ln};${fn};;;\nORG:${org}\nTEL:${ph}\nEMAIL:${em}\nURL:${url}\nEND:VCARD`;
        }
    }
    return '';
}

async function updateQR() {
    currentData = getFormData();
    const canvas = document.getElementById('qrCanvas');
    const ph = document.getElementById('qrPlaceholder');
    const actions = document.getElementById('qrActions');
    const dataBox = document.getElementById('qrDataBox');
    const saveBtn = document.getElementById('saveQrBtn');

    if (!currentData) {
        canvas.style.display = 'none';
        ph.style.display = 'block';
        actions.style.display = 'none';
        dataBox.style.display = 'none';
        saveBtn.style.display = 'none';
        return;
    }

    canvas.style.display = 'block';
    ph.style.display = 'none';
    actions.style.display = 'flex';
    dataBox.style.display = 'block';
    saveBtn.style.display = 'block';

    await QRCode.toCanvas(canvas, currentData, {
        width: 300,
        margin: 2,
        errorCorrectionLevel: 'H',
        color: { dark: '#000000', light: '#ffffff' }
    });

    await document.fonts.load('bold 28px Jua');
    const ctx = canvas.getContext('2d');
    const size = canvas.width;
    const fontSize = Math.round(size * 0.092);
    ctx.font = `bold ${fontSize}px Jua, sans-serif`;
    const textW = ctx.measureText('uwu').width;
    const textH = fontSize;
    const pad = Math.round(size * 0.028);
    const boxW = textW + pad * 2;
    const boxH = textH + pad * 2;
    const cx = size / 2;
    const cy = size / 2;

    ctx.fillStyle = '#ffffff';
    ctx.fillRect(Math.round(cx - boxW / 2), Math.round(cy - boxH / 2), Math.round(boxW), Math.round(boxH));
    ctx.fillStyle = '#000000';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('uwu', cx, cy);

    document.getElementById('qrDataPre').textContent = currentData;
}

// Live input listeners
['urlInput', 'textInput', 'wssid', 'wpass', 'cfn', 'cln', 'cph', 'cem', 'corg', 'curl', 'evtitle', 'evstart', 'evend', 'evloc', 'evdesc'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', updateQR);
});
document.getElementById('wsec').addEventListener('change', updateQR);
document.getElementById('whidden').addEventListener('change', updateQR);

document.getElementById('clearBtn').addEventListener('click', () => {
    ['urlInput', 'textInput', 'wssid', 'wpass', 'cfn', 'cln', 'cph', 'cem', 'corg', 'curl', 'evtitle', 'evstart', 'evend', 'evloc', 'evdesc'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    document.getElementById('whidden').checked = false;
    document.getElementById('wsec').value = 'WPA';
    updateQR();
});

/* -- DOWNLOAD -- */
document.getElementById('downloadBtn').addEventListener('click', () => {
    const canvas = document.getElementById('qrCanvas');
    const a = document.createElement('a');
    a.download = `qr-${activeTab}-${Date.now()}.png`;
    a.href = canvas.toDataURL('image/png');
    a.click();
});

/* -- COPY DATA -- */
document.getElementById('copyDataBtn').addEventListener('click', async () => {
    await navigator.clipboard.writeText(currentData).catch(() => {});
    showToast('Data copied to clipboard!');
});

/* -- AUTH TABS -- */
document.querySelectorAll('.modal-tab').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.modal-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const mode = btn.dataset.auth;
        document.getElementById('authLoginForm').style.display = mode === 'login' ? 'block' : 'none';
        document.getElementById('authRegisterForm').style.display = mode === 'register' ? 'block' : 'none';
        document.getElementById('authTwofaForm').style.display = 'none';
        document.getElementById('authMsg').textContent = '';
    });
});

/* -- FAVOURITES KEPT ON THIS DEVICE -- */
/*
 * Saving has never needed an account, it only ever needed somewhere to put the
 * result. Signed out, that somewhere is localStorage: the same Save button, the
 * same list under My QRs, just held on this device and readable by nobody else.
 *
 * It is a waiting room, not a second home. The first time an account signs in
 * here the whole pile is handed to the server, which keeps whatever the account
 * does not already have and tells us so, and the device store is emptied. The
 * bot does exactly this with its own local list when a chat links, and both
 * sides decide sameness on the encoded payload, so a code saved in both places
 * survives as one.
 */
const FAV_KEY = 'qr_favourites';
const FAV_MAX = 50;

function favLoad() {
    try {
        const raw = JSON.parse(localStorage.getItem(FAV_KEY) || '[]');
        return Array.isArray(raw) ? raw.filter((f) => f && f.data && f.image) : [];
    } catch {
        return [];
    }
}

function favStore(list) {
    try {
        localStorage.setItem(FAV_KEY, JSON.stringify(list));
        return true;
    } catch {
        // A full or blocked store is worth saying out loud, because the user
        // just asked for something to be kept and it will not be.
        return false;
    }
}

/** Add one code. Returns 'added', 'duplicate', 'full' or 'failed'. */
function favAdd(data, type, image) {
    const list = favLoad();
    if (list.some((f) => f.data === data)) return 'duplicate';
    if (list.length >= FAV_MAX) return 'full';
    list.push({
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        data,
        type,
        image,
        created: new Date().toISOString(),
    });
    return favStore(list) ? 'added' : 'failed';
}

function favRemove(id) {
    favStore(favLoad().filter((f) => f.id !== id));
}

function favCount() {
    return favLoad().length;
}

/* -- AUTH STATE -- */
let currentUser = null;

function setAuthBtn() {
    const btn = document.getElementById('authBtn');
    const logoutBtn = document.getElementById('logoutBtn');
    const deviceBtn = document.getElementById('deviceQrBtn');
    if (currentUser) {
        btn.innerHTML = '<span data-icon="folder"></span> My QRs';
        hydrateIcons(btn);
        logoutBtn.style.display = '';
        deviceBtn.style.display = 'none';
    } else {
        btn.innerHTML = 'Register / Login';
        logoutBtn.style.display = 'none';
        // Nothing kept here yet means nothing to open, so the button stays away
        // until the first save puts something behind it.
        deviceBtn.style.display = favCount() ? '' : 'none';
    }
    // Saving works either way now, so the button follows the code, not the user.
    document.getElementById('saveQrBtn').style.display = currentData ? 'block' : 'none';
}

async function triggerPasswordSave(username, password) {
    if (window.PasswordCredential) {
        try {
            const cred = new PasswordCredential({ id: username, password, name: username });
            await navigator.credentials.store(cred);
        } catch (e) {}
    }
}

document.getElementById('logoutBtn').addEventListener('click', async () => {
    const token = localStorage.getItem('qr_session');
    await fetch('/api/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'logout', token }),
    }).catch(() => {});
    localStorage.removeItem('qr_session');
    currentUser = null;
    // Only this session ends. Any other browser signed in to the account keeps
    // its own session and its own Telegram connection, which is untouched by a
    // log out here.
    stopTgWatch();
    stopTgConnectPoll();
    tgLinkedSeen = null;
    const panel = document.getElementById('tgPanel');
    if (panel) panel.hidden = true;
    setAuthBtn();
    showToast('Logged out.');
});

document.getElementById('authBtn').addEventListener('click', () => {
    if (currentUser) {
        loadMyQRs();
        tgRefresh();
        openModal('myQrModal');
    } else {
        openModal('authModal');
    }
});

/* -- ENTER KEY SUBMIT -- */
document.getElementById('authLoginForm').addEventListener('submit', (e) => {
    e.preventDefault();
    document.getElementById('loginSubmit').click();
});

document.getElementById('authRegisterForm').addEventListener('submit', (e) => {
    e.preventDefault();
    document.getElementById('registerSubmit').click();
});

/* -- LOGIN -- */
document.getElementById('loginSubmit').addEventListener('click', async () => {
    const username = document.getElementById('loginUsername').value.trim();
    const password = document.getElementById('loginPassword').value;
    const msg = document.getElementById('authMsg');
    msg.className = 'auth-msg';
    msg.textContent = 'Logging in…';

    try {
        const res = await fetch('/api/auth', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                action: 'login',
                username,
                password
            }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Login failed');

        // The password was right but the account wants Telegram to allow it,
        // so no session comes back until that happens.
        if (data.twofa_required) {
            msg.textContent = '';
            beginTwofa(data, username, password);
            return;
        }

        finishSignIn(data.user, data.token, username, password);
    } catch (e) {
        msg.className = 'auth-msg error';
        msg.textContent = e.message;
    }
});

/* -- REGISTER -- */
document.getElementById('registerSubmit').addEventListener('click', async () => {
    const username = document.getElementById('regUsername').value.trim();
    const email = document.getElementById('regEmail').value.trim();
    const pw = document.getElementById('regPassword').value;
    const pw2 = document.getElementById('regPassword2').value;
    const msg = document.getElementById('authMsg');
    msg.className = 'auth-msg';

    if (!username) {
        msg.className = 'auth-msg error';
        msg.textContent = 'Please choose a username.';
        return;
    }
    if (pw !== pw2) {
        msg.className = 'auth-msg error';
        msg.textContent = 'Passwords do not match.';
        return;
    }
    if (pw.length < 6) {
        msg.className = 'auth-msg error';
        msg.textContent = 'Password must be at least 6 characters.';
        return;
    }

    msg.textContent = 'Creating account…';
    try {
        const res = await fetch('/api/auth', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                action: 'register',
                username,
                email,
                password: pw
            }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Registration failed');
        triggerPasswordSave(username, pw);
        currentUser = { id: data.session.userId, username: data.username };
        localStorage.setItem('qr_session', data.session.token);
        closeModal('authModal');
        setAuthBtn();
        showToast('Account created! Welcome, ' + username + '!');
        // A new account is the commonest way a device arrives holding codes:
        // saved first, registered afterwards. They go up with it.
        mergeDeviceFavourites();
    } catch (e) {
        msg.className = 'auth-msg error';
        msg.textContent = e.message;
    }
});

/* -- SESSION RESTORE -- */
(async () => {
    const token = localStorage.getItem('qr_session');
    // Signed out is still a state worth dressing: a device holding saved codes
    // needs its My QRs button on the very first paint, not only after a save.
    if (!token) return setAuthBtn();
    try {
        const res = await fetch('/api/auth', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                action: 'me',
                token
            }),
        });
        if (!res.ok) {
            localStorage.removeItem('qr_session');
            return;
        }
        const data = await res.json();
        currentUser = data.user;
        setAuthBtn();
        // Anything a previous merge could not hand over is still sitting here.
        mergeDeviceFavourites();
    } catch {}
})();

/* -- SAVE QR -- */
document.getElementById('saveQrBtn').addEventListener('click', async () => {
    if (!currentData) return;
    const canvas = document.getElementById('qrCanvas');
    const imageDataUrl = canvas.toDataURL('image/png');

    if (!currentUser) {
        const outcome = favAdd(currentData, activeTab, imageDataUrl);
        if (outcome === 'duplicate') return showToast('Already in your saved codes.');
        if (outcome === 'full') {
            return showToast(`This device holds ${FAV_MAX} codes. Delete one first.`);
        }
        if (outcome === 'failed') {
            return showToast('This browser would not let us save it. Check your storage settings.');
        }
        setAuthBtn();
        return showToast('Saved on this device. Log in and it moves to your account.');
    }

    try {
        const res = await fetch('/api/qr-save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: localStorage.getItem('qr_session'),
                data: currentData,
                type: activeTab,
                imageDataUrl,
            }),
        });
        if (!res.ok) throw new Error((await res.json()).error);
        showToast('QR saved!');
    } catch (e) {
        showToast('Save failed: ' + e.message);
    }
});

/* -- MY QRs -- */
document.getElementById('deviceQrBtn').addEventListener('click', () => {
    loadMyQRs();
    openModal('myQrModal');
});

function renderQrCards(grid, cards) {
    grid.innerHTML = cards
        .map(
            (c) => `
      <div class="qr-card" data-id="${escHtml(c.id)}">
        <img src="${c.image}" alt="QR Code" loading="lazy" />
        <div class="qr-card-label">${escHtml(c.label)}</div>
        <div class="qr-card-actions">
          <a href="${c.image}" download="qr-${escHtml(c.id)}.png" class="btn-ghost" aria-label="Download"><span data-icon="download"></span></a>
          <button class="btn-ghost" onclick="deleteQR('${escHtml(c.id)}')" aria-label="Delete"><span data-icon="trash"></span></button>
        </div>
      </div>`
        )
        .join('');
    hydrateIcons(grid);
}

function setMyQrNote(text) {
    const note = document.getElementById('myQrNote');
    note.textContent = text || '';
    note.hidden = !text;
}

async function loadMyQRs() {
    const grid = document.getElementById('myQrGrid');

    // Signed out, the list is whatever this device is holding.
    if (!currentUser) {
        const list = favLoad();
        setMyQrNote(
            'These are saved in this browser only. Log in or register and they ' +
                'move to your account, joining anything already there, without ' +
                'saving anything twice.'
        );
        if (!list.length) {
            grid.innerHTML = '<p class="empty-state">No saved QR codes yet.</p>';
            return;
        }
        renderQrCards(
            grid,
            list
                .slice()
                .reverse()
                .map((f) => ({ id: f.id, image: f.image, label: f.data.slice(0, 80) }))
        );
        return;
    }

    setMyQrNote('');
    grid.innerHTML = '<p class="empty-state">Loading…</p>';
    const token = localStorage.getItem('qr_session');
    try {
        const res = await fetch(`/api/qr-list?token=${encodeURIComponent(token)}`);
        const data = await res.json();
        if (!data.qrs || !data.qrs.length) {
            grid.innerHTML = '<p class="empty-state">No saved QR codes yet.</p>';
            return;
        }
        renderQrCards(
            grid,
            data.qrs.map((q) => ({ id: q.id, image: q.image_url, label: q.data_preview }))
        );
    } catch {
        grid.innerHTML = '<p class="empty-state">Failed to load.</p>';
    }
}

window.deleteQR = async (id) => {
    if (!currentUser) {
        favRemove(id);
        setAuthBtn();
        loadMyQRs();
        return;
    }
    const token = localStorage.getItem('qr_session');
    await fetch('/api/qr-delete', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            id,
            token
        }),
    });
    loadMyQRs();
};

/* -- HANDING THE DEVICE LIST TO THE ACCOUNT -- */
/*
 * Runs once per sign in, on every route into an account: password, Telegram
 * approval, backup code, and a fresh registration. The server does the
 * de-duplication, because only it can see what the account already holds, and
 * only what it confirms is dropped from this device.
 */
async function mergeDeviceFavourites() {
    const list = favLoad();
    if (!list.length) return;

    let data;
    try {
        const res = await fetch('/api/qr-save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: localStorage.getItem('qr_session'),
                action: 'merge',
                items: list.map((f) => ({
                    id: f.id,
                    data: f.data,
                    type: f.type,
                    imageDataUrl: f.image,
                })),
            }),
        });
        data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Merge failed');
    } catch {
        // Keep every one of them. An account that could not be reached is a
        // reason to try again later, never a reason to drop the only copy.
        showToast('Your device codes are still here. We will move them next time.');
        return;
    }

    // Anything the server named as failed stays put; the rest is now on the
    // account and this device does not need a second copy.
    const failed = new Set(data.failed || []);
    favStore(list.filter((f) => failed.has(f.id)));

    const moved = data.added || 0;
    const skipped = data.skipped || 0;
    if (moved) {
        showToast(
            `${moved} saved ${moved === 1 ? 'code' : 'codes'} moved to your account` +
                (skipped ? `, ${skipped} already there.` : '.')
        );
    } else if (skipped) {
        showToast('Your saved codes were already on your account.');
    }
}

function escHtml(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/* -- TOAST -- */
let toastTimer;

function showToast(msg) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 2800);
}

/* -- PASSWORD TOGGLES -- */
document.querySelectorAll('.pw-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
        const input = btn.previousElementSibling;
        const showing = input.type === 'text';
        input.type = showing ? 'password' : 'text';
        btn.querySelector('[data-icon]').setAttribute('data-icon', showing ? 'eye' : 'eye-off');
        hydrateIcons(btn);
    });
});

/* -- SERVICE WORKER -- */
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
}

/* -- SIGN IN COMPLETION -- */
function finishSignIn(user, token, username, password, note) {
    currentUser = user;
    localStorage.setItem('qr_session', token);
    if (username && password) triggerPasswordSave(username, password);
    closeModal('authModal');
    setAuthBtn();
    showToast(note || 'Welcome back!');
    // There is now somewhere to put whatever this device was holding.
    mergeDeviceFavourites();
}

/* -- TWO FACTOR, VIA TELEGRAM -- */
/*
 * Two ways to finish, running at the same time. Either the six digits get
 * typed in here, or the Approve button gets tapped in the chat and the poll
 * below notices. Whichever lands first wins.
 *
 * A third way exists for when neither can happen, because the phone is lost or
 * the app will not open: one of the backup codes made on the account. The same
 * field takes it, the toggle underneath swaps between the two, and the account
 * is only offered it when it actually has codes left.
 */
let twofaPoll = null;

function stopTwofaPoll() {
    if (twofaPoll) {
        clearInterval(twofaPoll);
        twofaPoll = null;
    }
}

function showAuthPane(pane) {
    document.getElementById('authLoginForm').style.display = pane === 'login' ? 'block' : 'none';
    document.getElementById('authRegisterForm').style.display = pane === 'register' ? 'block' : 'none';
    document.getElementById('authTwofaForm').style.display = pane === 'twofa' ? 'block' : 'none';
    const tabs = document.querySelector('.modal-tabs');
    if (tabs) tabs.style.display = pane === 'twofa' ? 'none' : '';
}

function beginTwofa(challenge, username, password) {
    stopTwofaPoll();
    showAuthPane('twofa');

    const field = document.getElementById('twofaCode');
    const hint = document.getElementById('twofaHint');
    const label = document.getElementById('twofaLabel');
    const waiting = document.getElementById('twofaWaiting');
    const toggle = document.getElementById('twofaBackupToggle');
    const telegramHint = challenge.hint || 'Check Telegram for the code.';

    let backupMode = false;
    // Never offered to an account with nothing to offer. Someone who has run
    // out is better told to reach Telegram than sent looking for a code that
    // will not work.
    toggle.hidden = !challenge.backup_available;

    const dress = () => {
        hint.textContent = backupMode
            ? 'Type one of the backup codes you saved. Each one works once.'
            : telegramHint;
        label.textContent = backupMode ? 'Backup code' : 'Six digit code';
        toggle.textContent = backupMode
            ? 'Go back to the Telegram code'
            : "Can't reach Telegram? Use a backup code";
        field.value = '';
        field.placeholder = backupMode ? 'xxxxx-xxxxx' : '000000';
        field.maxLength = backupMode ? 12 : 6;
        field.inputMode = backupMode ? 'text' : 'numeric';
        field.classList.toggle('tg-otp', !backupMode);
        // The chat is not going to finish this one, so stop suggesting it will.
        waiting.hidden = backupMode;
        field.focus();
    };
    dress();

    const submit = async () => {
        const msg = document.getElementById('authMsg');
        const typed = field.value.trim();
        const digits = typed.replace(/\D/g, '');
        const letters = typed.replace(/[^a-zA-Z0-9]/g, '');

        if (backupMode ? letters.length !== 10 : digits.length !== 6) {
            msg.className = 'auth-msg error';
            msg.textContent = backupMode
                ? 'A backup code is ten characters, like xxxxx-xxxxx.'
                : 'Enter all six digits.';
            return;
        }

        msg.className = 'auth-msg';
        msg.textContent = 'Checking...';
        try {
            const res = await fetch('/api/telegram-link', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    action: backupMode ? 'verify_backup' : 'verify',
                    challenge: challenge.challenge,
                    code: backupMode ? typed : digits,
                }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'That did not work');
            stopTwofaPoll();
            showAuthPane('login');
            msg.textContent = '';
            finishSignIn(
                data.user,
                data.token,
                username,
                password,
                backupMode
                    ? `Backup code used. ${data.backup_left} left.`
                    : undefined
            );
        } catch (e) {
            msg.className = 'auth-msg error';
            msg.textContent = e.message;
            field.value = '';
            field.focus();
        }
    };

    document.getElementById('twofaSubmit').onclick = submit;
    field.onkeydown = (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            submit();
        }
    };
    toggle.onclick = () => {
        backupMode = !backupMode;
        document.getElementById('authMsg').textContent = '';
        dress();
    };
    document.getElementById('twofaCancel').onclick = () => {
        stopTwofaPoll();
        showAuthPane('login');
        document.getElementById('authMsg').textContent = '';
    };

    // Watch for the Approve button being tapped in the chat instead.
    const started = Date.now();
    twofaPoll = setInterval(async () => {
        if (Date.now() - started > 6 * 60 * 1000) return stopTwofaPoll();
        try {
            const res = await fetch('/api/telegram-link', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'challenge', challenge: challenge.challenge }),
            });
            const data = await res.json();
            if (data.status === 'confirmed' && data.token) {
                stopTwofaPoll();
                showAuthPane('login');
                finishSignIn(data.user, data.token, username, password);
                return;
            }
            const dead = {
                denied: 'That sign in was refused from Telegram.',
                burned: 'Too many wrong codes. Start the sign in again.',
                expired: 'That request expired. Start the sign in again.',
                gone: 'That request is no longer there. Start again.',
            };
            if (dead[data.status]) {
                stopTwofaPoll();
                showAuthPane('login');
                const msg = document.getElementById('authMsg');
                msg.className = 'auth-msg error';
                msg.textContent = dead[data.status];
            }
        } catch {
            // A dropped poll is not worth reporting. The next one covers it.
        }
    }, 2500);
}

/* -- TELEGRAM LINK PANEL -- */
const tgApi = (body) =>
    fetch('/api/telegram-link', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: localStorage.getItem('qr_session'), ...body }),
    }).then(async (r) => {
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || 'Request failed');
        return d;
    });

let tgConnectPoll = null;

function stopTgConnectPoll() {
    if (tgConnectPoll) {
        clearInterval(tgConnectPoll);
        tgConnectPoll = null;
    }
}

function tgSay(text, isError) {
    const msg = document.getElementById('tgMsg');
    if (!msg) return;
    msg.className = isError ? 'auth-msg error' : 'auth-msg';
    msg.textContent = text;
}

/* -- ONE LINK, EVERY SESSION -- */
/*
 * The Telegram connection belongs to the account, not to the browser that made
 * it. Log in on a laptop and a phone and both are connected, because both are
 * the same account and the link is a row against the account id. Nothing here
 * is limited to one session, and signing in somewhere new never disturbs a
 * session that is already open.
 *
 * What does not travel by itself is the news. A panel opened before the link
 * was made goes on saying so, and would offer Connect for an account that is
 * already connected. This heartbeat is the fix: while the panel is on screen it
 * re-reads the account every few seconds, so a connection, a disconnection or a
 * sign in approval toggle made anywhere else shows up here without a reload.
 *
 * It stops itself the moment the panel closes, so a tab left open all day is
 * not quietly polling all day.
 */
const TG_WATCH_MS = 8000;
let tgWatch = null;
let tgLinkedSeen = null; // what this tab last saw, so a change elsewhere is news

function tgPanelOpen() {
    const modal = document.getElementById('myQrModal');
    return !!modal && !modal.classList.contains('hidden');
}

function stopTgWatch() {
    if (tgWatch) {
        clearInterval(tgWatch);
        tgWatch = null;
    }
}

function startTgWatch() {
    stopTgWatch();
    tgWatch = setInterval(() => {
        if (!currentUser || !tgPanelOpen()) return stopTgWatch();
        tgRefresh({ quiet: true });
    }, TG_WATCH_MS);
}

/**
 * Read the account's Telegram state and dress the panel with it.
 *
 * Quiet is the heartbeat calling. It leaves the panel alone on a failed read,
 * because a dropped request says nothing about the link, and it never touches
 * the backup codes half, because codes on screen are shown exactly once and a
 * background tick must not be what wipes them.
 */
async function tgRefresh(options) {
    const quiet = !!(options && options.quiet);
    const panel = document.getElementById('tgPanel');
    if (!panel || !currentUser) return;
    panel.hidden = false;
    const state = document.getElementById('tgState');

    let linked;
    let telegram;
    try {
        ({ linked, telegram } = await tgApi({ action: 'status' }));
    } catch (e) {
        if (!quiet) state.textContent = e.message;
        return;
    }

    document.getElementById('tgConnected').hidden = !linked;
    document.getElementById('tgDisconnected').hidden = linked;
    state.textContent = linked
        ? 'Connected' + (telegram.username ? ' to @' + telegram.username : '') + '.'
        : 'Not connected yet.';
    document.getElementById('tgTwofa').checked = !!(telegram && telegram.twofa);

    const changed = tgLinkedSeen !== null && tgLinkedSeen !== linked;
    tgLinkedSeen = linked;

    // Only the heartbeat announces. A change this tab made has already said so
    // in its own words.
    if (quiet && changed) {
        stopTgConnectPoll();
        tgSay('');
        showToast(
            linked
                ? 'Telegram was connected from another session.'
                : 'Telegram was disconnected from another session.'
        );
        if (linked) tgBackupRefresh();
    }

    if (!quiet) {
        if (linked) tgBackupRefresh();
        startTgWatch();
    }
}

document.getElementById('tgConnectBtn')?.addEventListener('click', async () => {
    stopTgConnectPoll();
    tgSay('Opening Telegram...');
    try {
        const { code, url } = await tgApi({ action: 'deeplink' });
        window.open(url, '_blank', 'noopener');
        tgSay('Confirm it in the chat. This updates by itself.');

        const started = Date.now();
        tgConnectPoll = setInterval(async () => {
            if (Date.now() - started > 10 * 60 * 1000) return stopTgConnectPoll();
            try {
                const { status } = await tgApi({ action: 'poll', code });
                if (status === 'confirmed') {
                    stopTgConnectPoll();
                    tgSay('');
                    showToast('Telegram connected!');
                    tgRefresh();
                } else if (['denied', 'expired', 'gone'].includes(status)) {
                    stopTgConnectPoll();
                    tgSay('That request was not completed. Try again.', true);
                }
            } catch {
                // Keep polling. A single failed check means nothing.
            }
        }, 2000);
    } catch (e) {
        tgSay(e.message, true);
    }
});

document.getElementById('tgCodeBtn')?.addEventListener('click', async () => {
    const field = document.getElementById('tgCodeInput');
    try {
        await tgApi({ action: 'redeem', code: field.value });
        field.value = '';
        tgSay('');
        showToast('Telegram connected!');
        tgRefresh();
    } catch (e) {
        tgSay(e.message, true);
    }
});

document.getElementById('tgCodeInput')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        document.getElementById('tgCodeBtn').click();
    }
});

document.getElementById('tgUnlinkBtn')?.addEventListener('click', async () => {
    try {
        await tgApi({ action: 'unlink' });
        showToast('Telegram disconnected.');
        tgSay('');
        tgRefresh();
    } catch (e) {
        tgSay(e.message, true);
    }
});

document.getElementById('tgTwofa')?.addEventListener('change', async (e) => {
    try {
        await tgApi({ action: 'twofa', enabled: e.target.checked });
        showToast(e.target.checked ? 'Sign in approval is on.' : 'Sign in approval is off.');
        // Turning it on with nothing to fall back on is how people lock
        // themselves out, so say so at the moment it becomes true.
        tgSay(
            e.target.checked && !backupRemaining
                ? 'Make some backup codes below. Without them, losing Telegram ' +
                      'means losing the account.'
                : ''
        );
    } catch (err) {
        e.target.checked = !e.target.checked;
        tgSay(err.message, true);
    }
});

/* -- BACKUP CODES -- */
/*
 * The way back in when the chat is gone. Made here, shown exactly once, and
 * spent one at a time in the sign in modal. Nothing on this page can read them
 * back afterwards, because the server only ever kept their hashes.
 *
 * Making a set is itself held back until Telegram allows it. A signed in tab is
 * not proof of much: a set of codes outlives the session that asked for it, so
 * the account has to say yes from the chat before any of them exist.
 */
let backupRemaining = 0;
let backupCodes = [];
let backupArmed = false;
let backupArmTimer = null;
let backupRequestId = null;
let backupPoll = null;

function backupDisarm() {
    clearTimeout(backupArmTimer);
    backupArmed = false;
}

function stopBackupPoll() {
    if (backupPoll) {
        clearInterval(backupPoll);
        backupPoll = null;
    }
}

function backupBusy(busy) {
    const btn = document.getElementById('tgBackupBtn');
    if (btn) btn.disabled = busy;
}

function backupButtonLabel(total) {
    return total ? 'Replace backup codes' : 'Generate backup codes';
}

async function tgBackupRefresh() {
    const state = document.getElementById('tgBackupState');
    if (!state) return;

    // Anything on screen belongs to the last visit and cannot be shown again.
    document.getElementById('tgBackupCodes').hidden = true;
    document.getElementById('tgBackupActions').hidden = true;
    backupCodes = [];
    backupDisarm();

    try {
        const { total, remaining } = await tgApi({ action: 'backup_status' });
        backupRemaining = remaining;
        state.textContent = !total
            ? 'None yet. Nothing to fall back on if Telegram goes missing.'
            : remaining
              ? `${remaining} of ${total} still unused.`
              : 'All used. Make a fresh set.';
        document.getElementById('tgBackupBtn').textContent = backupButtonLabel(total);
    } catch (e) {
        state.textContent = e.message;
    }

    // A request left waiting when the panel was closed is still live in the
    // chat, so pick the wait back up rather than stranding whoever approves it.
    if (backupRequestId) waitForBackupApproval();
}

function showBackupCodes(codes) {
    backupCodes = codes;
    backupRemaining = codes.length;

    const box = document.getElementById('tgBackupCodes');
    box.innerHTML = codes.map((code) => `<span>${escHtml(code)}</span>`).join('');
    box.hidden = false;
    document.getElementById('tgBackupActions').hidden = false;
    document.getElementById('tgBackupState').textContent =
        `${codes.length} of ${codes.length} still unused.`;
    document.getElementById('tgBackupBtn').textContent = backupButtonLabel(codes.length);
    tgSay('Save these now. They are not shown again.');
}

/** Watch the request until the chat answers it, one way or the other. */
function waitForBackupApproval() {
    stopBackupPoll();
    backupBusy(true);

    const started = Date.now();
    backupPoll = setInterval(async () => {
        // The request itself only lives five minutes. Waiting past that is
        // waiting for something the server has already thrown away.
        if (Date.now() - started > 5.5 * 60 * 1000) {
            stopBackupPoll();
            backupBusy(false);
            backupRequestId = null;
            tgSay('That request timed out. Ask for the codes again.', true);
            return;
        }

        try {
            const data = await tgApi({ action: 'backup_poll', request: backupRequestId });

            if (data.status === 'ready') {
                stopBackupPoll();
                backupBusy(false);
                backupRequestId = null;
                showBackupCodes(data.codes);
                return;
            }

            const dead = {
                denied: 'That was refused from Telegram. No codes were made.',
                expired: 'That request expired before it was approved. Ask again.',
                gone: 'That request is no longer there. Ask again.',
                used: 'That request has already been answered somewhere else.',
            };
            if (dead[data.status]) {
                stopBackupPoll();
                backupBusy(false);
                backupRequestId = null;
                tgSay(dead[data.status], data.status !== 'used');
            }
        } catch {
            // A dropped poll is not worth reporting. The next one covers it.
        }
    }, 2500);
}

document.getElementById('tgBackupBtn')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;

    // Replacing a set someone may be relying on is worth one deliberate second,
    // so the first press only arms the second.
    if (backupRemaining && !backupArmed) {
        backupArmed = true;
        btn.textContent = 'Press again to replace them';
        tgSay('The codes you have now stop working the moment you do.');
        backupArmTimer = setTimeout(() => {
            backupDisarm();
            btn.textContent = backupButtonLabel(backupRemaining);
            tgSay('');
        }, 8000);
        return;
    }
    backupDisarm();

    backupBusy(true);
    tgSay('Asking Telegram...');
    try {
        const { request, hint } = await tgApi({ action: 'backup_request' });
        backupRequestId = request;
        tgSay(`${hint || 'Approve it in Telegram'}. The codes appear here once you do.`);
        waitForBackupApproval();
    } catch (err) {
        backupBusy(false);
        tgSay(err.message, true);
    }
});

document.getElementById('tgBackupCopy')?.addEventListener('click', async () => {
    if (!backupCodes.length) return;
    await navigator.clipboard.writeText(backupCodes.join('\n')).catch(() => {});
    showToast('Backup codes copied.');
});

document.getElementById('tgBackupDownload')?.addEventListener('click', () => {
    if (!backupCodes.length) return;
    const text =
        `QR Maker backup codes for ${currentUser?.username || 'your account'}\n` +
        `Made ${new Date().toLocaleString()}\n` +
        'Each one signs you in once, in place of the Telegram approval.\n\n' +
        backupCodes.join('\n') +
        '\n';
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'qr-maker-backup-codes.txt';
    a.click();
    URL.revokeObjectURL(url);
});

document.getElementById('tgBackupDone')?.addEventListener('click', () => {
    backupCodes = [];
    document.getElementById('tgBackupCodes').innerHTML = '';
    document.getElementById('tgBackupCodes').hidden = true;
    document.getElementById('tgBackupActions').hidden = true;
    tgSay('');
});
