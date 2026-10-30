# Hiding where images are stored (portable)

A small API route that sends an image's bytes rather than its address, and a
page that shows, opens and downloads those bytes through `blob:` URLs. Once it
is in, the browser never learns where an image is kept. That holds for the
markup, the network panel, an image opened in a new tab and a saved file.

It fits any site that keeps per-user images in object storage and currently hands
the browser a direct link to each one. Nothing here depends on a framework, a
storage vendor or a hosting platform. The examples are plain JavaScript with a
Node-style `(req, res)` handler. They translate line for line to anything else.

## What it is for

The usual way to show a stored image is to save its public URL next to the
record, send that URL in the list response and put it in an `<img src>`. Every
step of that publishes the storage address:

- **The list response carries it.** Anyone with the network panel open can read
  every address in the account.
- **The markup carries it.** "Open image in new tab" or "Copy image address"
  takes you straight to the bucket.
- **The download carries it.** The browser ignores the `download` attribute on a
  cross-origin link, so a Download button just navigates to the bucket and
  shows the address in the bar.

Showing the address is a problem in itself. It names your storage provider,
your bucket, your folder layout and often a user id. It also tends to be
permanent, so it keeps working after the record that pointed to it is deleted,
after the session ends, and for anyone it gets pasted to.

**The rule the whole design rests on: the storage address never leaves the
server.** The browser asks for an image by the record's id and gets back the
picture. It never gets back where the picture lives.

## The mechanism, in three parts

### 1. The list stops sending the address

Whatever endpoint returns the user's items drops the image URL column from its
response. The item's id is all the page needs.

```js
// before
.select('id, title, image_url, created_at')

// after: the picture is fetched by id from the image route
.select('id, title, created_at')
```

If the database stores **only** a full URL and not the storage key, start
storing the key (the object path inside the bucket) on every write. If you
can't migrate old rows yet, have the server work out the key from the URL.
The route needs a key, because it reads through the storage SDK and not over
the public URL.

### 2. The image route sends the bytes

One route, `GET /api/image?id=<record id>`:

1. **Authenticate** from the `Authorization` header.
2. **Look the record up by id _and_ owner** in one query, so a record that
   belongs to someone else can't be told apart from one that doesn't exist.
3. **Read the object** from storage by its key with the server's credentials.
4. **Send the bytes** with the headers below.

```js
export default async function handler(req, res) {
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method not allowed' });

  const id = req.query.id;
  if (!id) return res.status(400).json({ error: 'Missing id' });

  let userId;
  try {
    ({ userId } = await requireAuth(req)); // reads Authorization: Bearer <token>
  } catch (e) {
    return res.status(e.status || 401).json({ error: e.message });
  }

  // Owner in the WHERE clause, not checked afterwards. Someone else's
  // record and a missing one both come back as nothing.
  const row = await db.items.findOne({ id, user_id: userId }, ['image_key']);
  if (!row || !row.image_key) return res.status(404).json({ error: 'Not found' });

  const file = await storage.download(BUCKET, row.image_key); // server credentials
  if (!file) return res.status(404).json({ error: 'Image unavailable' });

  const buffer = Buffer.from(await file.arrayBuffer());
  res.setHeader('Content-Type', file.type || 'image/png');
  res.setHeader('Content-Length', buffer.length);
  res.setHeader('Cache-Control', 'private, max-age=86400');
  res.setHeader('Vary', 'Authorization');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  return res.status(200).send(buffer);
}
```

`storage.download` stands for whatever your provider offers: a `GetObject` on
S3 or R2, `bucket.file(key).download()` on Cloud Storage, `from(bucket).download(key)`
on Supabase, or a read from disk. All that matters is that it runs on the
server with the server's credentials.

**Response headers, and why:**

| Header | Value | Why |
| ------ | ----- | --- |
| `Content-Type` | the object's type, `image/png` as a fallback | So the blob gets the right type, and opening it in a tab shows an image rather than a download |
| `Content-Length` | byte length | Lets the browser show progress and reuse the connection |
| `Cache-Control` | `private, max-age=…` | `private` keeps a CDN or shared proxy from storing it and handing it to the next user. The max-age can be long if an image never changes under its id |
| `Vary` | `Authorization` | Belt and braces for any cache that ignores `private` |
| `X-Content-Type-Options` | `nosniff` | The browser trusts the declared type instead of guessing |

Errors come back as JSON with a status code, the same as every other API route.
The page only needs to know that the request failed.

### 3. The page shows bytes, never addresses

For each item, the page fetches the image with the session header, turns the
response into a Blob, and makes an object URL for it. That object URL is the
only thing that goes into the DOM.

```js
async function fetchBlob(url, options) {
  const r = await fetch(url, options);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.blob();
}

// Object URLs for the grid currently on screen, released on every redraw.
let liveUrls = [];

function renderGrid(grid, items, token) {
  liveUrls.forEach((u) => URL.revokeObjectURL(u));
  liveUrls = [];

  grid.innerHTML = items.map(() => `
    <div class="card">
      <img alt="Image" title="Open image" />
      <button type="button" data-download>Download</button>
    </div>`).join('');

  grid.querySelectorAll('.card').forEach((el, i) => {
    const item = items[i];
    const img = el.querySelector('img');

    // Start now so the image is usually ready before anyone presses anything.
    const loaded = fetchBlob(`/api/image?id=${encodeURIComponent(item.id)}`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then((blob) => {
      const url = URL.createObjectURL(blob);
      liveUrls.push(url);
      img.src = url;
      return blob;
    });
    loaded.catch(() => { img.alt = 'Image unavailable'; });

    // Open straight from the click, without awaiting anything first, so the
    // popup blocker treats it as something the user did.
    img.addEventListener('click', () => {
      if (img.src) window.open(img.src, '_blank');
    });

    el.querySelector('[data-download]').addEventListener('click', () => {
      loaded.then((blob) => saveBlob(blob, `image-${item.id}.png`),
                  () => alert('That image could not be loaded.'));
    });
  });
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;          // honoured, because blob: is same-origin
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Some browsers start the download after click() returns.
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
```

Opened in a tab or saved to disk, what the user sees is
`blob:https://your-site/3f1c…`, a random id that only means anything inside
that one page, plus a file name you chose.

Images that never come from the server should go the same way, so every image
behaves the same. That covers a `<canvas>` (`canvas.toBlob`) and a data URL
kept in local storage (`fetch(dataUrl).then(r => r.blob())`).

## The details that are easy to get wrong

- **The token goes in a header, not the query string.** `?token=…` ends up in
  server logs, CDN logs, browser history and any `Referer` the page sends. A
  plain `<img src="/api/image?id=…&token=…">` would avoid the blob step, but
  only by leaking the session instead.
- **Ownership is part of the query.** Fetching by id and checking the owner
  afterwards works, but it's easy to forget on the next route someone writes,
  and it tends to answer 403. A 403 tells the caller the id exists. Return 404
  for both.
- **Never let a CDN cache it.** Some hosts cache GET responses from API routes
  unless told otherwise. Without `private`, the first user's image can be served
  to everyone who asks for that id.
- **Read by key, not by fetching the public URL from the server.** A server-side
  fetch of the public URL works while the bucket is public and breaks the day
  you make it private, which is the natural next step (see below).
- **Response size limits.** Serverless platforms cap response bodies, often at a
  few megabytes. Thumbnails and small graphics fit easily. For large originals,
  stream the object to the response instead of buffering it, or serve a resized
  copy.
- **Revoke object URLs, but not too early.** A URL revoked straight after
  `click()` can cancel a download that hasn't started, and one revoked while its
  `<img>` is on screen breaks "open in new tab". Release them when the view that
  owns them goes away. Never keeping them leaks memory on every redraw.
- **Popup blockers.** `window.open` only counts as user-initiated if it runs
  inside the click handler, before any `await`. If the blob isn't ready yet,
  say so instead of awaiting and then opening.
- **`<a download>` on a cross-origin URL is ignored.** That is why the old
  Download button navigated to the bucket, and why a same-origin `blob:` URL
  fixes it.
- **Don't swap this for base64 in JSON.** Putting every image inline in the list
  response as a data URL also hides the address. But it makes the list a third
  larger per image, stops it from loading progressively, and can't be cached
  per image.
- **Old copies of the list still carry addresses.** A service worker or HTTP
  cache that stored list responses before the change keeps serving the old
  shape until it's replaced. Bump the worker's version so it is.
- **Load concurrency.** A grid of fifty items is fifty requests at once. That's
  usually fine. If the platform bills or limits per invocation, load images
  as they scroll into view (`IntersectionObserver`), or a few at a time.

## Service worker, if there is one

- An image request is an ordinary GET under `/api/`, so a network-first rule
  can keep the last copy for offline use. Note that `cache.match` ignores
  request headers. The cache key is the URL alone, so keep cached images per
  origin, never across accounts on a shared device, or clear the runtime cache
  on sign out.
- Only cache `response.ok`. A 401 cached by URL keeps an image broken after
  the user signs back in.

## Afterwards: make the bucket private

The route reads with server credentials, so the bucket no longer needs to be
public for the site to work. Until it's private, every address handed out before
the change still opens for anyone who has one.

Before flipping it, find anything else that relies on the public URLs: emails,
chat bots, exports, embeds on other sites. Each of those either needs to send
bytes itself, or get a short-lived signed URL made at the moment it's needed.

A signed URL is **not** a replacement for this route on the site. It still shows
the provider, bucket and path. It only stops working after a while.

## Checking it works

1. The list response contains no storage addresses. Search the JSON for the
   provider's hostname.
2. The rendered page source contains no storage addresses.
3. Every `<img>` in the grid has a `blob:` `src`.
4. Opening an image in a new tab shows a `blob:` URL in the address bar.
5. Download saves a file with the name you chose, and the network panel shows
   no request to the storage host.
6. The image route answers:
   - your own id: `200`, an image content type, `Cache-Control: private`
   - someone else's id: `404`
   - an id that doesn't exist: `404`
   - no token or a bad token: `401`
   - any method but GET: `405`
7. With the bucket set to private, everything above still works.

## What this is not

- **It's not copy protection.** Whoever can see an image can save it. This
  hides where images are kept, not what they show.
- **It's not access control by itself.** The ownership check in the route is.
  If the route skips it, any id becomes a working link to someone else's
  image, just one that shows a nicer address.
- **It doesn't hide anything from the server**, the storage provider or anyone
  with the server's credentials.
