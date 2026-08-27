import ipaddress
import logging
import logging.config
import re
from threading import RLock

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

_IPV4_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:\d{1,3}\.){3}\d{1,3}(?![A-Za-z0-9])"
)
_IPV6_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:(?:[0-9A-Fa-f]{1,4}:){2,}[0-9A-Fa-f:.%]*|::[0-9A-Fa-f:.%]+)"
    r"(?![A-Za-z0-9])"
)
_INTERNAL_HOST_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"ad\.analog\.com\b",
    re.IGNORECASE,
)

_sensitive_values = set()
_sensitive_values_lock = RLock()


def register_sensitive(value):
    """Register a runtime value for redaction from subsequent log output."""
    value = str(value)
    if len(value) < 4:
        return
    with _sensitive_values_lock:
        _sensitive_values.add(value)


def _replace_ip(match):
    value = match.group(0)
    try:
        ipaddress.ip_address(value.split("%", maxsplit=1)[0])
    except ValueError:
        return value
    return "<IP>"


def redact_text(value):
    """Redact network and registered sensitive values from log text."""
    value = str(value)
    with _sensitive_values_lock:
        registered = sorted(_sensitive_values, key=len, reverse=True)

    for sensitive in registered:
        value = value.replace(sensitive, "<REDACTED>")
    value = _INTERNAL_HOST_RE.sub("<INTERNAL_HOST>", value)
    value = _IPV6_RE.sub(_replace_ip, value)
    return _IPV4_RE.sub(_replace_ip, value)


class RedactingFormatter(logging.Formatter):
    """Apply redaction after the wrapped formatter renders a log record."""

    def __init__(self, formatter):
        self._formatter = formatter

    def format(self, record):
        return redact_text(self._formatter.format(record))


def install_log_redaction(handlers):
    """Wrap handlers with the redacting formatter, without double wrapping."""
    for handler in handlers:
        if handler is None or isinstance(handler.formatter, RedactingFormatter):
            continue
        formatter = handler.formatter or logging.Formatter()
        handler.setFormatter(RedactingFormatter(formatter))


def install_pytest_log_redaction(config):
    """Install redaction on pytest's live, captured, and file log handlers."""
    handlers = list(logging.getLogger().handlers)
    plugin = config.pluginmanager.get_plugin("logging-plugin")
    if plugin is not None:
        for name in (
            "log_cli_handler",
            "caplog_handler",
            "report_handler",
            "log_file_handler",
        ):
            handlers.append(getattr(plugin, name, None))
    install_log_redaction(handlers)


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
    install_log_redaction(logging.getLogger().handlers)
