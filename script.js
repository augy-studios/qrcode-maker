// Wait for QR lib (qrcode.js) to be available
function readyQRLib() {
    return new Promise(r => {
        const poll = () => (typeof qrcode === 'function') ? r() : setTimeout(poll, 50);
        poll();
    });
}

const $ = (sel) => document.querySelector(sel);
const textEl = $('#qrtext');
const apiToggle = $('#apiToggle');
const marginToggle = $('#marginToggle');
const eccSel = $('#ecc');
const sizeSel = $('#size');
const preview = $('#preview');
const apiImg = $('#apiImg');
const btnSvg = $('#downloadSvg');
const btnPng = $('#downloadPng');
const btnShare = $('#shareOut');

let currentSvg = null;
let currentPngURL = null;

function getParamsText() {
    const url = new URL(location.href);
    return url.searchParams.get('text') || '';
}

function setParamsText(v) {
    const url = new URL(location.href);
    if (v) url.searchParams.set('text', v);
    else url.searchParams.delete('text');
    history.replaceState({}, '', url);
}

function buildApiURL(data, size, ecc, margin) {
    const pad = margin ? 1 : 0; // 1 ~ quiet zone in modules (API interprets `margin` param in px) - keep small
    // QRServer create-qr-code (documented) — returns PNG
    // https://goqr.me/api/doc/create-qr-code/  (docs)  // citation in the page footer
    const params = new URLSearchParams({
        data,
        size: `${size}x${size}`,
        ecc,
        margin: String(pad * 4) // visually pleasant
    });
    return `https://api.qrserver.com/v1/create-qr-code/?${params.toString()}`;
}

async function renderAll() {
    const data = textEl.value.trim();
    const ecc = eccSel.value;
    const size = parseInt(sizeSel.value, 10);
    const quiet = marginToggle.checked;

    // Offline-first: local SVG preview (qrcode-generator)
    await readyQRLib();
    const typeNumber = 0; // auto
    const qr = qrcode(typeNumber, ecc);
    qr.addData(data || '');
    qr.make();
    const moduleCount = qr.getModuleCount();
    const scale = Math.floor(size / moduleCount) || 4;
    const margin = quiet ? 4 : 0;

    const svg = qr.createSvgTag(scale, margin);
    preview.innerHTML = svg;
    currentSvg = svg;

    // Online PNG
    const apiUrl = buildApiURL(data || ' ', size, ecc, quiet);
    apiImg.src = apiToggle.checked ? apiUrl : '';
    currentPngURL = apiToggle.checked ? apiUrl : null;

    // Update URL param to enable quick re-open / deep link
    setParamsText(data);
}

// Downloads
btnSvg.addEventListener('click', () => {
    if (!currentSvg) return;
    const blob = new Blob([currentSvg], {
        type: 'image/svg+xml'
    });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'qr.svg';
    a.click();
    URL.revokeObjectURL(a.href);
});

btnPng.addEventListener('click', async () => {
    if (!currentPngURL) {
        // Generate PNG from SVG client-side as fallback
        const canvas = document.createElement('canvas');
        const size = parseInt(sizeSel.value, 10);
        canvas.width = canvas.height = size;
        const ctx = canvas.getContext('2d');
        const img = new Image();
        const svgBlob = new Blob([currentSvg], {
            type: 'image/svg+xml'
        });
        img.onload = () => {
            ctx.fillStyle = '#fff';
            ctx.fillRect(0, 0, size, size);
            ctx.drawImage(img, 0, 0, size, size);
            const a = document.createElement('a');
            a.href = canvas.toDataURL('image/png');
            a.download = 'qr.png';
            a.click();
            URL.revokeObjectURL(img.src);
        };
        img.src = URL.createObjectURL(svgBlob);
        return;
    }

    try {
        const response = await fetch(currentPngURL);
        const blob = await response.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'qr.png';
        a.click();
        URL.revokeObjectURL(a.href);
    } catch (err) {
        console.error('Download failed', err);
        alert('Failed to download PNG. Please try again.');
    }
});

// Share out the current page (deep-link with ?text=…)
btnShare.addEventListener('click', async () => {
    const data = textEl.value.trim();
    const shareUrl = new URL(location.href);
    shareUrl.searchParams.set('text', data);
    if (navigator.share) {
        try {
            await navigator.share({
                title: 'QR Quick',
                text: data,
                url: shareUrl.toString()
            });
        } catch {}
    } else {
        // Fallback: copy link
        await navigator.clipboard.writeText(shareUrl.toString());
        btnShare.textContent = 'Link copied';
        setTimeout(() => btnShare.textContent = 'Share QR', 1500);
    }
});

// Input listeners
['input', 'change'].forEach(ev => {
    textEl.addEventListener(ev, renderAll);
    apiToggle.addEventListener(ev, renderAll);
    marginToggle.addEventListener(ev, renderAll);
    eccSel.addEventListener(ev, renderAll);
    sizeSel.addEventListener(ev, renderAll);
});

// Prefill from query (?text=...) including share target redirect
window.addEventListener('DOMContentLoaded', () => {
    const initial = getParamsText();
    if (initial) textEl.value = initial;
    renderAll();
});