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
        choices=['start', 'get', 'list'],
        help="set the mode when potato is used, currently supporting: start, get, list",
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
        help="Whether to require password authentication (true/false)",
        default=True,
    )

    parser.add_argument(
        "--persist-sessions",
        action="store_true",
        dest="persist_sessions",
        help="Enable session persistence between server restarts (default: False)",
        default=False,
    )

    return parser.parse_args()
