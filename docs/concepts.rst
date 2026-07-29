.. description::

   The mental model behind hw-test in a few minutes.

.. _hw-test-concepts:

How hw-test works
=================

``hw-test`` runs tests against hardware and shares a pool of
boards safely between teams. You can run it from a developer shell or from CI.

You do not operate the hardware directly. A test asks for a board by its
capabilities (for example ``sc598`` and ``ezkit``); ``hw-test`` finds a
compatible free board, reserves it, runs the test, and releases it afterwards.

The pieces
----------

Shared coordinator
  The booking service. It keeps the inventory of hardware and records who has
  reserved each board. You connect to it by setting ``LG_COORDINATOR``; your
  team/organization owns and runs it, so you join it rather than set one up.

Hardware host
  The machine physically wired to a board and its equipment: serial console,
  power switch, debug probe, GPIO. (Labgrid calls this an *exporter*.)

Board slot
  A reservable board in the shared pool is described by capability tags rather
  than by location or serial number. A test selects one by tags. (Labgrid calls
  this a *place*.)

Driver
  A single control on the board. Power, console, GPIO, SSH, OpenOCD, etc. A
  test asks for a driver by its protocol.

You rarely touch these directly. Each term maps to a Labgrid word. See
:ref:`glossary <hw-test-glossary>`.

Where to go next
----------------

* Run an existing test on a board that sis already set up: :ref:`run-a-test`.
* Write a new test for a supported platform: :ref:`write-a-test`.
* Add your board or fixture to the shared pool: :ref:`integrate-hardware`.
* Run hardware tests from CI: :ref:`run-tests-in-ci`.
* Set up a new hardware host for your team: :ref:`set-up-a-hardware-host`.
