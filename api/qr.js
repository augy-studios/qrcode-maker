// api/qr.js
// POST /api/qr
// Body: { data, format, darkColor, lightColor, logoUrl?, size? }
// Returns: { image: "data:image/png;base64,..." } or SVG string

import QRCode from 'qrcode';
import sharp from 'sharp';
import https from 'https';
import http from 'http';

const DEFAULT_SIZE = 400;
const LOGO_RATIO = 0.22; // logo occupies ~22% of QR width

function fetchBuffer(url) {
    return new Promise((resolve, reject) => {
        const client = url.startsWith('https') ? https : http;
        client.get(url, (res) => {
            const chunks = [];
            res.on('data', c => chunks.push(c));
            res.on('end', () => resolve(Buffer.concat(chunks)));
            res.on('error', reject);
        }).on('error', reject);
    });
}

export default async function handler(req, res) {
    // CORS
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
    if (req.method === 'OPTIONS') return res.status(200).end();
    if (req.method !== 'POST') return res.status(405).json({
        error: 'Method not allowed'
    });

    const {
        data,
        format = 'png', // 'png' | 'svg'
        darkColor = '#000000',
        lightColor = '#ffffff',
        logoUrl = null,
        size = DEFAULT_SIZE
    } = req.body;

    if (!data || typeof data !== 'string' || !data.trim()) {
        return res.status(400).json({
            error: 'Missing or invalid "data" field'
        });
    }

    const safeSize = Math.min(Math.max(parseInt(size) || DEFAULT_SIZE, 100), 1000);

    try {
        // ── SVG path ──────────────────────────────────────────────────────────────
        if (format === 'svg') {
            const svg = await QRCode.toString(data, {
                type: 'svg',
                color: {
                    dark: darkColor,
                    light: lightColor
                },
                width: safeSize,
                margin: 2
            });
            res.setHeader('Content-Type', 'application/json');
            return res.status(200).json({
                svg
            });
        }

        // ── PNG path ───────────────────────────────────────────────────────────────
        // 1. Generate base QR as PNG buffer
        const qrBuffer = await QRCode.toBuffer(data, {
            type: 'png',
            color: {
                dark: darkColor,
                light: lightColor
            },
            width: safeSize,
            margin: 2
        });

        // 2. Overlay logo if provided
        if (logoUrl) {
            let logoBuffer;
            // Support base64 data URLs from the client
            if (logoUrl.startsWith('data:')) {
                const base64 = logoUrl.split(',')[1];
                logoBuffer = Buffer.from(base64, 'base64');
            } else {
                logoBuffer = await fetchBuffer(logoUrl);
            }

            const logoSize = Math.round(safeSize * LOGO_RATIO);
            const pad = 8; // white padding around logo

            // Resize + pad logo
            const paddedLogo = await sharp(logoBuffer)
                .resize(logoSize, logoSize, {
                    fit: 'contain',
                    background: {
                        r: 255,
                        g: 255,
                        b: 255,
                        alpha: 1
                    }
                })
                .extend({
                    top: pad,
                    bottom: pad,
                    left: pad,
                    right: pad,
                    background: {
                        r: 255,
                        g: 255,
                        b: 255,
                        alpha: 1
                    }
                })
                .png()
                .toBuffer();

            const finalSize = logoSize + pad * 2;
            const offset = Math.round((safeSize - finalSize) / 2);

            const composed = await sharp(qrBuffer)
                .composite([{
                    input: paddedLogo,
                    top: offset,
                    left: offset
                }])
                .png()
                .toBuffer();

            const b64 = composed.toString('base64');
            return res.status(200).json({
                image: `data:image/png;base64,${b64}`
            });
        }

        const b64 = qrBuffer.toString('base64');
        return res.status(200).json({
            image: `data:image/png;base64,${b64}`
        });

    } catch (err) {
        console.error('QR generation error:', err);
        return res.status(500).json({
            error: 'QR generation failed',
            detail: err.message
        });
    }
}