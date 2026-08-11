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

The board's available drivers are defined by its coordinator-side place config.
If a driver is missing, ask the person who maintains the fixture to update it;
the mapping is explained in :ref:`labgrid-hardware-place`.

Use build artifacts when needed
-------------------------------

Tests can retrieve artifacts from the GitHub workflow that produced them. The
test context contains the workflow run information. For a single, known
artifact, ``GitHub`` downloads it by name:

.. code:: python

   from hw_tests.github import GitHub


   artifacts = GitHub(context).download("my-build-artifact")
   image = artifacts / "my-image.bin"

Resolve artifacts by role with ``Images``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Different build systems publish the same board under different artifact names
and internal layouts (Buildroot, standalone U-Boot, Yocto). A single workflow
run also publishes one artifact per board. Hardcoding an artifact name and its
inner filenames ties a test to one build system and one board.

``Images`` removes that coupling: a test asks for a *role* (``spl``, ``uboot``,
``kernel``, ``dtb``, ...) and ``Images`` resolves the right file for whatever
was built.

.. code:: python

   from hw_tests.github import GitHub
   from hw_tests.images import Images


   images = Images(context, GitHub(context))
   spl = images.get("spl")
   uboot = images.get("uboot")

``Images.get`` resolves in three steps:

#. The build system, detected from the repository under test
   (``br2-external`` → ``br2``, ``u-boot`` → ``uboot``, ``lnxdsp-adi-meta`` →
   ``yocto``). Set ``flavor`` in the context to override detection for a local
   run. An unknown repository skips the test.
#. The artifact is selected from the run by matching every
   ``needs`` token as a case-insensitive substring of the artifact name, so
   ``needs = ["sc598", "ezkit"]`` picks the sc598 ezkit build and rejects
   ``ezlite`` or ``sc589``.
#. Role descriptor maps each role, per flavor, to an artifact and an inner-file pattern.

If a role is not defined for the detected flavor, the test is skipped rather
than failed (that image source does not support it).

The descriptor lives at ``tests/<category>/artifacts.toml``, next to the tests
that use it — ``category`` is the first path segment of the test name, so
``adsp/u-boot`` reads ``tests/adsp/artifacts.toml``. Each entry names an
artifact glob (matched against the run's artifact names) and a file glob
(matched against files inside it):

.. code:: toml

   [br2.spl]
   artifact = "*_defconfig"
   file = "bootstrap/u-boot-spl"
   [br2.kernel]
   artifact = "*_defconfig"
   file = "bootstrap/Image"

   [yocto.spl]
   artifact = "*"
   file = "u-boot-spl-*.elf"

The file glob may include directories when a workflow publishes a bundle;
``Images.get`` returns the matching file below the extracted bundle, and
``Images.artifact_path`` returns its resolved path inside that bundle for
serving it at the same HTTP path.

Pull a role from another repository
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A role can name a ``source`` to resolve its artifact from a different
repository's run instead of the run under test — for example a kernel test that
boots on SPL and U-Boot built by the ``u-boot`` repo and an initramfs from
``br2-external``:

.. code:: toml

   [linux.uboot]
   artifact = "*"
   file = "u-boot"
   source = "uboot"

Each named source is configured in ``config.toml`` with its repository and,
optionally, a branch and an exact run to pin:

.. code:: toml

   [sources.uboot]
   repository = "analogdevicesinc/u-boot"
   branch = "adi-u-boot-2025.10.y"
   # run_id = "1234567890"   # pin an exact run; otherwise latest green is used

Without ``run_id``, ``Images`` resolves the newest successful run on the branch
that actually carries the artifact, so a role does not go stale as artifacts
expire. Set ``run_id`` to pin an exact run, e.g. when bisecting a regression in
the boot chain.

For a local run that needs artifacts, provide ``GITHUB_TOKEN`` and
``workflow_run_url`` as shown in :ref:`run-a-test`. Without a token, ``Images``
falls back to files placed locally by ``GitHub.download``; see
:ref:`run-a-test`.

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
