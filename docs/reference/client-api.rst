.. description::

   Test API and client reference for hw-test.

.. _labgrid-client-repo:

Test API and client reference
=============================

A client is the test process that reserves a board slot and drives the board.
This page assumes the board is already registered. To add a new board, see
:ref:`integrate-hardware`.

For the first local run, virtualenv setup, ``LG_COORDINATOR``, and basic
``pytest`` commands, start with :ref:`run-a-test`. This page only
covers reusable client code.

For labgrid command details, use the upstream
:external+labgrid:doc:`labgrid documentation <index>`.

Useful labgrid inspection commands:

.. code:: bash

   labgrid-client places
   labgrid-client resources
   labgrid-client who
   labgrid-client -p <place> show

Use the client API
++++++++++++++++++

Tests should use ``hw_tests.labgrid.LabgridClient`` instead of open-coding
labgrid session handling. It selects a matching place from ``needs``, acquires
it, configures SSH, and releases it at the end.

Small smoke test:

.. code:: python

   from hw_tests.labgrid import LabgridClient


   def test_smoke(context):
       client = LabgridClient(context)
       with client.acquire() as target:
           ssh = target.get_driver("SSHDriver")
           ssh.run_check("true")

U-Boot style test:

The images are resolved by role with ``Images``, so the same test runs against
Buildroot, standalone U-Boot, and Yocto builds. See
:ref:`write-a-test` for how flavor detection, ``needs``-based target selection,
and the ``tests/<category>/artifacts.toml`` descriptor work.

.. code:: python

   from hw_tests.github import GitHub
   from hw_tests.images import Images
   from hw_tests.labgrid import LabgridClient


   def test_uboot_version(context):
       images = Images(context, GitHub(context))

       spl = images.get("spl")
       uboot_image = images.get("uboot")

       client = LabgridClient(context)
       with client.acquire() as target:
           spi_boot = target.get_driver("DigitalOutputProtocol", name="spi_boot")
           power = target.get_driver("PowerProtocol")
           ssh = target.get_driver("SSHDriver")
           openocd = target.get_driver("OpenOCDDriver", activate=False)
           uboot = target.get_driver("UBootDriver", name="uboot", activate=False)

           spi_boot.set(False)
           power.cycle()
           ssh.put(str(spl), "u-boot-spl")
           ssh.put(str(uboot_image), "u-boot")
           spi_boot.set(True)

           target.activate(openocd)
           try:
               openocd.execute(openocd.load_commands)
           finally:
               target.deactivate(openocd)

           target.activate(uboot)
           uboot.console.sendline("version")
           uboot.console.expect("U-Boot", timeout=30)

Test configuration
++++++++++++++++++

Each test has a ``config.toml`` that contains default context values of a test
set. For example, the ``needs`` list selects compatible
:ref:`board slots <hw-test-glossary>`:

.. code:: toml

   needs = ["sc598", "ezkit"]

Any context value can be overridden when triggering a test; see
:ref:`run-a-test` for the local command-line form and :ref:`run-tests-in-ci`
for GitHub Actions.
