"""
Config module.
"""

import yaml

config = {}


def init_config(args):
    global config
    with open(args.config_file, "r") as file_p:
        config.update(yaml.safe_load(file_p))

    config.update({
        "verbose": args.verbose,
        "very_verbose": args.very_verbose,
        "__debug__": args.debug,
        "__config_file__": args.config_file,
    })
