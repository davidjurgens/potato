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

    return parser.parse_args()
