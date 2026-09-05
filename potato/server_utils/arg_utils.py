"""
Utility functions around parsing arguments.
"""

from argparse import ArgumentParser, RawDescriptionHelpFormatter


#: Commands `flask_server.main()` intercepts from sys.argv before this parser
#: runs. They cannot be `mode` choices -- each has its own flag grammar -- but
#: leaving them out of `--help` entirely hid `validate` and `preview`, which is
#: the loop every piece of Potato's agent-facing documentation is built around.
#: An agent that trusted `--help` concluded the documented workflow did not
#: exist in its build.
#:
#: `tests/unit/test_cli_dispatch.py` checks this list against the tokens really
#: dispatched, so a new command cannot be added without appearing here.
STAGE1_COMMANDS = {
    "validate": "check a config the way the server checks it at boot",
    "preview": "show what a config declares, and render it in a browser",
    "mcp": "run the MCP server for coding agents",
    "import": "build a project from an existing annotation file",
    "transcripts": "convert transcripts into annotation data",
    "convokit": "build a project from a ConvoKit corpus",
    "deploy": "put a task on a host, and take it down again",
    "share": "serve a task on a temporary public URL",
    "download-models": "fetch segmentation model weights",
}

STAGE1_HELP = "other commands:\n" + "\n".join(
    f"  {name:<17}{summary}" for name, summary in STAGE1_COMMANDS.items()
) + "\n\nRun `potato <command> --help` for that command's own options."


def arguments():
    """
    Creates and returns the arg parser for Potato on the command line.
    """
    parser = ArgumentParser(
        epilog=STAGE1_HELP,
        formatter_class=RawDescriptionHelpFormatter,
    )
    parser.set_defaults(show_path=False, show_similarity=False)

    parser.add_argument(
        "mode",
        # `transcripts` and `convokit` are deliberately absent: flask_server.main()
        # intercepts both from sys.argv before this parser ever runs, so listing
        # them here advertised modes that could not be reached. Any command
        # dispatched in that first stage must stay out of these choices --
        # tests/unit/test_cli_dispatch.py enforces that the two sets are disjoint.
        choices=['start', 'migrate', 'reset-password', 'codebook',
                 'repair-annotations'],
        # "currently supporting: start, migrate, ..." read as the complete
        # list of what Potato does, and it is not -- nine more commands are
        # dispatched before this parser runs and appear only in the epilog. A
        # reader who took the sentence at face value concluded `potato mcp`
        # and `potato validate` did not exist. Name what this argument accepts,
        # and say where the rest are.
        help=(
            "what to do with the config file. See 'other commands' below for "
            "the ones that take their own arguments instead"
        ),
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
        "--host",
        action="store",
        type=str,
        dest="host",
        help="interface to bind to (default: 0.0.0.0). Use 127.0.0.1 to accept "
             "only local connections, e.g. when fronting the server with a tunnel "
             "or reverse proxy.",
        default=None,
    )

    parser.add_argument(
        "--persist-sessions",
        action="store_true",
        dest="persist_sessions",
        help="Enable session persistence between server restarts (default: False)",
        default=False,
    )

    # SSL arguments (from master branch)
    parser.add_argument(
        "--ssl-cert",
        action="store",
        type=str,
        dest="ssl_cert",
        help="custom ssl cert location (should end in .pem)",
        default=None
    )

    parser.add_argument(
        "--ssl-key",
        action="store",
        type=str,
        dest="ssl_key",
        help="custom ssl key location (should end in .pem)",
        default=None
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

    # Password reset arguments
    parser.add_argument(
        "--username",
        action="store",
        type=str,
        dest="username",
        help="[reset-password mode] Username to reset password for",
        default=None,
    )

    # Annotation repair arguments (GH #167)
    parser.add_argument(
        "--apply",
        action="store_true",
        dest="apply",
        help="[repair-annotations mode] Write the repairs. Without this the run is a "
             "dry run that only reports what would change.",
        default=False,
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        dest="no_backup",
        help="[repair-annotations mode] Do not write user_state.json.bak before "
             "overwriting. Only meaningful with --apply.",
        default=False,
    )

    return parser.parse_args()
