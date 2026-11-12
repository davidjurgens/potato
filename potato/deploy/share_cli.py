"""``potato share`` — put a locally-running task on a public URL for a while.

Not a deployment. The server runs in this process and the URL dies with it. For
a pilot, a lab meeting, or handing someone a link for twenty minutes.

It runs the same preflight as a real deploy, because the exposure is the same:
whatever the config allows, it allows to the whole internet.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from typing import List, Optional

from potato.deploy.preflight import render_report, run_preflight
from potato.deploy.providers.base import ProviderError
from potato.deploy.providers.tunnel import detect_backend, start_tunnel


def _echo(message: str = "") -> None:
    print(message, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="potato share",
        description="Serve a task on a temporary public HTTPS URL.")
    parser.add_argument("config_file", help="path to the task's config.yaml")
    parser.add_argument("-p", "--port", type=int, default=8000)
    parser.add_argument("--backend", default=None,
                        choices=("cloudflared", "tailscale", "ngrok"),
                        help="tunnel to use (default: whichever is installed)")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="skip the exposure confirmation")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="do not assess the config first (not recommended)")
    return parser


def _wait_for_server(port: int, timeout: float = 90.0) -> bool:
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3)
            return True
        except urllib.error.HTTPError:
            return True  # responding, even if with 4xx
        except Exception:
            time.sleep(1)
    return False


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if not os.path.isfile(args.config_file):
        _echo(f"Config file not found: {args.config_file}")
        return 1

    if not args.skip_preflight:
        report = run_preflight(args.config_file, provider="tunnel", public=True)
        _echo(render_report(report))
        _echo("")
        if not report.ok:
            _echo("Refusing to share. Fix the errors above, or pass "
                  "--skip-preflight to share anyway.")
            return 2
        if not args.yes and sys.stdin.isatty():
            answer = input("Publish this task to the internet? [y/N] ")
            if answer.strip().lower() not in ("y", "yes"):
                _echo("Aborted.")
                return 3

    try:
        backend = detect_backend(args.backend)
    except ProviderError as exc:
        _echo(str(exc))
        return 1
    _echo(f"Tunnel backend: {backend}")

    server = None
    tunnel = None
    try:
        env = dict(os.environ)
        # Behind a tunnel the app sees a proxied request; without this, url_for
        # and session cookies use the wrong scheme and host.
        env["POTATO_PROXY_FIX"] = "1"
        env["POTATO_NONINTERACTIVE"] = "1"

        server_command = [
            sys.executable, "-m", "potato.flask_server", "start", args.config_file,
            "-p", str(args.port), "--host", "127.0.0.1",
        ]
        _echo(f"Starting Potato on 127.0.0.1:{args.port} ...")
        server = subprocess.Popen(server_command, env=env)

        if not _wait_for_server(args.port):
            _echo("The server did not come up. Try running it directly to see why:")
            _echo(f"  {' '.join(server_command)}")
            return 1

        _echo("Opening tunnel ...")
        tunnel, url = start_tunnel(backend, args.port)

        _echo("")
        _echo("=" * 62)
        _echo(f"  {url}")
        _echo("=" * 62)
        _echo("")
        _echo("This link works only while this command is running.")
        if backend == "cloudflared":
            _echo("Some university and corporate networks block trycloudflare.com.")
            _echo("If participants cannot reach it, try --backend tailscale.")
        _echo("Press Ctrl-C to stop.")

        while True:
            if server.poll() is not None:
                _echo("The Potato server exited.")
                return 1
            if tunnel.poll() is not None:
                _echo("The tunnel exited.")
                return 1
            time.sleep(1)

    except KeyboardInterrupt:
        _echo("\nStopping ...")
        return 0
    except ProviderError as exc:
        _echo(f"Error: {exc}")
        return 1
    finally:
        for process, label in ((tunnel, "tunnel"), (server, "server")):
            if process is None or process.poll() is not None:
                continue
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    sys.exit(main())
