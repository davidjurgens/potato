"""
Config module.
"""

import yaml

config = {}


def init_config(config_filepath):
    global config
    with open(config_filepath, "r") as file_p:
        config.update(yaml.safe_load(file_p))
