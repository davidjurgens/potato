/**
 * Device routing for the annotation page.
 *
 * Phones and tablets that identify themselves in the User-Agent are already
 * redirected to /pocket server-side (see routes.py annotate()). This script
 * covers what the server cannot see:
 *
 * 1. Touch devices with desktop User-Agents (iPadOS Safari reports itself as
 *    Macintosh): detected here via the primary-pointer media query and
 *    redirected to /pocket when the task supports it.
 * 2. Touch devices on tasks that are NOT touch-capable (spans, bounding
 *    boxes, ...): shown a dismissible warning that a desktop browser is
 *    recommended.
 * 3. Touch devices that chose "Desktop site": shown a quiet link back to the
 *    mobile interface instead of being re-redirected.
 * 4. Desktop users on a pocket-capable task: the navbar's hidden
 *    "Compact view" link is revealed — the card-stack interface is open to
 *    everyone, routing is only automatic for touch devices.
 *
 * The "Desktop site" choice (?desktop=1) is remembered in sessionStorage on
 * the client and in the Flask session on the server, so neither side loops.
 */
(function () {
    "use strict";

    var FORCE_DESKTOP_KEY = "potato_force_desktop";
    var WARNING_DISMISSED_KEY = "potato_mobile_warning_dismissed";

    function potatoUrl(path) {
        return window.potatoUrl ? window.potatoUrl(path) : path;
    }

    // Primary input is a coarse pointer (finger) — true on phones/tablets,
    // false on touchscreen laptops, where the primary pointer is the trackpad.
    function isTouchDevice() {
        try {
            return (
                window.matchMedia("(pointer: coarse)").matches &&
                navigator.maxTouchPoints > 0
            );
        } catch (e) {
            return false;
        }
    }

    function rememberDesktopChoice() {
        try {
            if (new URLSearchParams(window.location.search).get("desktop") === "1") {
                sessionStorage.setItem(FORCE_DESKTOP_KEY, "1");
            }
        } catch (e) { /* private mode etc. */ }
    }

    function desktopChosen() {
        try {
            return sessionStorage.getItem(FORCE_DESKTOP_KEY) === "1";
        } catch (e) {
            return false;
        }
    }

    function showBanner(html) {
        var banner = document.createElement("div");
        banner.id = "device-routing-banner";
        banner.setAttribute("role", "status");
        banner.style.cssText =
            "position:sticky;top:0;z-index:2000;display:flex;align-items:center;" +
            "gap:12px;padding:10px 16px;background:#fdf3e2;color:#7a5310;" +
            "border-bottom:1px solid #e2c185;font-size:14px;line-height:1.4;";
        banner.innerHTML = html;
        var dismiss = document.createElement("button");
        dismiss.type = "button";
        dismiss.textContent = "Dismiss";
        dismiss.style.cssText =
            "margin-left:auto;min-height:38px;padding:6px 14px;border:1px solid #e2c185;" +
            "border-radius:8px;background:transparent;color:inherit;cursor:pointer;";
        dismiss.addEventListener("click", function () {
            banner.remove();
            try { sessionStorage.setItem(WARNING_DISMISSED_KEY, "1"); } catch (e) {}
        });
        banner.appendChild(dismiss);
        document.body.insertBefore(banner, document.body.firstChild);
    }

    function warningDismissed() {
        try {
            return sessionStorage.getItem(WARNING_DISMISSED_KEY) === "1";
        } catch (e) {
            return false;
        }
    }

    function revealCompactViewLink() {
        var link = document.getElementById("compact-view-link");
        if (!link) return;
        link.href = potatoUrl("/pocket");
        link.hidden = false;
    }

    function run() {
        rememberDesktopChoice();
        var touch = isTouchDevice();

        fetch(potatoUrl("/pocket/api/routing"), { credentials: "same-origin" })
            .then(function (response) {
                if (!response.ok) throw new Error("routing unavailable");
                return response.json();
            })
            .then(function (routing) {
                if (!touch) {
                    // Desktop: no routing, just discoverability.
                    if (routing.enabled && routing.capable) {
                        revealCompactViewLink();
                    }
                    return;
                }
                // Let the server know a touch device is here even though the
                // User-Agent may claim desktop (iPad case) — admin dashboard.
                fetch(potatoUrl("/pocket/api/device_hint"), {
                    method: "POST",
                    credentials: "same-origin",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ device: "tablet" }),
                }).catch(function () {});

                if (routing.available) {
                    if (desktopChosen()) {
                        if (!warningDismissed()) {
                            showBanner(
                                'This task has a touch-friendly interface. ' +
                                '<a href="' + potatoUrl("/pocket") + '">Switch to the mobile version</a>.'
                            );
                        }
                    } else {
                        window.location.replace(potatoUrl("/pocket"));
                    }
                } else if (!routing.capable && !warningDismissed()) {
                    showBanner(
                        "Heads up: this task includes annotation types that are " +
                        "not optimized for phones or tablets. A desktop browser " +
                        "is recommended."
                    );
                }
            })
            .catch(function () { /* routing endpoint absent: do nothing */ });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", run);
    } else {
        run();
    }
})();
