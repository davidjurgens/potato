"""
Web Proxy Blueprint

Provides a reverse proxy for browsing external websites within an iframe.
Used by the web agent creation mode to allow annotators to browse sites
while recording their interactions.

Security considerations:
- Strips X-Frame-Options and CSP frame-ancestors headers
- Rewrites relative URLs to route through proxy
- Injects interaction recording JavaScript
- Only active when web_agent_recorder display type is configured
- Blocks requests to private/internal IPs (SSRF protection)
"""

import ipaddress
import logging
import re
import socket
from html import escape as html_escape
from urllib.parse import urljoin, urlparse, quote

from flask import Blueprint, request, Response, current_app, session, redirect, url_for

logger = logging.getLogger(__name__)

web_proxy_bp = Blueprint('web_proxy', __name__)


def _login_required(f):
    """Require user authentication for web proxy routes."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def _is_private_ip(hostname: str) -> bool:
    """Check if a hostname resolves to a private/internal IP address."""
    # Block localhost variants
    if hostname in ('localhost', '127.0.0.1', '::1', '0.0.0.0'):
        return True

    try:
        # Resolve hostname to IP
        addr_info = socket.getaddrinfo(hostname, None)
        for family, socktype, proto, canonname, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            # Block private, loopback, link-local, and reserved ranges
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast):
                return True
            # Explicitly block cloud metadata endpoint
            if ip_str == '169.254.169.254':
                return True
    except (socket.gaierror, ValueError):
        # If we can't resolve, allow (the request will fail anyway)
        pass

    return False


def _validate_url(target_url: str) -> tuple:
    """Validate a URL for SSRF safety. Returns (is_safe, error_message)."""
    parsed = urlparse(target_url)

    # Only allow http and https schemes
    if parsed.scheme not in ('http', 'https'):
        return False, f"Scheme '{parsed.scheme}' is not allowed. Only HTTP and HTTPS are permitted."

    hostname = parsed.hostname
    if not hostname:
        return False, "No hostname found in URL."

    # Block private/internal IPs
    if _is_private_ip(hostname):
        return False, "Requests to private/internal addresses are not allowed."

    return True, ""


@web_proxy_bp.route('/api/web_agent/proxy/<path:url>')
@_login_required
def proxy(url):
    """
    Reverse proxy endpoint that fetches and serves external web content.

    Strips framing restrictions and rewrites URLs to maintain proxy routing.
    """
    import requests as req_lib

    # Reconstruct the full URL (path may have been split)
    target_url = url
    # Check for non-HTTP schemes before prepending https://
    if '://' in target_url and not target_url.startswith(('http://', 'https://')):
        # Non-HTTP scheme (ftp://, file://, etc.) — reject early
        is_safe, error_msg = _validate_url(target_url)
        if not is_safe:
            logger.warning("SSRF blocked proxy request to %s: %s", target_url, error_msg)
            return Response(
                f'<html><body><h2>Blocked</h2><p>{html_escape(error_msg)}</p></body></html>',
                status=403,
                content_type='text/html',
            )
    elif not target_url.startswith(('http://', 'https://')):
        target_url = 'https://' + target_url

    # Forward query parameters
    query_string = request.query_string.decode('utf-8')
    if query_string:
        target_url += '?' + query_string

    # SSRF protection: validate URL before fetching
    is_safe, error_msg = _validate_url(target_url)
    if not is_safe:
        logger.warning(f"SSRF blocked proxy request to {target_url}: {error_msg}")
        return Response(
            f'<html><body><h2>Blocked</h2><p>{html_escape(error_msg)}</p></body></html>',
            status=403,
            content_type='text/html',
        )

    try:
        # Fetch the target page
        headers = {
            'User-Agent': request.headers.get('User-Agent', 'Mozilla/5.0'),
            'Accept': request.headers.get('Accept', '*/*'),
            'Accept-Language': request.headers.get('Accept-Language', 'en-US,en;q=0.9'),
        }

        resp = req_lib.get(
            target_url,
            headers=headers,
            timeout=15,
            allow_redirects=True,
            stream=True,
        )

        # Get content type
        content_type = resp.headers.get('Content-Type', 'text/html')

        # For HTML content, rewrite URLs and inject recording script
        if 'text/html' in content_type:
            body = resp.text
            body = _rewrite_urls(body, resp.url)
            body = _inject_recorder_script(body)

            # Build response, stripping frame restrictions
            proxy_resp = Response(body, status=resp.status_code)
            proxy_resp.headers['Content-Type'] = content_type
        else:
            # For non-HTML (CSS, JS, images), pass through
            proxy_resp = Response(
                resp.content,
                status=resp.status_code,
                content_type=content_type,
            )

        # Remove framing restrictions
        proxy_resp.headers.pop('X-Frame-Options', None)
        proxy_resp.headers.pop('Content-Security-Policy', None)

        # Set permissive CSP
        proxy_resp.headers['X-Frame-Options'] = 'ALLOWALL'

        return proxy_resp

    except Exception as e:
        logger.error(f"Proxy error for {target_url}: {e}")
        return Response(
            f'<html><body><h2>Proxy Error</h2><p>Could not load: {html_escape(target_url)}</p>'
            f'<p>Error: {html_escape(str(e))}</p></body></html>',
            status=502,
            content_type='text/html',
        )


@web_proxy_bp.route('/api/web_agent/check_frameable')
@_login_required
def check_frameable():
    """
    Check if a URL can be loaded in an iframe.

    Returns JSON with {frameable: true/false, reason: string}.
    """
    import requests as req_lib

    url = request.args.get('url', '')
    if not url:
        return {'frameable': False, 'reason': 'No URL provided'}

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    # SSRF protection
    is_safe, error_msg = _validate_url(url)
    if not is_safe:
        logger.warning(f"SSRF blocked check_frameable request to {url}: {error_msg}")
        return {'frameable': False, 'reason': error_msg}

    try:
        resp = req_lib.head(url, timeout=5, allow_redirects=True)

        # Check X-Frame-Options
        xfo = resp.headers.get('X-Frame-Options', '').upper()
        if xfo in ('DENY', 'SAMEORIGIN'):
            return {'frameable': False, 'reason': f'X-Frame-Options: {xfo}'}

        # Check CSP frame-ancestors
        csp = resp.headers.get('Content-Security-Policy', '')
        if 'frame-ancestors' in csp:
            # Simple check - if it specifies frame-ancestors, likely restrictive
            if "'none'" in csp or "'self'" in csp:
                return {'frameable': False, 'reason': 'CSP frame-ancestors restriction'}

        return {'frameable': True, 'reason': 'OK'}

    except Exception as e:
        return {'frameable': False, 'reason': str(e)}


def _rewrite_urls(html_content: str, base_url: str) -> str:
    """Rewrite relative URLs in HTML to route through proxy."""
    parsed_base = urlparse(base_url)
    base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}"

    # Rewrite href and src attributes with absolute URLs
    def replace_url(match):
        attr = match.group(1)
        quote_char = match.group(2)
        url_val = match.group(3)

        if url_val.startswith(('data:', 'javascript:', 'mailto:', '#', 'blob:')):
            return match.group(0)

        # Make absolute
        if url_val.startswith('//'):
            abs_url = f"{parsed_base.scheme}:{url_val}"
        elif url_val.startswith('/'):
            abs_url = base_origin + url_val
        elif url_val.startswith(('http://', 'https://')):
            abs_url = url_val
        else:
            abs_url = urljoin(base_url, url_val)

        proxy_url = f"/api/web_agent/proxy/{abs_url}"
        return f'{attr}={quote_char}{proxy_url}{quote_char}'

    pattern = r'(href|src|action)=(["\'])(.*?)\2'
    html_content = re.sub(pattern, replace_url, html_content, flags=re.IGNORECASE)

    return html_content


def _inject_recorder_script(html_content: str) -> str:
    """Inject the interaction recording script into proxied HTML."""
    recorder_script = '''
    <script>
    // Notify parent frame of page load
    if (window.parent !== window) {
        window.parent.postMessage({
            type: 'proxy-page-loaded',
            url: window.location.href,
            title: document.title
        }, '*');

        // Forward interaction events to parent
        ['click', 'input', 'scroll', 'keydown'].forEach(function(eventType) {
            document.addEventListener(eventType, function(e) {
                var rect = e.target ? e.target.getBoundingClientRect() : {};
                window.parent.postMessage({
                    type: 'proxy-interaction',
                    eventType: eventType,
                    x: e.clientX || 0,
                    y: e.clientY || 0,
                    target: {
                        tag: e.target ? e.target.tagName : '',
                        text: e.target ? (e.target.textContent || '').substring(0, 100) : '',
                        id: e.target ? e.target.id : '',
                        className: e.target ? e.target.className : '',
                        bbox: rect ? [rect.left, rect.top, rect.right, rect.bottom] : []
                    },
                    key: e.key || '',
                    value: e.target ? (e.target.value || '') : '',
                    scrollX: window.scrollX,
                    scrollY: window.scrollY,
                    timestamp: Date.now() / 1000
                }, '*');
            }, true);
        });

        // Track mouse movement (throttled)
        var lastMouseMove = 0;
        document.addEventListener('mousemove', function(e) {
            var now = Date.now();
            if (now - lastMouseMove > 50) {
                lastMouseMove = now;
                window.parent.postMessage({
                    type: 'proxy-mousemove',
                    x: e.clientX,
                    y: e.clientY,
                    timestamp: now / 1000
                }, '*');
            }
        }, true);
    }
    </script>
    '''

    # Insert before closing </body> or at end
    if '</body>' in html_content.lower():
        insert_pos = html_content.lower().rfind('</body>')
        return html_content[:insert_pos] + recorder_script + html_content[insert_pos:]
    else:
        return html_content + recorder_script
