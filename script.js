/* -- THEME -- */
const THEMES = [{
        id: 'classic',
        label: 'Classic',
        hex: '#ccffcc'
    },
    {
        id: 'pink',
        label: 'Not Green 1',
        hex: '#ffcccc'
    },
    {
        id: 'lavender',
        label: 'Not Green 2',
        hex: '#ccccff'
    },
    {
        id: 'yellow',
        label: 'Not Green 3',
        hex: '#ffffcc'
    },
    {
        id: 'rose',
        label: 'Not Green 4',
        hex: '#ffccff'
    },
    {
        id: 'cyan',
        label: 'Not Green 5',
        hex: '#ccffff'
    },
    {
        id: 'white',
        label: 'Really Really Light',
        hex: '#ffffff'
    },
];

let currentTheme = localStorage.getItem('qr_theme') || 'classic';

function applyTheme(id) {
    document.documentElement.setAttribute('data-theme', id === 'classic' ? '' : id);
    currentTheme = id;
    localStorage.setItem('qr_theme', id);
    renderThemeGrid();
}

function renderThemeGrid() {
    const grid = document.getElementById('themeGrid');
    grid.innerHTML = THEMES.map(t => `
    <div class="theme-option${t.id === currentTheme ? ' selected' : ''}" data-theme-id="${t.id}">
      <span class="theme-swatch" style="background:${t.hex}"></span>
      ${t.label}
    </div>`).join('');
    grid.querySelectorAll('.theme-option').forEach(el => {
        el.addEventListener('click', () => {
            applyTheme(el.dataset.themeId);
            closeModal('themeModal');
        });
    });
}
applyTheme(currentTheme);

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
let qrInstance = null;
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

function updateQR() {
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
    saveBtn.style.display = currentUser ? 'block' : 'none';

    if (!qrInstance) {
        qrInstance = new QRious({
            element: canvas,
            size: 300,
            level: 'M'
        });
    }
    qrInstance.value = currentData;
    document.getElementById('qrDataPre').textContent = currentData;
}

// Live input listeners
['urlInput', 'textInput', 'wssid', 'wpass', 'cfn', 'cln', 'cph', 'cem', 'corg', 'curl'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', updateQR);
});
document.getElementById('wsec').addEventListener('change', updateQR);
document.getElementById('whidden').addEventListener('change', updateQR);

document.getElementById('clearBtn').addEventListener('click', () => {
    ['urlInput', 'textInput', 'wssid', 'wpass', 'cfn', 'cln', 'cph', 'cem', 'corg', 'curl'].forEach(id => {
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

/* -- MODALS -- */
function openModal(id) {
    document.getElementById(id).classList.add('open');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('open');
}

document.querySelectorAll('[data-close]').forEach(btn => {
    btn.addEventListener('click', () => closeModal(btn.dataset.close));
});
document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
        if (e.target === overlay) closeModal(overlay.id);
    });
});

document.getElementById('themeBtn').addEventListener('click', () => {
    renderThemeGrid();
    openModal('themeModal');
});

/* -- AUTH TABS -- */
document.querySelectorAll('.modal-tab').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.modal-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const mode = btn.dataset.auth;
        document.getElementById('authLoginForm').style.display = mode === 'login' ? 'block' : 'none';
        document.getElementById('authRegisterForm').style.display = mode === 'register' ? 'block' : 'none';
        document.getElementById('authMsg').textContent = '';
    });
});

/* -- AUTH STATE -- */
let currentUser = null;

function setAuthBtn() {
    const btn = document.getElementById('authBtn');
    const logoutBtn = document.getElementById('logoutBtn');
    if (currentUser) {
        btn.textContent = '📁 My QRs';
        logoutBtn.style.display = '';
        document.getElementById('saveQrBtn').style.display = currentData ? 'block' : 'none';
    } else {
        btn.textContent = 'Register / Login';
        logoutBtn.style.display = 'none';
        document.getElementById('saveQrBtn').style.display = 'none';
    }
}

function triggerPasswordSave(username, password) {
    const form = document.getElementById('pwSaveForm');
    document.getElementById('pwSaveUsername').value = username;
    document.getElementById('pwSavePassword').value = password;
    // Briefly show and submit so the browser password manager intercepts it
    form.style.display = '';
    form.style.position = 'fixed';
    form.style.opacity = '0';
    form.style.pointerEvents = 'none';
    form.requestSubmit();
    setTimeout(() => {
        form.style.display = 'none';
        form.style.position = '';
        form.style.opacity = '';
        form.style.pointerEvents = '';
    }, 500);
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
    setAuthBtn();
    showToast('Logged out.');
});

document.getElementById('authBtn').addEventListener('click', () => {
    if (currentUser) {
        loadMyQRs();
        openModal('myQrModal');
    } else {
        openModal('authModal');
    }
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
        currentUser = data.user;
        localStorage.setItem('qr_session', data.token);
        triggerPasswordSave(username, password);
        closeModal('authModal');
        setAuthBtn();
        showToast('Welcome back!');
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
    } catch (e) {
        msg.className = 'auth-msg error';
        msg.textContent = e.message;
    }
});

/* -- SESSION RESTORE -- */
(async () => {
    const token = localStorage.getItem('qr_session');
    if (!token) return;
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
    } catch {}
})();

/* -- SAVE QR -- */
document.getElementById('saveQrBtn').addEventListener('click', async () => {
    if (!currentUser || !currentData) return;
    const canvas = document.getElementById('qrCanvas');

    canvas.toBlob(async blob => {
        const formData = new FormData();
        formData.append('image', blob, 'qr.webp');
        formData.append('data', currentData);
        formData.append('type', activeTab);
        formData.append('token', localStorage.getItem('qr_session'));

        try {
            const res = await fetch('/api/qr-save', {
                method: 'POST',
                body: formData
            });
            if (!res.ok) throw new Error((await res.json()).error);
            showToast('QR saved!');
        } catch (e) {
            showToast('Save failed: ' + e.message);
        }
    }, 'image/webp', 0.85);
});

/* -- MY QRs -- */
async function loadMyQRs() {
    const grid = document.getElementById('myQrGrid');
    grid.innerHTML = '<p class="empty-state">Loading…</p>';
    const token = localStorage.getItem('qr_session');
    try {
        const res = await fetch(`/api/qr-list?token=${encodeURIComponent(token)}`);
        const data = await res.json();
        if (!data.qrs || !data.qrs.length) {
            grid.innerHTML = '<p class="empty-state">No saved QR codes yet.</p>';
            return;
        }
        grid.innerHTML = data.qrs.map(q => `
      <div class="qr-card" data-id="${q.id}">
        <img src="${q.image_url}" alt="QR Code" loading="lazy" />
        <div class="qr-card-label">${escHtml(q.data_preview)}</div>
        <div class="qr-card-actions">
          <a href="${q.image_url}" download="qr-${q.id}.webp" class="btn-ghost" style="text-align:center;font-size:.72rem;padding:5px">⬇</a>
          <button class="btn-ghost" onclick="deleteQR('${q.id}')">🗑</button>
        </div>
      </div>`).join('');
    } catch {
        grid.innerHTML = '<p class="empty-state">Failed to load.</p>';
    }
}

window.deleteQR = async (id) => {
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
        btn.querySelector('.pw-icon-show').style.display = showing ? '' : 'none';
        btn.querySelector('.pw-icon-hide').style.display = showing ? 'none' : '';
    });
});

/* -- SERVICE WORKER -- */
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
}