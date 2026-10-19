.. description::

   Build the test context and select the tests to run.

Test executor
=============

These modules run before a test. ``collect`` selects which tests to run, and
``context`` builds the test configuration from its ``config.toml``, overwriting
from the provided context, for example, the git reference to get the artifacts
from or explicit board to run the test on.

Context
-------

.. automodule:: hw_tests.context

Collect
-------

.. automodule:: hw_tests.collect
