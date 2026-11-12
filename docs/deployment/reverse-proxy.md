# Running Potato Behind a Reverse Proxy (URL Path Prefix)

Some deployments expose several internal Potato servers through a single public
HTTPS endpoint by mapping URL paths to different local ports:

```text
https://host/app1/  ->  http://127.0.0.1:8000/
https://host/app2/  ->  http://127.0.0.1:8001/
```

This is common in locked-down environments where opening additional public ports
is restricted. The v2.5 annotation UI loads static assets and performs
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

## What SCRIPT_NAME controls

Both options below converge on the WSGI `SCRIPT_NAME`. The app reads
`SCRIPT_NAME` (surfaced as `request.script_root`) as the single source of truth
and uses it for:

- server-rendered `url_for(...)` output (CSS/JS/static tags), and
- the client-side prefix exposed to the browser as `window.config.url_prefix`,
  which wraps `fetch()`, `navigator.sendBeacon()`, `EventSource`, and
  root-relative `href`/`action`/`src`/`poster`/`srcset` attributes (including
  dynamically inserted media and data elements), and
- the `Path` of the `session` cookie. See
  [Two studies on one host](#two-studies-on-one-host).

The helper lives in `potato/templates/_url_prefix.js`. The annotation page, the
admin pages and the dashboards all include it. If you add a page that builds a
request URL in JavaScript, include it there too:

```jinja
<script type="text/javascript">{% include '_url_prefix.js' %}</script>
```

`tests/unit/test_proxy_prefix_static_urls.py` fails if a page uses a
root-relative URL in JavaScript without the include.

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

## Two studies on one host

One host can serve several studies, for example `/app1` and `/app2` from two
Potato processes behind one nginx. Each process signs the `session` cookie with
its own key.

Flask scopes that cookie to `SESSION_COOKIE_PATH` or `APPLICATION_ROOT`. Both
default to `/`. Without a prefix, the browser keeps one cookie for the whole
host. The second login then overwrites the first study's cookie, and neither
process can verify the other's signature. The annotator returns to the login
page of the study that they did not log in to last. One study alone never shows
this problem. The second study breaks both.

Potato scopes the cookie to the prefix, so `/app1` and `/app2` hold separate
cookies and the studies do not collide. Both options below give the same
result, because both set `SCRIPT_NAME`.

Two conditions apply:

- Each service must set its own prefix. If `/app2` has no prefix, its cookie
  returns to `Path=/` and overwrites the cookie of `/app1` again.
- Give the two studies different signing keys, or share one deliberately. See
  `secret_key` and `POTATO_SECRET_KEY` in [Installation & Usage](usage.md).

To set one path for every study on the host, set `SESSION_COOKIE_PATH`. An
explicit value wins over the prefix.

Annotators do not have to clear their cookies after an upgrade. A browser sends
the longest matching path first, so the new `Path=/app1` cookie wins over a
stale `Path=/` cookie.

## Verifying

1. Load `https://host/app1/` and confirm CSS/JS load (no 404s in DevTools).
2. **Sign in.** The login form posts to `/app1/auth`, not `/auth`.
3. Make an annotation and confirm it autosaves (no "annotations not saved").
4. Navigate Next/Previous and confirm media and data render.
5. Follow Logout, and the Finish link on the last item, and confirm neither
   leaves the prefix.
6. If using live agent eval, confirm the stream connects and updates.
7. If the host serves more than one study, sign in to each one in one browser.
   Confirm that each `session` cookie shows its own `Path` in DevTools, and that
   the first study stays signed in.

Step 2 is worth doing first, and on a browser with no session. Until v2.8.3 the
login page was the one page the prefix did not reach: its two forms posted to
`/auth` and `/register` at the public root, so a task mounted below a path
could not admit a single annotator, while every page behind the login looked
correct. `/done`, `/logout` and `/pocket` were unprefixed for the same reason.

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
