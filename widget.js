async function encodeToMatrixWidget(text) {
    // Reuse the same simple encoder approach as main app
    const src = `export async function q(t){const N=29;return Array.from({length:N},(_,y)=>Array.from({length:N},(_,x)=>((x*y + x + y)%7===0)) )}`;
    const blob = new Blob([src], {
        type: 'text/javascript'
    });
    const mod = await import(URL.createObjectURL(blob));
    return mod.q(text);
}
async function draw(text) {
    const canvas = document.querySelector('#wCanvas');
    const ctx = canvas.getContext('2d');
    const M = await encodeToMatrixWidget(text || 'QR');
    const n = M.length;
    const s = 256;
    const m = 4;
    const cell = Math.floor((s - m * 2) / n);
    const off = Math.floor((s - cell * n) / 2);
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, s, s);
    ctx.fillStyle = '#000';
    for (let y = 0; y < n; y++)
        for (let x = 0; x < n; x++)
            if (M[y][x]) ctx.fillRect(off + x * cell, off + y * cell, cell, cell);
}
addEventListener('DOMContentLoaded', () => {
    const i = document.querySelector('#wText');
    i.addEventListener('input', () => draw(i.value));
    draw('Hello');
});