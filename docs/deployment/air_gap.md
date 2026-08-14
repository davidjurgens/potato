# Air-Gapped and Offline Deployment

Potato is often run on networks with no outbound internet access — secure
research environments, clinical settings, field deployments, or simply a machine
behind a strict proxy.

**Status: partially supported.** Read this page before deploying offline; some
of the interface still reaches out to public CDNs and will degrade without them.

## What works offline today

| Asset | Status |
|-------|--------|
| **Fabric.js** (image annotation canvas) | ✅ Vendored at `potato/static/vendor/fabric-5.3.1.min.js` |
| Peaks.js (audio/video waveforms) | ✅ Vendored at `potato/static/peaks.min.js` |
| PDF.js (PDF display) | ✅ Vendored at `potato/static/vendor/pdfjs/` |
| Bootstrap CSS + Font Awesome on the **adjudication** page | ✅ Vendored |
| All of Potato's own CSS and JavaScript | ✅ Served locally |

Fabric.js matters most: image annotation is entirely non-functional without it —
the canvas never initializes, so the tools render but nothing can be drawn.

## What still requires internet access

`base_template_v2.html` — the template behind the main annotation interface —
still loads three assets from public CDNs:

| Asset | Host | Effect when unreachable |
|-------|------|-------------------------|
| jQuery 3.6.0 | `code.jquery.com` | **Span (text) annotation breaks.** jQuery is a hard dependency there. |
| Bootstrap 5.1.3 (CSS + JS) | `cdn.jsdelivr.net` | Layout and spacing degrade; dropdowns, modals, and tooltips stop working. |
| Font Awesome 6.0.0 | `cdnjs.cloudflare.com` | Icons render as empty boxes. Labels remain readable. |

Bootstrap CSS and Font Awesome are *already vendored* for the adjudication page,
but at **different versions** (Bootstrap 5.3.3, Font Awesome 6.7.2) than the CDN
copies used here. Pointing the main template at them is therefore a version bump
— Bootstrap 5.1 → 5.3 introduces colour modes and renames CSS variables — and
needs a full-application regression pass rather than a one-line edit. Bootstrap's
JavaScript bundle is not vendored at all.

**If you are deploying air-gapped now**, mirror those three files onto a host
your network can reach and override the template, or accept the degradation
above. Text annotation in particular should be tested before you rely on it.

## Managing vendored assets

`scripts/vendor_assets.py` is the manifest and the tool:

```bash
python scripts/vendor_assets.py --check    # verify committed files against pinned hashes
python scripts/vendor_assets.py            # download anything missing
python scripts/vendor_assets.py --force    # re-download everything
```

Every download is verified against the CDN's published Subresource Integrity
hash and is **refused** on mismatch. These files are committed to the
repository, so an unverified download would ship to every user.

## Adding a new frontend dependency

Vendor it. `tests/unit/test_no_new_cdn_assets.py` fails the build if a new
external `<script>` or `<link>` appears in the main template, so this is
enforced rather than remembered.

If a dependency genuinely cannot be vendored yet, add its host to
`ALLOWED_EXTERNAL` in that test **with a note explaining why**. Each entry is
tracked work, not an exemption — and the test also fails if an allowlist entry
becomes stale, so the list keeps meaning something.

## Related

- [Deployment overview](../deployment/reverse-proxy.md)
- [Image annotation](../annotation-types/multimedia/image_annotation.md)
