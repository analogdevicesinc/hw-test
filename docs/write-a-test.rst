.. description::

   A practical guide to writing and trying a hardware test with hw-test.

.. _write-a-test:

Write a test
============

Use this guide when you have a supported board and want to add a test for it.
It assumes the board has already been added to the shared hardware pool. If it
has not, start with :ref:`integrate-hardware`.

A hardware test is a small Python test plus a ``config.toml`` file. The
configuration says which boards can run it. The Python code says what to do
with the selected board.

Check that the platform is available
------------------------------------

A platform is supported when at least one compatible board is available in the
shared pool. Ask your team for the platform's capability tags and the controls
it exposes. Common examples are ``adsp`` and ``sc598`` for board selection, and
``ssh``, a serial console, power control, or a debugger for test operations.

If you do not know whether a board is already available, the infrastructure
owner can check the shared pool. If it is not, see :ref:`integrate-hardware`
before writing a test that depends on it.

Create the test directory
-------------------------

Give the test a descriptive, stable path under ``tests/``. For example:

.. code:: text

   tests/adsp/my-board-smoke/
     config.toml
     test.py
     requirements.txt

The directory path is the test name. In this example, its name is
``adsp/my-board-smoke``.

Describe the hardware you need
------------------------------

In ``config.toml``, list the board-selection tags provided by the platform.
These must match tags on a :ref:`board slot <hw-test-glossary>` (a Labgrid
Place). ``hw-test`` selects a board only when every value in ``needs``
matches that place's tags.

.. code:: toml

   needs = ["sc598", "ezkit"]

For example, a board slot tagged with ``family=adsp``, ``board=sc598``, and
``kind=ezkit`` matches this test because it has both ``sc598`` and ``ezkit``.
It does not matter which matching board is selected; ``hw-test`` reserves one
that is currently free.

Keep ``needs`` about hardware capabilities, not an individual board-slot name,
lab location, or the drivers the test will use. That lets the same test run on
any compatible board and makes the infrastructure easier to grow. To understand
how place tags are assigned, see :ref:`integrate-hardware`.

Write the test
--------------

Use ``LabgridClient`` to find and reserve a compatible board. The ``with``
block is important: it always releases the board, including when the test
fails.

.. code:: python

   from hw_tests.labgrid import LabgridClient


   def test_smoke(context):
       client = LabgridClient(context)
       with client.acquire() as target:
           ssh = target.get_driver("SSHDriver")
           ssh.run_check("true")

Drivers represent capabilities attached to the board: a serial console, power
switch, GPIO, debug probe, or SSH connection to the hardware host. Ask for a
driver by its protocol where possible, so the test does not depend on a
particular fixture's implementation.

For example, a test that controls boot mode and power might start like this:

.. code:: python

   with client.acquire() as target:
       boot_mode = target.get_driver("DigitalOutputProtocol", name="spi_boot")
       power = target.get_driver("PowerProtocol")

       boot_mode.set(True)
       power.cycle()

The board's available drivers are defined by its environment file. If a driver
is missing, ask the person who maintains the fixture to update it; the mapping
is explained in :ref:`labgrid-hardware-place`.

Use build artifacts when needed
-------------------------------

Tests can retrieve artifacts from the GitHub workflow that produced them. The
test context contains the workflow run information, and ``GitHub`` uses it to
download an artifact:

.. code:: python

   from hw_tests.github import GitHub


   artifacts = GitHub(context).download("my-build-artifact")
   image = artifacts / "my-image.bin"

For a local run that needs artifacts, provide ``GITHUB_TOKEN`` and
``workflow_run_url`` as shown in :ref:`run-a-test`.

To run against files you built locally instead, see :ref:`run-a-test`.

Try it locally
--------------

If the test has a ``requirements.txt`` file, install it first. Then run only
the test you are working on:

.. shell::

   $ python3 -m pip install -r tests/adsp/my-board-smoke/requirements.txt
   $ set='{"name": "adsp/my-board-smoke"}' pytest -vvv

The first run is a good time to verify that the test selects the intended type
of board. Avoid ``pytest tests`` while developing: it can reserve and run many
boards at once.

When the local test is reliable, add it to your workflow using
:ref:`run-tests-in-ci`.

Next steps
----------

* :ref:`run-a-test` for local setup and
  common failures.
* :ref:`integrate-hardware` if no compatible board exists.
* :ref:`labgrid-client-repo` for fuller driver
  examples and CI details.
