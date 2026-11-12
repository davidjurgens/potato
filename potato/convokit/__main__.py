"""Allow ``python -m potato.convokit`` alongside ``potato convokit``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
