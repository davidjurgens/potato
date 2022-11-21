"""
Logging functionalities.
"""

import logging


def init_logger(config):
    """
    Initialize logger.
    """
    logger_name = config.get("logger_name", "potato")
    logger = logging.getLogger(logger_name)

    logger.setLevel(logging.INFO)
    logging.basicConfig()

    if config.get("verbose"):
        logger.setLevel(logging.DEBUG)

    if config.get("very_verbose"):
        logger.setLevel(logging.NOTSET)
