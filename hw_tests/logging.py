import logging
import logging.config

NC = "\033[0m"
BLUE = "\033[94m"
GREEN = "\033[92m"
ORANGE = "\033[38;5;208m"
RED = "\033[91m"

LEVEL_COLORS = {
    logging.INFO: BLUE,
    logging.WARNING: ORANGE,
    logging.ERROR: RED,
    logging.CRITICAL: RED,
}


class ColorFormatter(logging.Formatter):
    def format(self, record):
        level_color = LEVEL_COLORS.get(record.levelno, "")
        record.levelname = f"{level_color}{record.levelname}:{NC}"
        return super().format(record)


def gha_escape(value, *, prop=False):
    """Escape a string for a GitHub Actions workflow command."""
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if prop:
        value = value.replace(":", "%3A").replace(",", "%2C")
    return value


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "colored": {
            "()": ColorFormatter,
            "fmt": "%(levelname)s %(message)s",
        },
    },
    "handlers": {
        "default": {
            "level": "INFO",
            "formatter": "colored",
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["default"],
        "level": "INFO",
    },
    "loggers": {
        "hw_tests": {
            "level": "INFO",
            "propagate": True,
        },
    },
}


def set_logging():
    logging.config.dictConfig(LOGGING_CONFIG)
