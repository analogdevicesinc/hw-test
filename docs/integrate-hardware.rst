.. description::

   Bring a board or test fixture into the shared hw-test infrastructure.

.. _integrate-hardware:

Integrate hardware
==================

Use this guide when you want your Device Under Test (DUT) to be
available to ``hw-test``. By the end, a test can request its capabilities and
run against it without knowing where it is physically connected.

The integration work has two parts. First, you need to describe what is
physically connected to the hardware host. Then, describe what a test is
allowed to do with it.

Before you begin
----------------

Have these details ready:

* the board or fixture name and the platform it supports;
* the operations a test needs: console, power cycle, reset, boot-mode GPIO,
  debug probe, SSH, or another interface;
* stable identifiers for the attached equipment, such as USB serial numbers or
  fixed USB paths; and
* a hardware host connected to the shared test service.

If there is no prepared hardware host, work through
:ref:`set-up-a-hardware-host` first. If a similar board is already integrated,
use its coordinator-side place config as the starting point for the new one.

The integration path
--------------------

1. Decide what a test should be able to do

   Start from the test intent, not the physical wiring. A smoke test may only
   need SSH. A boot test may need a console, power control, a boot-mode GPIO,
   and a debugger. This becomes the small, stable interface test authors use.

2. Identify the connected equipment

   On the hardware host, find stable IDs for serial adapters, debug probes,
   power controllers, and GPIO. Do not base the setup on a changing device name
   such as ``/dev/ttyUSB0``.

3. Publish the equipment to the shared pool.

   Add the resources to the hardware-host configuration and confirm the host
   can see them. A resource is one controllable thing, for example the board's
   serial console or its power outlet.

4. Create one reservable :ref:`board slot <hw-test-glossary>`

   Associate the board's resources with a named slot and give the slot useful
   capability tags such as ``sc598`` and ``ezkit``. Tests use these tags to
   find compatible hardware; they should not be tied to a lab location or a
   single board serial number.

5. Add the board config to the coordinator

   Use ``labgrid-client -p <board-slot> edit`` to store the mapping from
   published equipment to the capabilities exposed to a test, such as a serial
   console, power switch, or OpenOCD driver. This config is shared by all
   clients; no ``hw-test/envs`` file is needed.

6. Prove each operation before writing a test

   Reserve the board and try power, console, GPIO, image upload, and debug
   operations one at a time. This separates fixture setup problems from test
   code problems.

7. Run a small test

   Add or select a test whose ``needs`` tags match the board slot, then run it
   locally. :ref:`write-a-test` shows the test side.

Detailed implementation guide
-----------------------------

The steps above are the integration checklist. Follow
:ref:`register-a-board` for the exact commands
and configuration examples, including exporter resources, board tags, and
the coordinator-side place config shape.

Choosing good capabilities
--------------------------

Make the board interface useful to the next team:

* Use tags for what board the test requires, for example processor family,
  board model, or fixture type.
* Use driver names for distinct controls on the same board, for example
  ``spi_boot`` for the boot-mode switch.
* Use stable hardware identifiers for physical equipment, so reconnecting
  a USB device does not silently change the fixture.
* Keep shared equipment explicit. If several boards share a debug probe or GPIO
  controller, model that relationship so it is reserved safely.

When to ask for help
--------------------

Ask the team that owns the test infrastructure when the hardware host needs
network access, new system packages, credential setup, a new power-controller
type, or a custom debug tool. These are host-level changes that should be
reviewed before a board is made available to other teams.
