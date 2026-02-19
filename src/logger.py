"""Central logger — import `log` from here in every module."""

import logging
import sys


def _setup() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s  %(levelname)-8s  %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger = logging.getLogger("smolstt")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


log = _setup()
