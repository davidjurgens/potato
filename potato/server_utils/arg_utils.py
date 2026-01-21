"""
Utility functions around parsing arguments.
"""

from argparse import ArgumentParser


def arguments():
    """
    Creates and returns the arg parser for Potato on the command line.
    """
    parser = ArgumentParser()
    parser.set_defaults(show_path=False, show_similarity=False)

    parser.add_argument(
        "mode",
        choices=['start', 'get', 'list', 'migrate'],
        help="set the mode when potato is used, currently supporting: start, get, list, migrate",
        default="start",
    )

    parser.add_argument("config_file")

    parser.add_argument(
        "-p",
        "--port",
        action="store",
        type=int,
        dest="port",
        help="The port to run on",
        default=None,
    )

    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Report verbose output", default=False
    )

    parser.add_argument(
        "--debug", action="store_true", help="Launch in debug mode with no login", default=False
    )

    parser.add_argument(
        "--debug-log",
        action="store",
        type=str,
        dest="debug_log",
        choices=['all', 'ui', 'server', 'none'],
        help="Control debug logging: 'all' (UI and server), 'ui' (frontend only), 'server' (backend only), 'none' (disable)",
        default=None,
    )

    parser.add_argument(
        "--debug-phase",
        action="store",
        type=str,
        dest="debug_phase",
        help="Skip directly to a specific phase (e.g., 'annotation', 'poststudy') or page name. Requires --debug flag.",
        default=None,
    )

    parser.add_argument(
        "--veryVerbose",
        action="store_true",
        dest="very_verbose",
        help="Report very verbose output",
        default=False,
    )

    parser.add_argument(
        "--with-custom-js",
        action="store_true",
        dest="customjs",
        help="Use a custom js module served from vite."
    )

    parser.add_argument(
        "--custom-js-hostname",
        action="store",
        type=str,
        dest="customjs_hostname",
        help="custom hostname for potato.js serving",
        default=None,
    )

    parser.add_argument(
        "--require-password",
        action="store",
        type=lambda x: str(x).lower() == 'true',
        dest="require_password",
        help="Whether to require password authentication (true/false). If not specified, uses config file value.",
        default=None,
    )

    parser.add_argument(
        "--persist-sessions",
        action="store_true",
        dest="persist_sessions",
        help="Enable session persistence between server restarts (default: False)",
        default=False,
    )

    # Migration-specific arguments
    parser.add_argument(
        "--to-v2",
        action="store_true",
        dest="to_v2",
        help="[migrate mode] Migrate configuration to v2 format",
        default=False,
    )

    parser.add_argument(
        "--output", "-o",
        dest="output_file",
        help="[migrate mode] Output file path (default: print to stdout)",
        default=None,
    )

    parser.add_argument(
        "--in-place", "-i",
        action="store_true",
        dest="in_place",
        help="[migrate mode] Modify the config file in place",
        default=False,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="[migrate mode] Show what changes would be made without applying them",
        default=False,
    )

    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        dest="quiet",
        help="[migrate mode] Suppress informational output",
        default=False,
    )

    return parser.parse_args()
