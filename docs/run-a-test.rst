.. description::

   Run one existing hardware test from your shell.

.. _run-a-test:

Run a test
==========

Use this guide when there is already a supported board in the shared pool and
you want to run one existing test against it. This is the smallest useful local
workflow.

Before you start, you need:

* the address of the shared hardware service (the coordinator),
* a supported board available through that service, and
* the name of a test that can run on that board.

Set up your environment
-----------------------

From a checkout of ``hw-test``:

.. shell::

   $ python3 -m venv .venv
   $ source .venv/bin/activate
   $ python3 -m pip install --upgrade pip
   $ python3 -m pip install -e '.[test]'

This creates a Python environment and installs ``hw-test`` in editable mode.

Point ``hw-test`` at the shared hardware service (the
:ref:`shared coordinator <hw-test-glossary>`):

.. code:: bash

   export LG_COORDINATOR=<coordinator>

Run one test
------------

Run a single small test first:

.. shell::

   $ set='{"name": "adsp/smoke"}' pytest -vvv

The ``set`` variable is the test context override. Its most important field is
``name``, which matches the test directory under ``tests/``. It is JSON so a
test can carry nested, test-specific configuration.
See
:ref:`run-tests-in-ci` for how the same object is passed in CI.

Some tests have extra Python requirements. Install them before running:

.. shell::

   $ python3 -m pip install -r tests/adsp/u-boot/requirements.txt
   $ set='{"name": "adsp/u-boot"}' pytest -vvv

Choose a specific board
-----------------------

By default ``hw-test`` runs the test on the first free
:ref:`board slot <hw-test-glossary>` whose tags match the test's ``needs``. When
several boards match and you want a particular one, name it with
``labgrid_target``:

.. shell::

   $ set='{"name": "adsp/u-boot", "labgrid_target": "MUN-01-SC598_EZKIT-02"}' \
       pytest -vvv

The value is the board slot name shown by ``labgrid-client places``.

Run against local build files
-----------------------------

Some tests download build artifacts from a GitHub Actions run. To use files you
built locally instead, place them where the test expects and run without a
token. ``hw-test`` looks under ``_artifacts/<test-name>/0/`` and tells you the
exact path it expects:

.. shell::

   $ set='{"name": "adsp/bootstrap"}' pytest -s
     WARNING hw_tests.github:
       Neither 'workflow_run_url' in context or 'GITHUB_REPOSITORY' in
       environment, cannot download artifacts; assuming you have them at
       '<cwd>/_artifacts/adsp/bootstrap/0'
   $ cp /path/to/my.dtb _artifacts/adsp/bootstrap/0/my.dtb
   $ set='{"name": "adsp/bootstrap"}' pytest -s
     ... test uses the local file ...

To download artifacts from a GitHub Actions run instead, set ``GITHUB_TOKEN``
and pass ``workflow_run_url``:

.. code:: bash

   export GITHUB_TOKEN=<token>

.. shell::

   $ set='{"name": "adsp/bootstrap", "workflow_run_url": "https://api.github.com/repos/example/project/actions/runs/123"}' \
       pytest -vvs

``GITHUB_TOKEN`` is a GitHub personal access token. You can create one from any
GitHub account under **Settings → Developer settings → Personal access tokens**;
a token with read access to the repository is enough.

For the public ``analogdevicesinc`` repositories you do **not** need to belong
to the Analog Devices organization to download artifacts, so any valid token
works. You do, however, need to be a signed-in GitHub user.

Do not run the whole suite while bringing up a setup
----------------------------------------------------

Avoid this while you are still getting one test working:

.. code:: bash

   pytest tests

It can run many hardware tests and reserve every matching board. Start with one
test, one board slot, and one board.

If the run fails
----------------

See :ref:`hw-test-troubleshooting` for the local-run checklist
(``LG_COORDINATOR``, matching tags, env file, SSH reachability).
