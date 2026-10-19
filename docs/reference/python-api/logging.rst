.. description::

   Logging setup and redaction.

Logging
=======

.. automodule:: hw_tests.logging
   :no-members:

.. autoclass:: hw_tests.logging.RedactingFormatter

.. autoclass:: hw_tests.logging.ColorFormatter

.. autofunction:: hw_tests.logging.set_logging

.. autofunction:: hw_tests.logging.register_sensitive

.. autofunction:: hw_tests.logging.redact_text

.. autofunction:: hw_tests.logging.install_log_redaction

.. autofunction:: hw_tests.logging.install_pytest_log_redaction

.. autofunction:: hw_tests.logging.gha_escape
