import logging

from hw_tests.logging import (
    RedactingFormatter,
    install_log_redaction,
    redact_text,
    register_sensitive,
)


def test_redact_text_hides_ipv4_ipv6_and_internal_hostname():
    text = (
        "wget 192.0.2.42:45678 from 198.51.100.80; "
        "build runner@build-host.ad.analog.com via 2001:db8::1"
    )

    redacted = redact_text(text)

    assert "192.0.2.42" not in redacted
    assert "198.51.100.80" not in redacted
    assert "2001:db8::1" not in redacted
    assert "build-host.ad.analog.com" not in redacted
    assert redacted.count("<IP>") == 3
    assert "<INTERNAL_HOST>" in redacted


def test_redact_text_hides_registered_values():
    register_sensitive("temporary-coordinator-name")

    assert redact_text("connecting to temporary-coordinator-name") == (
        "connecting to <REDACTED>"
    )


def test_handler_redacts_formatted_log_record():
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    install_log_redaction([handler])

    record = logging.LogRecord(
        "StepLogger",
        logging.INFO,
        __file__,
        1,
        "connecting to %s",
        ("192.0.2.42",),
        None,
    )

    assert isinstance(handler.formatter, RedactingFormatter)
    assert "192.0.2.42" not in handler.format(record)
    assert "<IP>" in handler.format(record)
