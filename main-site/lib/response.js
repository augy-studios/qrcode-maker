export const ok = (res, data, status = 200) =>
    res.status(status).json(data);

export const err = (res, msg, status = 400) =>
    res.status(status).json({
        error: msg
    });