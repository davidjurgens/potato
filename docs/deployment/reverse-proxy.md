# Running Potato Behind a Reverse Proxy (URL Path Prefix)

Some deployments expose several internal Potato servers through a single public
HTTPS endpoint by mapping URL paths to different local ports:

```text
https://host/app1/  ->  http://127.0.0.1:8000/
https://host/app2/  ->  http://127.0.0.1:8001/
```

This is common in locked-down environments where opening additional public ports
is restricted. The catch: the v2.5 annotation UI loads static assets and performs
annotation actions through **root-relative** URLs (`/static/...`, `/updateinstance`,
`/annotate`, `/api/current_instance`, `/media/...`). When Potato is mounted under
`/app1`, those URLs resolve against the public *root* instead of the mounted app,
which shows up as:

- CSS/JS assets returning 404
- the annotation shell loading but the main interface staying hidden
- data/media files failing to load
- annotation autosaves failing with "annotations not saved"

Potato can apply a deployment prefix to both server-generated URLs and the
client-side requests so these deployments work without per-site nginx hacks.

## How it works

Both options below converge on the WSGI `SCRIPT_NAME`. The app reads
`SCRIPT_NAME` (surfaced as `request.script_root`) as the single source of truth
and uses it for:

- server-rendered `url_for(...)` output (CSS/JS/static tags), and
- the client-side prefix exposed to the browser as `window.config.url_prefix`,
  which wraps `fetch()`, `navigator.sendBeacon()`, `EventSource`, and
  root-relative `href`/`action`/`src` attributes (including dynamically inserted
  media and data elements).

When no prefix is configured, `SCRIPT_NAME` is empty and nothing changes — this
is a no-op for ordinary `potato start` runs.

## Option A — `POTATO_PROXY_FIX` (proxy sends `X-Forwarded-Prefix`)

Use this when you control the proxy and it can send forwarded headers. Potato
enables Werkzeug's `ProxyFix`, which reads `X-Forwarded-Prefix` (and
`X-Forwarded-Proto`/`-Host`/`-For`) per request.

```bash
export POTATO_PROXY_FIX=1
potato start config.yaml -p 8000
```

Optional trust-count overrides (default `1` each):

```bash
export POTATO_PROXY_FIX_X_FOR=1
export POTATO_PROXY_FIX_X_PROTO=1
export POTATO_PROXY_FIX_X_HOST=1
export POTATO_PROXY_FIX_X_PREFIX=1
```

nginx (proxy strips the prefix, forwards it as a header):

```nginx
location /app1/ {
    proxy_pass         http://127.0.0.1:8000/;   # trailing slash strips /app1/
    proxy_set_header   Host              $host;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_set_header   X-Forwarded-Prefix /app1;
}
```

> **Security:** `ProxyFix` trusts forwarded headers. Only enable
> `POTATO_PROXY_FIX` when the app is reachable **exclusively** through the trusted
> proxy. If the internal port is also directly reachable, a client could spoof
> `X-Forwarded-Prefix`/`-Host` and poison generated URLs.

## Option B — `POTATO_URL_PREFIX` (proxy config cannot be changed)

Use this when you cannot add forwarded headers but you know the public mount
path. Potato injects the prefix into `SCRIPT_NAME` itself.

```bash
export POTATO_URL_PREFIX=/app1
potato start config.yaml -p 8000
```

The proxy must still **strip** the prefix before forwarding, so Flask continues
to receive unprefixed paths such as `/static/styles.css`:

```nginx
location /app1/ {
    proxy_pass       http://127.0.0.1:8000/;     # trailing slash strips /app1/
    proxy_set_header Host $host;
}
```

If both variables are set, the per-request forwarded prefix wins;
`POTATO_URL_PREFIX` acts as the fallback when no `X-Forwarded-Prefix` is present.

## Live streaming (Server-Sent Events)

The live-agent and live-coding viewers use SSE (`EventSource`). The URL prefix is
applied automatically, but SSE additionally requires the proxy to **disable
buffering** on the stream location, or events will be held back:

```nginx
location /app1/api/ {
    proxy_pass            http://127.0.0.1:8000/api/;
    proxy_set_header      Host $host;
    proxy_buffering       off;
    proxy_read_timeout    3600s;
}
```

## Verifying

1. Load `https://host/app1/` and confirm CSS/JS load (no 404s in DevTools).
2. Make an annotation and confirm it autosaves (no "annotations not saved").
3. Navigate Next/Previous and confirm media and data render.
4. If using live agent eval, confirm the stream connects and updates.

## Notes and limitations

- Root-relative links inside displayed annotation **content** are also prefixed.
  Root-relative URLs are same-origin by definition, so this is generally correct,
  but content authors who intend to point at the public root should use absolute
  URLs.
- `pip`-installed deployments rely on packaged static assets; ensure you are on a
  build that includes nested `static/` directories (fonts, vendored assets).

## Related

- [Installation & Usage](usage.md)
- [HuggingFace Spaces](../data-export/huggingface_spaces.md)
