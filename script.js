// ── Service Worker ────────────────────────────
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () =>
        navigator.serviceWorker.register('/sw.js')
        .then(r => console.log('SW registered', r.scope))
        .catch(e => console.warn('SW failed', e))
    );
}

// ── State ─────────────────────────────────────
let activeTab = 'url';
let logoDataUrl = null; // base64 of uploaded logo
let lastResult = null; // { image, svg, format, data }
const HISTORY_KEY = 'qrgen_history';
const MAX_HISTORY = 20;

// ── DOM refs ──────────────────────────────────
const tabBtns = document.querySelectorAll('.tab-btn');
const tabPanes = document.querySelectorAll('.tab-pane');
const customSection = document.getElementById('customisation-section');
const generateBtn = document.getElementById('generate-btn');
const genBtnText = document.getElementById('gen-btn-text');
const genSpinner = document.getElementById('gen-spinner');
const darkColorEl = document.getElementById('dark-color');
const lightColorEl = document.getElementById('light-color');
const darkHexEl = document.getElementById('dark-color-hex');
const lightHexEl = document.getElementById('light-color-hex');
const sizeSlider = document.getElementById('qr-size');
const sizeLabel = document.getElementById('size-label');
const logoUpload = document.getElementById('logo-upload');
const logoBrowseBtn = document.getElementById('logo-browse-btn');
const logoClearBtn = document.getElementById('logo-clear-btn');
const logoDropZone = document.getElementById('logo-drop-zone');
const logoDropLabel = document.getElementById('logo-drop-label');
const qrPlaceholder = document.getElementById('qr-placeholder');
const qrResult = document.getElementById('qr-result');
const qrImg = document.getElementById('qr-img');
const qrMeta = document.getElementById('qr-meta');
const downloadBtn = document.getElementById('download-btn');
const copyBtn = document.getElementById('copy-btn');
const qrError = document.getElementById('qr-error');
const qrErrorMsg = document.getElementById('qr-error-msg');
const historyList = document.getElementById('history-list');
const clearHistoryBtn = document.getElementById('clear-history-btn');

// ── Tab switching ─────────────────────────────
tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        const tab = btn.dataset.tab;
        activeTab = tab;

        tabBtns.forEach(b => {
            b.classList.remove('active');
            b.setAttribute('aria-selected', 'false');
        });
        tabPanes.forEach(p => p.classList.remove('active'));

        btn.classList.add('active');
        btn.setAttribute('aria-selected', 'true');
        document.getElementById(`tab-${tab}`).classList.add('active');

        // Hide customisation panel on history tab
        customSection.style.display = tab === 'history' ? 'none' : '';

        if (tab === 'history') renderHistory();
    });
});

// ── Colour pickers ────────────────────────────
darkColorEl.addEventListener('input', () => {
    darkHexEl.textContent = darkColorEl.value;
});
lightColorEl.addEventListener('input', () => {
    lightHexEl.textContent = lightColorEl.value;
});

// ── Size slider ───────────────────────────────
sizeSlider.addEventListener('input', () => {
    sizeLabel.textContent = sizeSlider.value + 'px';
});

// ── Logo upload / drag-drop ───────────────────
logoBrowseBtn.addEventListener('click', () => logoUpload.click());
logoDropZone.addEventListener('click', e => {
    if (e.target !== logoClearBtn) logoUpload.click();
});

logoUpload.addEventListener('change', e => {
    const file = e.target.files[0];
    if (file) loadLogo(file);
});

logoDropZone.addEventListener('dragover', e => {
    e.preventDefault();
    logoDropZone.classList.add('drag-over');
});
logoDropZone.addEventListener('dragleave', () => logoDropZone.classList.remove('drag-over'));
logoDropZone.addEventListener('drop', e => {
    e.preventDefault();
    logoDropZone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith('image/')) loadLogo(file);
});

logoClearBtn.addEventListener('click', e => {
    e.stopPropagation();
    logoDataUrl = null;
    logoUpload.value = '';
    logoDropLabel.innerHTML = 'Drop image or <button type="button" class="link-btn" id="logo-browse-btn">browse</button>';
    document.getElementById('logo-browse-btn').addEventListener('click', () => logoUpload.click());
    logoClearBtn.hidden = true;
    logoDropZone.classList.remove('has-logo');
});

function loadLogo(file) {
    const reader = new FileReader();
    reader.onload = e => {
        logoDataUrl = e.target.result;
        logoDropLabel.textContent = `✓ ${file.name}`;
        logoClearBtn.hidden = false;
        logoDropZone.classList.add('has-logo');
    };
    reader.readAsDataURL(file);
}

// ── Build QR data string ──────────────────────
function buildData() {
    if (activeTab === 'url') {
        let v = document.getElementById('url-input').value.trim();
        if (!v) return null;
        if (!/^https?:\/\//i.test(v)) v = 'https://' + v;
        return v;
    }
    if (activeTab === 'text') {
        const v = document.getElementById('text-input').value.trim();
        return v || null;
    }
    if (activeTab === 'contact') {
        const fn = document.getElementById('c-first').value.trim();
        const ln = document.getElementById('c-last').value.trim();
        const ph = document.getElementById('c-phone').value.trim();
        const em = document.getElementById('c-email').value.trim();
        const og = document.getElementById('c-org').value.trim();
        const ur = document.getElementById('c-url').value.trim();
        if (!fn && !ln && !ph && !em) return null;
        return `BEGIN:VCARD\nVERSION:3.0\nFN:${fn} ${ln}\nN:${ln};${fn};;;\nORG:${og}\nTEL:${ph}\nEMAIL:${em}\nURL:${ur}\nEND:VCARD`;
    }
    return null;
}

// ── Generate ──────────────────────────────────
generateBtn.addEventListener('click', generate);

async function generate() {
    const data = buildData();
    if (!data) {
        showError('Please fill in at least one field.');
        return;
    }

    setLoading(true);
    hideError();

    const fmt = document.querySelector('input[name="fmt"]:checked').value;

    const body = {
        data,
        format: fmt,
        darkColor: darkColorEl.value,
        lightColor: lightColorEl.value,
        size: parseInt(sizeSlider.value),
        ...(logoDataUrl ? {
            logoUrl: logoDataUrl
        } : {})
    };

    try {
        const res = await fetch('/api/qr', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(body)
        });

        const json = await res.json();

        if (!res.ok) {
            showError(json.error || 'Server error. Please try again.');
            setLoading(false);
            return;
        }

        lastResult = {
            ...json,
            format: fmt,
            data
        };
        displayResult(lastResult);
        addToHistory(lastResult);
    } catch (err) {
        showError('Network error. Are you offline?');
    } finally {
        setLoading(false);
    }
}

// ── Display result ────────────────────────────
function displayResult(result) {
    qrPlaceholder.hidden = true;
    qrResult.hidden = false;
    hideError();

    if (result.format === 'svg') {
        // Render SVG inline
        const blob = new Blob([result.svg], {
            type: 'image/svg+xml'
        });
        const url = URL.createObjectURL(blob);
        qrImg.src = url;
    } else {
        qrImg.src = result.image;
    }

    // Truncate meta label
    const label = result.data.length > 60 ? result.data.slice(0, 57) + '…' : result.data;
    qrMeta.textContent = label;
}

// ── Download ──────────────────────────────────
downloadBtn.addEventListener('click', () => {
    if (!lastResult) return;
    const fmt = lastResult.format;
    const ext = fmt === 'svg' ? 'svg' : 'png';
    const mime = fmt === 'svg' ? 'image/svg+xml' : 'image/png';

    let href;
    if (fmt === 'svg') {
        href = URL.createObjectURL(new Blob([lastResult.svg], {
            type: mime
        }));
    } else {
        href = lastResult.image;
    }

    const a = document.createElement('a');
    a.href = href;
    a.download = `qrcode-${Date.now()}.${ext}`;
    a.click();
});

// ── Copy data ─────────────────────────────────
copyBtn.addEventListener('click', async () => {
    if (!lastResult) return;
    try {
        await navigator.clipboard.writeText(lastResult.data);
        copyBtn.textContent = '✓ Copied!';
        setTimeout(() => {
            copyBtn.textContent = '📋 Copy Data';
        }, 2000);
    } catch {
        copyBtn.textContent = '✗ Failed';
        setTimeout(() => {
            copyBtn.textContent = '📋 Copy Data';
        }, 2000);
    }
});

// ── History ───────────────────────────────────
function loadHistory() {
    try {
        return JSON.parse(localStorage.getItem(HISTORY_KEY)) || [];
    } catch {
        return [];
    }
}

function saveHistory(items) {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(items));
}

function addToHistory(result) {
    const items = loadHistory();
    const entry = {
        id: Date.now(),
        data: result.data,
        image: result.image || null, // SVG history stores null thumbnail
        format: result.format,
        ts: new Date().toLocaleString()
    };
    items.unshift(entry);
    if (items.length > MAX_HISTORY) items.length = MAX_HISTORY;
    saveHistory(items);
}

function renderHistory() {
    const items = loadHistory();
    historyList.innerHTML = '';

    if (!items.length) {
        historyList.innerHTML = '<li class="history-empty">No history yet. Generate a QR code to get started.</li>';
        return;
    }

    items.forEach(item => {
        const li = document.createElement('li');
        li.className = 'history-item';
        li.innerHTML = `
      ${item.image ? `<img src="${item.image}" alt="QR thumbnail" />` : `<div style="width:44px;height:44px;background:#f0fff4;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:1.2rem;">⬛</div>`}
      <div class="history-info">
        <div class="history-label">${escHtml(item.data.slice(0, 60))}${item.data.length > 60 ? '…' : ''}</div>
        <div class="history-meta">${item.format.toUpperCase()} · ${item.ts}</div>
      </div>
      <button class="history-del" data-id="${item.id}" title="Remove">✕</button>
    `;
        // Click row to reload
        li.addEventListener('click', e => {
            if (e.target.classList.contains('history-del')) return;
            if (item.image) {
                lastResult = {
                    image: item.image,
                    format: item.format,
                    data: item.data
                };
                displayResult(lastResult);
                // Switch to url tab to show result
                tabBtns[0].click();
            }
        });
        li.querySelector('.history-del').addEventListener('click', e => {
            e.stopPropagation();
            deleteHistoryItem(item.id);
        });
        historyList.appendChild(li);
    });
}

function deleteHistoryItem(id) {
    const items = loadHistory().filter(i => i.id !== id);
    saveHistory(items);
    renderHistory();
}

clearHistoryBtn.addEventListener('click', () => {
    if (confirm('Clear all history?')) {
        localStorage.removeItem(HISTORY_KEY);
        renderHistory();
    }
});

// ── Helpers ───────────────────────────────────
function setLoading(on) {
    generateBtn.disabled = on;
    genBtnText.textContent = on ? 'Generating…' : 'Generate QR Code';
    genSpinner.hidden = !on;
}

function showError(msg) {
    qrError.hidden = false;
    qrErrorMsg.textContent = msg;
    qrResult.hidden = true;
    qrPlaceholder.hidden = false;
}

function hideError() {
    qrError.hidden = true;
}

function escHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}