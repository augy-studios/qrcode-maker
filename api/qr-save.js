import {
    createClient
} from '@supabase/supabase-js';
import {
    err
} from '../lib/response.js';
import formidable from 'formidable';
import fs from 'fs';
import sharp from 'sharp';

export const config = {
    api: {
        bodyParser: false
    }
};

const supabase = createClient(
    process.env.SUPABASE_URL,
    process.env.SUPABASE_SERVICE_ROLE_KEY
);

export default async function handler(req, res) {
    if (req.method !== 'POST') return err(res, 'Method not allowed', 405);

    const form = formidable({
        maxFileSize: 2 * 1024 * 1024
    });
    const [fields, files] = await form.parse(req);

    const token = Array.isArray(fields.token) ? fields.token[0] : fields.token;
    const data = Array.isArray(fields.data) ? fields.data[0] : fields.data;
    const type = Array.isArray(fields.type) ? fields.type[0] : fields.type;
    const imgFile = files.image ?. [0];

    if (!token || !imgFile) return err(res, 'Missing fields');

    const {
        data: authData,
        error: authErr
    } = await supabase.auth.getUser(token);
    if (authErr || !authData.user) return err(res, 'Unauthorised', 401);

    const userId = authData.user.id;
    const raw = fs.readFileSync(imgFile.filepath);

    // Compress to WebP
    const webp = await sharp(raw).webp({
        quality: 85
    }).toBuffer();
    const path = `${userId}/${Date.now()}.webp`;

    const {
        error: uploadErr
    } = await supabase.storage
        .from('qr_images')
        .upload(path, webp, {
            contentType: 'image/webp',
            upsert: false
        });
    if (uploadErr) return err(res, uploadErr.message, 500);

    const {
        data: urlData
    } = supabase.storage.from('qr_images').getPublicUrl(path);

    const {
        error: dbErr
    } = await supabase.from('qr_codes').insert({
        user_id: userId,
        type,
        qr_data: data,
        data_preview: data.slice(0, 80),
        image_path: path,
        image_url: urlData.publicUrl,
    });
    if (dbErr) return err(res, dbErr.message, 500);

    res.status(200).json({
        ok: true
    });
}